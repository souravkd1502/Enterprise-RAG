"""Real signed-token verification and HTTP trust-boundary tests; JWKS is local."""

import asyncio
import io
import json
import logging
import os
import time
import unittest
from dataclasses import FrozenInstanceError
from typing import Annotated
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

from src.api.dependencies import get_tenant_context
from src.api.main import app
from src.core.config import Settings, get_settings
from src.core.logging import JsonFormatter
from src.core.security import TokenVerifier
from src.core.tenancy import TenantContext
from test_config import ENVIRONMENT


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(cls.private_key.public_key(), as_dict=True)
        cls.jwk.update(kid="test-key", use="sig", alg="RS256")

    def setUp(self):
        environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.settings = Settings(_env_file=None)
        self.verifier = TokenVerifier(self.settings)
        fetch = patch.object(self.verifier._jwks, "fetch_data", return_value={"keys": [self.jwk]})
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)

    def token(self, changes=None, *, omit=(), key=None):
        claims = {
            "iss": self.settings.jwt_issuer, "aud": self.settings.jwt_audience,
            "exp": int(time.time()) + 300, "tenant_id": "tenant-a", "user_id": "user-a",
        }
        claims.update(changes or {})
        for name in omit:
            claims.pop(name)
        return jwt.encode(claims, key or self.private_key, algorithm="RS256", headers={"kid": "test-key"})

    def test_valid_signature_produces_immutable_explicit_identity(self):
        context = self.verifier.verify(self.token())
        self.assertEqual(context, TenantContext("tenant-a", "user-a"))
        with self.assertRaises(FrozenInstanceError):
            context.tenant_id = "tenant-b"

    def test_expiry_issuer_audience_and_identity_claims_are_enforced(self):
        cases = (
            {"exp": int(time.time()) - 60}, {"iss": "other-issuer"},
            {"aud": "other-api"}, {"tenant_id": ""}, {"user_id": 42},
            {"tenant_id": "tenant\nforged"}, {"nbf": int(time.time()) + 300},
        )
        for claims in cases:
            with self.subTest(claims=tuple(claims)), self.assertRaises(InvalidTokenError):
                self.verifier.verify(self.token(claims))
        for claim in ("exp", "iss", "aud", "tenant_id", "user_id"):
            with self.subTest(missing=claim), self.assertRaises(InvalidTokenError):
                self.verifier.verify(self.token(omit=(claim,)))

    def test_tampered_and_unknown_key_tokens_are_rejected(self):
        with self.assertRaises(InvalidTokenError):
            self.verifier.verify(self.token(key=self.wrong_key))
        unknown_key_token = jwt.encode(
            {"exp": int(time.time()) + 300}, self.private_key,
            algorithm="RS256", headers={"kid": "unknown-key"},
        )
        with self.assertRaises(PyJWKClientError):
            self.verifier.verify(unknown_key_token)

    def test_unapproved_algorithm_rejected_before_key_fetch(self):
        token = jwt.encode({"tenant_id": "tenant-a"}, "x" * 64, algorithm="HS256", headers={"kid": "test-key"})
        with self.assertRaises(InvalidTokenError):
            self.verifier.verify(token)
        self.fetch.assert_not_called()

    def test_configurable_subject_claim(self):
        verifier = TokenVerifier(Settings(_env_file=None, jwt_user_id_claim="sub"))
        with patch.object(verifier._jwks, "fetch_data", return_value={"keys": [self.jwk]}):
            identity = verifier.verify(self.token({"sub": "subject-user"}, omit=("user_id",)))
        self.assertEqual(identity.user_id, "subject-user")

    def protected_app(self):
        application = FastAPI()
        application.state.token_verifier = self.verifier
        application.state.access_service = AsyncMock()

        @application.get("/protected")
        async def protected(context: Annotated[TenantContext, Depends(get_tenant_context)]):
            await asyncio.sleep(0)
            logging.getLogger("tests.auth_route").info("Protected operation completed")
            return {"tenant_id": context.tenant_id, "user_id": context.user_id}

        return application

    def test_http_requires_bearer_and_hides_token_errors(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.protected_app()), base_url="http://test") as client:
                for authorization in (None, "Basic invalid", "Bearer malformed", "Bearer " + self.token({"aud": "wrong"})):
                    headers = {"Authorization": authorization} if authorization else {}
                    response = await client.get("/protected", headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")
                    self.assertNotIn("wrong", response.text)
                with patch.object(self.verifier, "verify", side_effect=PyJWKClientConnectionError("private-url")):
                    with self.assertLogs("src.api.dependencies", level="ERROR") as logs:
                        response = await client.get("/protected", headers={"Authorization": "Bearer token"})
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn("private-url", response.text + " ".join(logs.output))

        asyncio.run(run())

    def test_concurrent_http_identity_and_logging_ignore_spoofed_ids(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("tests.auth_route")
        previous_level = logger.level
        previous_propagate = logger.propagate
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, previous_level)
        self.addCleanup(setattr, logger, "propagate", previous_propagate)

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.protected_app()), base_url="http://test") as client:
                async def request(tenant):
                    response = await client.get("/protected?tenant_id=spoofed", headers={
                        "Authorization": "Bearer " + self.token({"tenant_id": tenant, "user_id": tenant + "-user"}),
                        "X-Tenant-ID": "spoofed", "X-User-ID": "spoofed",
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"tenant_id": tenant, "user_id": tenant + "-user"})
                await asyncio.gather(request("tenant-a"), request("tenant-b"))

        asyncio.run(run())
        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual({event["tenant_id"] for event in events}, {"tenant-a", "tenant-b"})
        self.assertEqual(len({event["request_id"] for event in events}), 2)
        for event in events:
            self.assertEqual(event["user_id"], event["tenant_id"] + "-user")
        # A subsequent unauthenticated scope must not inherit either identity.
        logger.info("Outside request")
        self.assertIsNone(json.loads(stream.getvalue().splitlines()[-1])["tenant_id"])

    def test_real_application_lifespan_and_public_health(self):
        async def run():
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.get("/health")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"status": "ok"})
                    self.assertIsInstance(app.state.token_verifier, TokenVerifier)
            self.assertFalse(hasattr(app.state, "token_verifier"))

        with (
            patch("src.api.main.configure_logging"),
            patch("src.core.config.Settings", return_value=self.settings),
            patch("src.api.main.mongodb_database"),
            patch("src.api.main.minio_object_store"),
            patch("src.api.main.ensure_auth_indexes", new_callable=AsyncMock),
        ):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
