"""Upload validation, ownership, compensation, multipart limits, and object cleanup."""

import asyncio
import io
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from pymongo.errors import ConnectionFailure

from src.api.dependencies import get_document_service
from src.api.main import document_error_handler
from src.api.routes.documents import router
from src.core.exceptions import (
    DocumentError, DocumentNotFound, DocumentStorageError, InvalidDocument,
    UnsupportedDocument, UploadTooLarge,
)
from src.core.tenancy import TenantContext
from src.core.config import Settings
from src.domain.documents import Document, DocumentStatus
from src.infrastructure.minio.object_store import ObjectStore, object_key
from src.infrastructure.minio.client import minio_object_store
from src.services.document_service import DocumentService
from test_config import ENVIRONMENT

PDF = b"%PDF-1.7\n%%EOF\n"


class _UploadFixtures:
    def setUp(self):
        self.context = TenantContext("tenant-a", "user-a")
        now = datetime.now(timezone.utc)
        self.document = Document(
            filename="test.pdf", media_type="application/pdf", size_bytes=len(PDF),
            document_id=uuid4(), tenant_id="tenant-a", uploaded_by="user-a",
            status=DocumentStatus.UPLOADING, created_at=now, updated_at=now,
        )
        self.repository = MagicMock()
        self.repository.create = AsyncMock(return_value=self.document)
        self.repository.transition_status = AsyncMock(return_value=self.document.model_copy(update={"status": DocumentStatus.PENDING}))
        self.repository.get = AsyncMock(return_value=self.document.model_copy(update={"status": DocumentStatus.PENDING}))
        self.repository.list = AsyncMock(return_value=[])
        self.objects = MagicMock(spec=ObjectStore)
        self.service = DocumentService(self.repository, self.objects, max_bytes=32)

    async def upload(self, data=PDF, filename="test.pdf", media_type="application/pdf"):
        return await self.service.upload(self.context, io.BytesIO(data), filename=filename, media_type=media_type)


class UploadServiceTests(_UploadFixtures, unittest.IsolatedAsyncioTestCase):
    async def test_validation_precedes_any_persistence(self):
        for kwargs, error in (
            ({"filename": ""}, InvalidDocument),
            ({"filename": "secret.txt"}, UnsupportedDocument),
            ({"data": b"not a PDF"}, UnsupportedDocument),
            ({"data": b""}, UnsupportedDocument),
            ({"media_type": "text/plain"}, UnsupportedDocument),
            ({"data": PDF * 4}, UploadTooLarge),
        ):
            with self.subTest(fields=tuple(kwargs)), self.assertRaises(error):
                await self.upload(**kwargs)
        self.repository.create.assert_not_awaited()
        self.objects.upload.assert_not_awaited()

    async def test_success_sanitizes_name_and_finalizes_only_after_upload(self):
        document = await self.upload(filename="C:\\private\\test.pdf")
        self.assertEqual(document.status, DocumentStatus.PENDING)
        metadata = self.repository.create.await_args.args[1]
        self.assertEqual(metadata.filename, "test.pdf")
        self.assertEqual(self.repository.create.await_args.kwargs["initial_status"], DocumentStatus.UPLOADING)
        self.objects.upload.assert_awaited_once()
        self.assertEqual(self.repository.transition_status.await_args.kwargs["target"], DocumentStatus.PENDING)

    async def test_failed_upload_claims_failure_before_removing_object(self):
        self.objects.upload.side_effect = OSError("private-server-details")
        self.repository.transition_status.return_value = self.document.model_copy(update={"status": DocumentStatus.FAILED})
        with self.assertLogs("src.services.document_service", level="ERROR") as logs:
            with self.assertRaises(DocumentStorageError):
                await self.upload()
        self.assertEqual(self.repository.transition_status.await_args.kwargs["target"], DocumentStatus.FAILED)
        self.objects.remove.assert_awaited_once_with(self.context, self.document.document_id)
        self.assertNotIn("private-server-details", " ".join(logs.output))

    async def test_ambiguous_finalize_never_removes_a_possibly_committed_object(self):
        self.repository.transition_status.side_effect = [ConnectionFailure("ambiguous write"), None]
        with self.assertLogs("src.services.document_service", level="WARNING"):
            with self.assertRaises(DocumentStorageError):
                await self.upload()
        self.objects.remove.assert_not_awaited()

    async def test_cleanup_failure_is_logged_without_masking_service_error(self):
        self.objects.upload.side_effect = OSError("upload failed")
        self.objects.remove.side_effect = OSError("private-cleanup-error")
        with self.assertLogs("src.services.document_service", level="ERROR") as logs:
            with self.assertRaises(DocumentStorageError):
                await self.upload()
        self.assertIn("Upload recovery required", " ".join(logs.output))
        self.assertNotIn("private-cleanup-error", " ".join(logs.output))

    async def test_cancellation_runs_compensation_and_preserves_cancellation(self):
        self.objects.upload.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.upload()
        self.objects.remove.assert_awaited_once()

    async def test_metadata_intent_failure_does_not_write_bytes(self):
        self.repository.create.side_effect = ConnectionFailure("private-uri")
        with self.assertLogs("src.services.document_service", level="ERROR"):
            with self.assertRaises(DocumentStorageError):
                await self.upload()
        self.objects.upload.assert_not_awaited()

    async def test_other_user_cannot_read_and_listing_filters_before_limit(self):
        with self.assertRaises(DocumentNotFound):
            await self.service.get(TenantContext("tenant-a", "other-user"), self.document.document_id)
        await self.service.list(self.context, limit=5)
        self.repository.list.assert_awaited_once_with(self.context, limit=5, owned_only=True)


class ObjectStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_namespace_does_not_accept_raw_paths_or_cross_tenant_keys(self):
        document_id = uuid4()
        a = object_key(TenantContext("tenant/a", "user"), document_id)
        b = object_key(TenantContext("tenant/b", "user"), document_id)
        self.assertNotEqual(a, b)
        self.assertNotIn("tenant/a", a)
        with self.assertRaises(TypeError):
            object_key(None, document_id)
        with self.assertRaises(TypeError):
            object_key(TenantContext("tenant", "user"), "../../raw-key")

    async def test_download_releases_response_when_destination_fails(self):
        client = MagicMock()
        response = client.get_object.return_value
        response.stream.return_value = [PDF]
        destination = MagicMock()
        destination.write.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            await ObjectStore(client, "documents").download_to(TenantContext("tenant", "user"), uuid4(), destination)
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


class UploadRouteTests(_UploadFixtures, unittest.IsolatedAsyncioTestCase):
    def test_openapi_exposes_the_multipart_file_contract(self):
        application = FastAPI()
        application.include_router(router)
        schema = application.openapi()["paths"]["/documents"]["post"]["requestBody"]
        self.assertEqual(schema["content"]["multipart/form-data"]["schema"]["required"], ["file"])

    async def request(self, method="POST", path="/documents", **kwargs):
        application = FastAPI()
        application.include_router(router)
        application.add_exception_handler(DocumentError, document_error_handler)
        application.state.token_verifier = MagicMock()
        application.state.token_verifier.verify.return_value = self.context
        application.state.access_service = AsyncMock()
        application.dependency_overrides[get_document_service] = lambda: self.service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    async def test_http_upload_returns_public_metadata_only(self):
        response = await self.request(headers={"Authorization": "Bearer test"}, files={"file": ("test.pdf", PDF, "application/pdf")})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "pending")
        for private in ("tenant_id", "uploaded_by", "object_key"):
            self.assertNotIn(private, response.json())

    async def test_authentication_runs_before_consuming_multipart_body(self):
        async def unread_body():
            self.fail("Unauthenticated body was consumed")
            yield b"unreachable"
        response = await self.request(content=unread_body(), headers={"Content-Type": "multipart/form-data; boundary=test"})
        self.assertEqual(response.status_code, 401)

    async def test_http_invalid_type_oversize_and_extra_fields(self):
        headers = {"Authorization": "Bearer test"}
        wrong = await self.request(headers=headers, files={"file": ("test.pdf", b"invalid", "application/pdf")})
        self.assertEqual(wrong.status_code, 415)
        oversized = await self.request(headers=headers, files={"file": ("test.pdf", PDF * 4, "application/pdf")})
        self.assertEqual(oversized.status_code, 413)
        extra = await self.request(headers=headers, files={"file": ("test.pdf", PDF, "application/pdf")}, data={"tenant_id": "spoofed"})
        self.assertEqual(extra.status_code, 400)

    async def test_chunked_request_is_bounded_without_content_length(self):
        async def body():
            yield b"x" * (self.service.max_bytes + 65537)
        response = await self.request(
            content=body(), headers={"Authorization": "Bearer test", "Content-Type": "multipart/form-data; boundary=test"},
        )
        self.assertEqual(response.status_code, 413)
        self.repository.create.assert_not_awaited()


class MinioLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_bucket_initialization_and_pool_cleanup(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            settings = Settings(_env_file=None)
        with patch("src.infrastructure.minio.client.PoolManager") as pool, patch("src.infrastructure.minio.client.Minio") as factory:
            factory.return_value.bucket_exists.return_value = False
            async with minio_object_store(settings) as objects:
                self.assertIsInstance(objects, ObjectStore)
            factory.return_value.make_bucket.assert_called_once_with(settings.minio_bucket)
            pool.return_value.clear.assert_called_once()

    async def test_startup_failure_is_safe_and_closes_pool(self):
        with patch.dict(os.environ, ENVIRONMENT, clear=True):
            settings = Settings(_env_file=None)
        with patch("src.infrastructure.minio.client.PoolManager") as pool, patch("src.infrastructure.minio.client.Minio") as factory:
            factory.return_value.bucket_exists.side_effect = OSError("private-endpoint")
            with self.assertLogs("src.infrastructure.minio.client", level="ERROR") as logs:
                with self.assertRaisesRegex(RuntimeError, "^MinIO initialization failed$"):
                    async with minio_object_store(settings):
                        self.fail("Unavailable MinIO accepted")
            self.assertNotIn("private-endpoint", " ".join(logs.output))
            pool.return_value.clear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
