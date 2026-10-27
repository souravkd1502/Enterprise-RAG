"""Opt-in real MongoDB checks; only a generated disposable database is removed.

Set TEST_MONGODB_URI to the local Compose replica set; never use production.
Run with unittest discovery from tests/integration. No application .env is read.
"""

import os
import unittest
from uuid import uuid4

from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from src.core.tenancy import TenantContext
from src.domain.documents import DocumentMetadata, DocumentStatus
from src.infrastructure.mongodb.document_repository import DocumentRepository
from src.infrastructure.mongodb.indexes import ensure_document_indexes


@unittest.skipUnless(os.environ.get("TEST_MONGODB_URI"), "Set TEST_MONGODB_URI to run live MongoDB tests")
class MongoDBDocumentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncMongoClient(
            os.environ["TEST_MONGODB_URI"], uuidRepresentation="standard", tz_aware=True,
            serverSelectionTimeoutMS=5000, timeoutMS=5000,
        )
        self.addAsyncCleanup(self.client.close)
        await self.client.admin.command("ping")
        self.database_name = "rag_test_" + uuid4().hex
        self.database = self.client[self.database_name]
        self.addAsyncCleanup(self.client.drop_database, self.database_name)
        await ensure_document_indexes(self.database)
        self.repository = DocumentRepository(self.database)
        self.a = TenantContext("tenant-a", "user-a")
        self.b = TenantContext("tenant-b", "user-b")
        self.metadata = DocumentMetadata(filename="test.pdf", media_type="application/pdf", size_bytes=20)

    async def test_cross_tenant_read_update_and_delete_are_isolated(self):
        document = await self.repository.create(self.b, self.metadata)
        self.assertIsNone(await self.repository.get(self.a, document.document_id))
        self.assertEqual(await self.repository.list(self.a), [])
        self.assertIsNone(await self.repository.soft_delete(self.a, document.document_id))
        self.assertIsNone(await self.repository.transition_status(
            self.a, document.document_id, expected=DocumentStatus.PENDING, target=DocumentStatus.PROCESSING,
        ))
        owned = await self.repository.get(self.b, document.document_id)
        self.assertEqual(owned.status, DocumentStatus.PENDING)
        await self.repository.soft_delete(self.b, document.document_id)
        self.assertIsNone(await self.repository.get(self.b, document.document_id))
        self.assertEqual(await self.repository.list(self.b), [])
        self.assertIsNone(await self.repository.transition_status(
            self.b, document.document_id, expected=DocumentStatus.PENDING, target=DocumentStatus.PROCESSING,
        ))
        tombstone = await self.database.documents.find_one({"tenant_id": self.b.tenant_id, "document_id": document.document_id})
        self.assertEqual(tombstone["status"], "deleting")

    async def test_unique_identity_and_compare_and_set_lifecycle(self):
        document = await self.repository.create(self.a, self.metadata)
        with self.assertRaises(DuplicateKeyError):
            await self.database.documents.insert_one(document.model_dump())
        moved = await self.repository.transition_status(
            self.a, document.document_id, expected=DocumentStatus.PENDING, target=DocumentStatus.PROCESSING,
        )
        self.assertEqual(moved.status, DocumentStatus.PROCESSING)
        self.assertIsNone(await self.repository.transition_status(
            self.a, document.document_id, expected=DocumentStatus.PENDING, target=DocumentStatus.PROCESSING,
        ))

    async def test_replica_set_supports_transactions(self):
        async with self.client.start_session() as session:
            async with await session.start_transaction():
                await self.database.transaction_probe.insert_one({"tenant_id": self.a.tenant_id}, session=session)
        self.assertEqual(await self.database.transaction_probe.count_documents({"tenant_id": self.a.tenant_id}), 1)


if __name__ == "__main__":
    unittest.main()
