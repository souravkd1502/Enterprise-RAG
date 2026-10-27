"""Real HTTP/JWT/MinIO/MongoDB uploads with disposable test storage.

Requires TEST_MONGODB_URI, TEST_MINIO_ENDPOINT, TEST_MINIO_ACCESS_KEY, and
TEST_MINIO_SECRET_KEY. The MinIO endpoint is HTTP for local Compose only.
"""

import io
import os
import time
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import jwt
from anyio import to_thread
from cryptography.hazmat.primitives.asymmetric import rsa
from minio import Minio
from minio.error import S3Error
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure

from src.api.main import app
from src.core.config import Settings, get_settings
from src.core.tenancy import TenantContext
from src.infrastructure.minio.object_store import object_key

PDF = b"%PDF-1.7\n%%EOF\n"
REQUIRED = ("TEST_MONGODB_URI", "TEST_MINIO_ENDPOINT", "TEST_MINIO_ACCESS_KEY", "TEST_MINIO_SECRET_KEY")


@unittest.skipUnless(all(os.environ.get(name) for name in REQUIRED), "Set local MongoDB and MinIO test connection variables")
class DocumentUploadIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(cls.private_key.public_key(), as_dict=True)
        cls.jwk.update(kid="upload-test-key", use="sig", alg="RS256")

    async def asyncSetUp(self):
        self.database_name = "rag_test_" + uuid4().hex
        self.bucket = "rag-test-" + uuid4().hex
        self.settings = Settings(
            _env_file=None,
            jwt_issuer="https://identity.example.com/", jwt_audience="upload-tests",
            jwt_jwks_url="https://identity.example.com/keys",
            mongodb_uri=os.environ["TEST_MONGODB_URI"], mongodb_database=self.database_name,
            minio_endpoint=os.environ["TEST_MINIO_ENDPOINT"], minio_secure=False,
            minio_access_key=os.environ["TEST_MINIO_ACCESS_KEY"],
            minio_secret_key=os.environ["TEST_MINIO_SECRET_KEY"], minio_bucket=self.bucket,
            chroma_host="localhost", redis_url="redis://localhost:6379/0",
            rabbitmq_url="amqp://localhost:5672/", llm_provider="local", llm_model="unused",
            embedding_provider="local", embedding_model="unused", upload_max_bytes=1024,
        )
        self.mongo = AsyncMongoClient(os.environ["TEST_MONGODB_URI"], uuidRepresentation="standard", tz_aware=True, timeoutMS=5000)
        self.addAsyncCleanup(self.mongo.close)
        self.addAsyncCleanup(self.mongo.drop_database, self.database_name)
        self.minio = Minio(
            os.environ["TEST_MINIO_ENDPOINT"], secure=False,
            access_key=os.environ["TEST_MINIO_ACCESS_KEY"], secret_key=os.environ["TEST_MINIO_SECRET_KEY"],
        )
        self.addAsyncCleanup(to_thread.run_sync, self.cleanup_bucket)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.configuration = patch("src.api.main.get_settings", return_value=self.settings)
        self.configuration.start()
        self.addCleanup(self.configuration.stop)
        logs = patch("src.api.main.configure_logging")
        logs.start()
        self.addCleanup(logs.stop)
        self.lifespan = app.router.lifespan_context(app)
        await self.lifespan.__aenter__()
        self.addAsyncCleanup(self.lifespan.__aexit__, None, None, None)
        for tenant_id in ("tenant-a", "tenant-b"):
            await self.mongo[self.database_name].tenants.insert_one({"tenant_id": tenant_id, "status": "active"})
        for tenant_id, user_id in (("tenant-a", "user-a"), ("tenant-a", "other-user"), ("tenant-b", "user-a")):
            await self.mongo[self.database_name].memberships.insert_one({
                "tenant_id": tenant_id, "user_id": user_id, "role": "MEMBER", "status": "active",
            })
        jwks = patch.object(app.state.token_verifier._jwks, "fetch_data", return_value={"keys": [self.jwk]})
        jwks.start()
        self.addCleanup(jwks.stop)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.http.aclose)

    def cleanup_bucket(self):
        if self.minio.bucket_exists(self.bucket):
            for item in self.minio.list_objects(self.bucket, recursive=True):
                self.minio.remove_object(self.bucket, item.object_name)
            self.minio.remove_bucket(self.bucket)

    def headers(self, tenant="tenant-a", user="user-a"):
        token = jwt.encode({
            "iss": self.settings.jwt_issuer, "aud": self.settings.jwt_audience,
            "exp": int(time.time()) + 300, "tenant_id": tenant, "user_id": user,
        }, self.private_key, algorithm="RS256", headers={"kid": "upload-test-key"})
        return {"Authorization": "Bearer " + token}

    async def upload(self):
        return await self.http.post("/documents", headers=self.headers(), files={"file": ("test.pdf", PDF, "application/pdf")})

    async def test_upload_persists_bytes_and_enforces_tenant_and_user_boundaries(self):
        response = await self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        document_id = UUID(response.json()["document_id"])
        self.assertEqual(response.json()["status"], "pending")
        row = await self.mongo[self.database_name].documents.find_one({"document_id": document_id})
        self.assertEqual((row["tenant_id"], row["uploaded_by"]), ("tenant-a", "user-a"))
        destination = io.BytesIO()
        await app.state.document_service._objects.download_to(TenantContext("tenant-a", "user-a"), document_id, destination)
        self.assertEqual(destination.getvalue(), PDF)
        path = "/documents/" + str(document_id)
        self.assertEqual((await self.http.get(path, headers=self.headers())).status_code, 200)
        for tenant, user in (("tenant-b", "user-a"), ("tenant-a", "other-user")):
            denied = await self.http.get(path, headers=self.headers(tenant, user))
            self.assertEqual(denied.status_code, 404)
            listing = await self.http.get("/documents", headers=self.headers(tenant, user))
            self.assertEqual(listing.json(), [])
        own = await self.http.get("/documents", headers=self.headers())
        self.assertEqual(len(own.json()), 1)
        no_membership = await self.http.get("/documents", headers=self.headers("tenant-a", "unprovisioned-user"))
        self.assertEqual(no_membership.status_code, 403)
        # Even the same document UUID maps to a different tenant's blob namespace.
        with self.assertRaises(S3Error) as missing:
            await to_thread.run_sync(self.minio.stat_object, self.bucket, object_key(TenantContext("tenant-b", "user-a"), document_id))
        self.assertEqual(missing.exception.code, "NoSuchKey")

    async def test_failed_finalize_cleans_real_object_and_retains_failed_intent(self):
        repository = app.state.document_service._repository
        original = repository.transition_status

        async def fail_once(context, document_id, *, expected, target):
            if target.value == "pending":
                raise ConnectionFailure("simulated finalize failure")
            return await original(context, document_id, expected=expected, target=target)

        with patch.object(repository, "transition_status", side_effect=fail_once):
            with self.assertLogs("src.services.document_service", level="ERROR"):
                response = await self.upload()
        self.assertEqual(response.status_code, 503)
        row = await self.mongo[self.database_name].documents.find_one({"tenant_id": "tenant-a"})
        self.assertEqual(row["status"], "failed")
        objects = await to_thread.run_sync(lambda: list(self.minio.list_objects(self.bucket, recursive=True)))
        self.assertEqual(objects, [])


if __name__ == "__main__":
    unittest.main()
