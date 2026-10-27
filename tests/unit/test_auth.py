"""Local signing, password handling, token/session boundaries, and safe HTTP errors."""

import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from jwt.exceptions import InvalidTokenError
import jwt
from pydantic import ValidationError
from pymongo.errors import ConnectionFailure

from src.api.main import auth_error_handler, safe_auth_validation, app
from src.api.routes.auth import router
from src.core.config import Settings
from src.core.exceptions import AuthError, AuthRejected, AuthUnavailable, AuthRateLimited
from src.core.security import LocalTokenCodec
from src.core.tenancy import TenantContext
from src.services.auth_service import AuthService
from test_config import ENVIRONMENT

PASSWORD = "correct horse battery staple"


class _KeyFixture:
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.key_path = Path(cls.directory.name) / "private.pem"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def settings(self, **changes):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            return Settings(_env_file=None, auth_mode="local", auth_private_key_path=self.key_path, **changes)


class LocalTokenTests(_KeyFixture, unittest.TestCase):
    def test_account_token_has_explicit_scope_and_cannot_be_retyped(self):
        codec = LocalTokenCodec(self.settings())
        issued = codec.issue_identity("user-a", None, uuid4().hex, int(time.time()) + 3600)
        verified = codec.decode(issued.access_token, "access")
        self.assertIsNone(verified.context)
        self.assertEqual(verified.user_id, "user-a")
        claims = jwt.decode(issued.access_token, options={"verify_signature": False})
        self.assertEqual(claims["auth_scope"], "account")
        claims["auth_scope"] = "tenant"
        inconsistent = jwt.encode(claims, codec._private_key, algorithm="RS256",
            headers={"kid": codec._kid, "typ": "access+jwt"})
        with self.assertRaises(InvalidTokenError):
            codec.decode(inconsistent, "access")

    def test_development_invitation_links_are_forbidden_in_production(self):
        with self.assertRaises(ValidationError):
            self.settings(app_env="production", auth_invitation_development_links=True)

    def test_openapi_exposes_workspace_authentication_and_examples(self):
        schema = app.openapi()
        self.assertEqual(schema["components"]["securitySchemes"]["AccessToken"]["scheme"], "bearer")
        self.assertIn("/tenants/invitations/accept", schema["paths"])
        self.assertIn("/auth/select-tenant", schema["paths"])
        self.assertIn("name", schema["components"]["schemas"]["SignupRequest"]["required"])
        self.assertIn("examples", schema["components"]["schemas"]["SignupRequest"]["properties"]["email"])

    def test_es256_uses_a_p256_key(self):
        path = self.key_path.parent / "ec-private.pem"
        key = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        codec = LocalTokenCodec(self.settings(jwt_algorithm="ES256").model_copy(update={"auth_private_key_path": path}))
        context = TenantContext("tenant-a", "user-a")
        tokens = codec.issue(context, uuid4().hex, int(time.time()) + 3600)
        self.assertEqual(codec.decode(tokens.access_token, "access").context, context)

    def test_purpose_identity_signature_and_expiry(self):
        codec = LocalTokenCodec(self.settings())
        context = TenantContext("tenant-a", "user-a")
        issued = codec.issue(context, uuid4().hex, int(time.time()) + 3600)
        self.assertEqual(codec.decode(issued.access_token, "access").context, context)
        self.assertEqual(codec.decode(issued.refresh_token, "refresh").context, context)
        with self.assertRaises(InvalidTokenError):
            codec.decode(issued.refresh_token, "access")
        expired = codec.issue(context, uuid4().hex, int(time.time()) - 60)
        with self.assertRaises(InvalidTokenError):
            codec.decode(expired.access_token, "access")
        header, payload, signature = issued.access_token.split(".")
        with self.assertRaises(InvalidTokenError):
            codec.decode(header + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:], "access")

    def test_missing_signing_key_fails_with_safe_error(self):
        settings = self.settings().model_copy(update={"auth_private_key_path": self.key_path.parent / "secret-key-path"})
        with self.assertRaisesRegex(RuntimeError, "^Local authentication signing key is missing or invalid$"):
            LocalTokenCodec(settings)

    def test_local_mode_does_not_require_jwks(self):
        with patch.dict(os.environ, {key: value for key, value in ENVIRONMENT.items() if key != "JWT_JWKS_URL"}, clear=True):
            settings = Settings(_env_file=None, auth_mode="local", auth_private_key_path=self.key_path)
        self.assertIsNone(settings.jwt_jwks_url)


