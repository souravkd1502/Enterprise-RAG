"""Local authentication with real MongoDB, asymmetric JWTs, and Argon2id.

Set TEST_MONGODB_URI to the local replica set. Each test deletes only its own
generated rag_test_<uuid> database; private signing keys live in a temporary dir.
"""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from uuid import uuid4
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from pymongo import AsyncMongoClient

from src.api.dependencies import get_tenant_context
from src.api.main import auth_error_handler, safe_auth_validation
from src.api.routes.auth import router
from src.api.routes.tenants import router as tenants_router
from src.core.config import Settings
from src.core.exceptions import AuthError, AuthUnavailable
from src.core.security import LocalTokenCodec
from src.core.tenancy import TenantContext
from src.infrastructure.mongodb.auth_repository import AuthRepository
from src.infrastructure.mongodb.indexes import ensure_auth_indexes
from src.services.auth_service import AuthService
from src.services.tenant_service import TenantService

PASSWORD = "correct horse battery staple"


@unittest.skipUnless(os.environ.get("TEST_MONGODB_URI"), "Set TEST_MONGODB_URI for real authentication tests")
class LocalAuthIntegrationTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncSetUp(self):
        self.mongo = AsyncMongoClient(os.environ["TEST_MONGODB_URI"], tz_aware=True, timeoutMS=5000)
        self.addAsyncCleanup(self.mongo.close)
        name = "rag_test_" + uuid4().hex
        self.database = self.mongo[name]
        self.addAsyncCleanup(self.mongo.drop_database, name)
        await ensure_auth_indexes(self.database)
        self.settings = Settings(
            _env_file=None, auth_mode="local", auth_private_key_path=self.key_path,
            auth_invitation_development_links=True,
            jwt_issuer="https://local.example.com/", jwt_audience="local-auth-test",
            mongodb_uri=os.environ["TEST_MONGODB_URI"], minio_endpoint="localhost:9000",
            minio_access_key="unused", minio_secret_key="unused", chroma_host="localhost",
            redis_url="redis://localhost:6379/0", rabbitmq_url="amqp://localhost:5672/",
            llm_provider="local", llm_model="unused", embedding_provider="local", embedding_model="unused",
        )
        self.repository = AuthRepository(self.database)
        codec = LocalTokenCodec(self.settings)
        service = AuthService(self.repository, codec, self.settings)
        await service.initialize()
        application = FastAPI()
        application.include_router(router)
        application.include_router(tenants_router)
        application.state.tenant_service = TenantService(self.repository.tenants, self.settings)
        application.state.auth_service = service
        application.state.token_verifier = codec
        application.add_exception_handler(AuthError, auth_error_handler)
        application.add_exception_handler(RequestValidationError, safe_auth_validation)

        @application.get("/protected")
        async def protected(context: Annotated[TenantContext, Depends(get_tenant_context)]):
            return {"tenant_id": context.tenant_id, "user_id": context.user_id}

        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")
        self.addAsyncCleanup(self.http.aclose)

    async def signup(self, email="person@example.com"):
        response = await self.http.post("/auth/signup", json={"email": email, "password": PASSWORD, "name": "Test user", "workspace_name": "Test workspace"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def access(self, tokens):
        return await self.http.get("/protected", headers={"Authorization": "Bearer " + tokens["access_token"]})

    async def test_signup_login_refresh_logout_and_tenant_assignment(self):
        first = await self.signup()
        second = await self.signup("other@example.com")
        self.assertNotEqual(first["tenant_id"], second["tenant_id"])
        response = await self.access(first)
        self.assertEqual(response.json(), {"tenant_id": first["tenant_id"], "user_id": first["user_id"]})
        login = await self.http.post("/auth/login", json={"email": "PERSON@example.com", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["tenant_id"], first["tenant_id"])
        rotated = await self.http.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
        self.assertEqual(rotated.status_code, 200)
        self.assertNotEqual(rotated.json()["refresh_token"], first["refresh_token"])
        logged_out = await self.http.post("/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]})
        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual((await self.access(first)).status_code, 401)
        self.assertEqual((await self.access(rotated.json())).status_code, 401)
        self.assertEqual((await self.access(login.json())).status_code, 200)  # independent login session
        self.assertEqual((await self.access(second)).status_code, 200)
        again = await self.http.post("/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]})
        self.assertEqual(again.status_code, 204)
        stored = await self.database.auth_users.find_one({"email": "person@example.com"})
        self.assertTrue(stored["password_hash"].startswith("$argon2id$"))
        self.assertNotIn(PASSWORD, str(stored))
        for session in await self.database.auth_sessions.find({}).to_list():
            self.assertNotIn("refresh_token", session)
            self.assertEqual(len(session["refresh_hash"]), 64)

    async def test_refresh_reuse_revokes_entire_session(self):
        tokens = await self.signup()
        rotated = await self.http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(rotated.status_code, 200)
        with self.assertLogs("src.services.auth_service", level="WARNING"):
            reused = await self.http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(reused.status_code, 401)
        self.assertEqual((await self.access(rotated.json())).status_code, 401)
        rejected = await self.http.post("/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
        self.assertEqual(rejected.status_code, 401)

    async def test_concurrent_refresh_has_one_winner_and_replay_revokes_it(self):
        tokens = await self.signup()
        with self.assertLogs("src.services.auth_service", level="WARNING"):
            responses = await asyncio.gather(*(
                self.http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}) for _ in range(2)
            ))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401])
        winner = next(response.json() for response in responses if response.status_code == 200)
        self.assertEqual((await self.access(winner)).status_code, 401)

    async def test_duplicate_email_invalid_credentials_and_injection_rejected(self):
        await self.signup()
        duplicate = await self.http.post("/auth/signup", json={"email": "PERSON@example.com", "password": PASSWORD, "name": "Test user"})
        self.assertEqual(duplicate.status_code, 409)
        wrong = await self.http.post("/auth/login", json={"email": "person@example.com", "password": "incorrect password string"})
        absent = await self.http.post("/auth/login", json={"email": "absent@example.com", "password": "incorrect password string"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json(), absent.json())
        injected = await self.http.post("/auth/signup", json={"email": "third@example.com", "password": PASSWORD, "tenant_id": "victim"})
        self.assertEqual(injected.status_code, 422)
        self.assertNotIn(PASSWORD, injected.text)

    async def test_disabled_users_and_expired_sessions_fail_closed_without_waiting_for_ttl(self):
        tokens = await self.signup()
        await self.database.auth_users.update_one({"email": "person@example.com"}, {"$set": {"active": False}})
        self.assertEqual((await self.access(tokens)).status_code, 401)
        refreshed = await self.http.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        self.assertEqual(refreshed.status_code, 401)
        await self.database.auth_users.update_one({"email": "person@example.com"}, {"$set": {"active": True}})
        await self.database.auth_sessions.update_many({}, {"$set": {"expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc)}})
        self.assertEqual((await self.access(tokens)).status_code, 401)

    async def test_rate_counter_is_atomic_under_concurrency(self):
        # Keep the fixed window stable even if this test starts at a minute boundary.
        with patch("src.infrastructure.mongodb.auth_repository.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime.now(timezone.utc)
            results = await asyncio.gather(*(self.repository.rate_allowed("client:concurrent-test", 3) for _ in range(10)))
        self.assertEqual(sum(results), 3)

    def headers(self, tokens):
        return {"Authorization": "Bearer " + tokens["access_token"]}

    async def account(self, email):
        response = await self.http.post("/auth/signup", json={
            "email": email, "password": PASSWORD, "name": "Test account",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsNone(response.json()["tenant_id"])
        return response.json()

    async def invite(self, owner, email, role="MEMBER"):
        response = await self.http.post("/tenants/" + owner["tenant_id"] + "/invitations",
            headers=self.headers(owner), json={"email": email, "role": role})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    async def test_account_onboarding_and_same_workspace_names(self):
        tokens = await self.account("new@example.com")
        self.assertEqual((await self.access(tokens)).status_code, 403)
        workspaces = []
        for _ in range(2):
            response = await self.http.post("/tenants", headers=self.headers(tokens), json={"name": "Shared label"})
            self.assertEqual(response.status_code, 201, response.text)
            workspaces.append(response.json())
        self.assertNotEqual(workspaces[0]["tenant_id"], workspaces[1]["tenant_id"])
        for workspace in workspaces:
            membership = await self.database.memberships.find_one({
                "tenant_id": workspace["tenant_id"], "user_id": tokens["user_id"],
            })
            self.assertEqual(membership["role"], "OWNER")
        profile = await self.http.get("/auth/me", headers=self.headers(tokens))
        self.assertEqual(len(profile.json()["workspaces"]), 2)
        login = await self.http.post("/auth/login", json={"email": "new@example.com", "password": PASSWORD})
        self.assertTrue(login.json()["tenant_selection_required"])
        selected = await self.http.post("/auth/select-tenant", json={
            "refresh_token": login.json()["refresh_token"], "tenant_id": workspaces[0]["tenant_id"],
        })
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual((await self.access(selected.json())).status_code, 200)
        self.assertEqual((await self.http.get("/auth/me", headers=self.headers(login.json()))).status_code, 401)
        switched = await self.http.post("/auth/select-tenant", json={
            "refresh_token": selected.json()["refresh_token"], "tenant_id": workspaces[1]["tenant_id"],
        })
        self.assertEqual(switched.status_code, 200)
        self.assertEqual((await self.access(selected.json())).status_code, 401)

    async def test_invitation_email_role_single_use_and_persisted_hash(self):
        owner = await self.signup()
        recipient = await self.account("member@example.com")
        wrong = await self.account("wrong@example.com")
        invitation = await self.invite(owner, "MEMBER@example.com")
        stored = await self.database.invitations.find_one({"invitation_id": invitation["invitation_id"]})
        self.assertNotIn(invitation["invitation_token"], str(stored))
        self.assertEqual(len(stored["token_hash"]), 64)
        body = {"token": invitation["invitation_token"]}
        path = "/tenants/invitations/accept"
        denied = await self.http.post(path, headers=self.headers(wrong), json=body)
        self.assertEqual(denied.status_code, 400)
        accepted = await self.http.post(path, headers=self.headers(recipient), json=body)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["role"], "MEMBER")
        self.assertEqual((await self.http.post(path, headers=self.headers(recipient), json=body)).status_code, 400)
        selected = await self.http.post("/auth/select-tenant", json={
            "refresh_token": recipient["refresh_token"], "tenant_id": owner["tenant_id"],
        })
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["user_id"], recipient["user_id"])
        self.assertEqual((await self.access(selected.json())).status_code, 200)
        forbidden = await self.http.post("/tenants/" + owner["tenant_id"] + "/invitations",
            headers=self.headers(selected.json()), json={"email": "other@example.com", "role": "OWNER"})
        self.assertEqual(forbidden.status_code, 403)
        members = await self.http.get("/tenants/" + owner["tenant_id"] + "/members", headers=self.headers(owner))
        self.assertEqual(len(members.json()), 2)
        forbidden = await self.http.get("/tenants/" + owner["tenant_id"] + "/members", headers=self.headers(selected.json()))
        self.assertEqual(forbidden.status_code, 403)
        await self.database.memberships.update_one({
            "tenant_id": owner["tenant_id"], "user_id": recipient["user_id"],
        }, {"$set": {"status": "inactive"}})
        self.assertEqual((await self.access(selected.json())).status_code, 403)
        audit = await self.database.audit_events.find({"tenant_id": owner["tenant_id"]}).to_list()
        self.assertTrue({"tenant.created", "invitation.created", "invitation.accepted"}.issubset({e["action"] for e in audit}))

    async def test_expired_invitation_and_tenant_membership_cannot_be_bypassed(self):
        owner = await self.signup()
        recipient = await self.account("member@example.com")
        forbidden = await self.http.post("/auth/login", json={
            "email": "member@example.com", "password": PASSWORD, "tenant_id": owner["tenant_id"],
        })
        self.assertEqual(forbidden.status_code, 403)
        invitation = await self.invite(owner, "member@example.com")
        await self.database.invitations.update_one({"invitation_id": invitation["invitation_id"]},
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        response = await self.http.post("/tenants/invitations/accept",
            headers=self.headers(recipient), json={"token": invitation["invitation_token"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(await self.database.memberships.count_documents({"user_id": recipient["user_id"]}), 0)
        await self.database.tenants.update_one({"tenant_id": owner["tenant_id"]}, {"$set": {"status": "inactive"}})
        self.assertEqual((await self.access(owner)).status_code, 403)

    async def test_workspace_creation_rolls_back_when_owner_insert_fails(self):
        user = await self.account("new@example.com")
        with patch.object(self.repository.tenants.memberships, "insert_one", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                await self.repository.tenants.create_workspace(user["user_id"], "Rollback")
        self.assertEqual(await self.database.tenants.count_documents({}), 0)
        self.assertEqual(await self.database.memberships.count_documents({}), 0)

    async def test_acceptance_failure_rolls_back_consumption_and_membership(self):
        owner = await self.signup()
        recipient = await self.account("member@example.com")
        invitation = await self.invite(owner, "member@example.com")
        user = await self.repository.find_user(recipient["user_id"])
        with patch.object(self.repository.tenants.memberships, "update_one", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                await self.repository.tenants.accept(user, sha256(invitation["invitation_token"].encode()).hexdigest())
        stored = await self.database.invitations.find_one({"invitation_id": invitation["invitation_id"]})
        self.assertIsNone(stored["accepted_at"])
        self.assertEqual(await self.database.memberships.count_documents({"user_id": recipient["user_id"]}), 0)

    async def test_active_role_is_preserved_and_disabled_delivery_does_not_persist(self):
        owner = await self.signup()
        invitation = await self.invite(owner, "person@example.com", role="MEMBER")
        response = await self.http.post("/tenants/invitations/accept",
            headers=self.headers(owner), json={"token": invitation["invitation_token"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "OWNER")
        service = TenantService(self.repository.tenants,
            self.settings.model_copy(update={"auth_invitation_development_links": False}))
        with self.assertRaises(AuthUnavailable):
            await service.invite({"user_id": owner["user_id"]}, owner["tenant_id"], "other@example.com", "MEMBER")
        self.assertEqual(await self.database.invitations.count_documents({}), 1)

    async def test_concurrent_invitation_acceptance_has_one_winner(self):
        owner = await self.signup()
        recipient = await self.account("member@example.com")
        invitation = await self.invite(owner, "member@example.com")
        responses = await asyncio.gather(*(self.http.post("/tenants/invitations/accept",
            headers=self.headers(recipient), json={"token": invitation["invitation_token"]}) for _ in range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 400])
        self.assertEqual(await self.database.memberships.count_documents({"user_id": recipient["user_id"]}), 1)

    async def test_legacy_accounts_migrate_idempotently_without_changing_tenant_ids(self):
        await self.database.auth_users.insert_one({
            "user_id": uuid4().hex, "tenant_id": uuid4().hex,
            "email": "legacy@example.com", "password_hash": "unused",
            "active": True, "created_at": datetime.now(timezone.utc),
        })
        self.assertEqual(await self.repository.migrate_legacy_users(), 1)
        self.assertEqual(await self.repository.migrate_legacy_users(), 0)
        user = await self.database.auth_users.find_one({"email": "legacy@example.com"})
        membership = await self.repository.tenants.membership(user["user_id"], user["tenant_id"])
        self.assertEqual(membership["role"], "OWNER")
        self.assertEqual(user["auth_provider"], "local")


if __name__ == "__main__":
    unittest.main()