class AuthServiceTests(_KeyFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.configuration = self.settings()
        self.repository = MagicMock()
        for name in ("rate_allowed", "create_user", "find_email", "find_user", "create_session", "active_session", "rotate", "revoke"):
            setattr(self.repository, name, AsyncMock())
        self.repository.rate_allowed.return_value = True
        self.repository.create_user.return_value = {"tenant_id": "tenant-a", "user_id": "user-a"}
        self.repository.tenants.workspaces = AsyncMock(return_value=[{"tenant_id": "tenant-a", "name": "Test", "status": "active", "created_at": datetime.now(timezone.utc), "role": "OWNER"}])
        self.repository.tenants.membership = AsyncMock(return_value={"role": "OWNER"})
        self.repository.active_session.return_value = {"revoked": False, "tenant_id": "tenant-a"}
        self.repository.find_user.return_value = {"active": True}
        self.service = AuthService(self.repository, LocalTokenCodec(self.configuration), self.configuration)
        await self.service.initialize()

    async def test_signup_stores_argon2_hash_and_refresh_digest_only(self):
        issued = await self.service.signup("Person@Example.com", PASSWORD, "Person", "Test")
        email, encoded, name, workspace = self.repository.create_user.await_args.args
        self.assertEqual(email, "person@example.com")
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertNotIn(PASSWORD, encoded)
        session_args = self.repository.create_session.await_args.args
        self.assertEqual(len(session_args[2]), 64)
        self.assertNotEqual(session_args[2], issued.refresh_token)
        self.assertEqual(issued.tenant_id, "tenant-a")

    async def test_login_rejects_bad_credentials_and_inactive_accounts(self):
        self.repository.find_email.return_value = None
        with self.assertRaises(AuthRejected):
            await self.service.login("missing@example.com", PASSWORD)
        self.repository.find_email.return_value = {"password_hash": self.service._dummy_hash, "active": False}
        with self.assertRaises(AuthRejected):
            await self.service.login("disabled@example.com", PASSWORD)
        self.repository.create_session.assert_not_awaited()

    async def test_access_requires_an_active_session_and_user(self):
        issued = await self.service.signup("person@example.com", PASSWORD, "Person")
        self.repository.active_session.return_value = None
        with self.assertRaises(AuthRejected):
            await self.service.authenticate_access(issued.access_token)
        self.repository.active_session.return_value = {"revoked": False, "tenant_id": "tenant-a"}
        self.repository.find_user.return_value = None
        with self.assertRaises(AuthRejected):
            await self.service.authenticate_access(issued.access_token)

    async def test_refresh_replay_revokes_session_and_storage_failure_fails_closed(self):
        issued = await self.service.signup("person@example.com", PASSWORD, "Person")
        self.repository.rotate.return_value = None
        with self.assertLogs("src.services.auth_service", level="WARNING"):
            with self.assertRaises(AuthRejected):
                await self.service.refresh(issued.refresh_token)
        self.repository.revoke.assert_awaited_once()
        self.repository.active_session.side_effect = ConnectionFailure("private-db-uri")
        with self.assertLogs("src.services.auth_service", level="ERROR") as logs:
            with self.assertRaises(AuthUnavailable):
                await self.service.authenticate_access(issued.access_token)
        self.assertNotIn("private-db-uri", " ".join(logs.output))

    async def test_rate_limit_rejects_before_hashing_and_logout_is_idempotent(self):
        self.repository.rate_allowed.return_value = False
        with self.assertRaises(AuthRateLimited):
            await self.service.enforce_limit("client:test")
        await self.service.logout("not-a-token")
        self.repository.revoke.assert_not_awaited()

    async def test_http_validation_never_echoes_password_and_extra_tenant_is_rejected(self):
        application = FastAPI()
        application.include_router(router)
        application.add_exception_handler(AuthError, auth_error_handler)
        application.add_exception_handler(RequestValidationError, safe_auth_validation)
        application.state.auth_service = self.service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            invalid = await client.post("/auth/signup", json={"email": "invalid", "password": "private-password-value", "tenant_id": "victim"})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn("private-password-value", invalid.text)
            self.repository.create_user.assert_not_awaited()
            successful = await client.post("/auth/signup", json={"email": "person@example.com", "password": PASSWORD, "name": "Person"})
            self.assertEqual(successful.status_code, 201)
            self.assertEqual(successful.headers["cache-control"], "no-store")
            self.assertNotIn(PASSWORD, successful.text)
            self.repository.rate_allowed.return_value = False
            limited = await client.post("/auth/login", json={"email": "person@example.com", "password": PASSWORD})
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.headers["retry-after"], "60")
            application.state.auth_service = None
            disabled = await client.post("/auth/login", json={"email": "person@example.com", "password": PASSWORD})
            self.assertEqual(disabled.status_code, 404)

    async def test_local_application_lifespan_initializes_auth(self):
        with (
            patch("src.api.main.get_settings", return_value=self.configuration),
            patch("src.api.main.configure_logging"),
            patch("src.api.main.mongodb_database"), patch("src.api.main.minio_object_store"),
            patch("src.api.main.ensure_auth_indexes", new_callable=AsyncMock) as indexes,
        ):
            async with app.router.lifespan_context(app):
                self.assertIsInstance(app.state.auth_service, AuthService)
                indexes.assert_awaited_once()
        self.assertFalse(hasattr(app.state, "auth_service"))


if __name__ == "__main__":
    unittest.main()
