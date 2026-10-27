"""Repository boundary and lifecycle checks; live isolation is tested separately."""

import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from pydantic import ValidationError

from src.core.tenancy import TenantContext
from src.domain.documents import DocumentMetadata, DocumentStatus
from src.infrastructure.mongodb.document_repository import DocumentRepository


class DocumentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.collection = MagicMock()
        self.collection.insert_one = AsyncMock()
        self.collection.find_one = AsyncMock(return_value=None)
        self.collection.find_one_and_update = AsyncMock(return_value=None)
        database = MagicMock()
        database.__getitem__.return_value = self.collection
        self.repository = DocumentRepository(database)
        self.context = TenantContext("tenant-a", "user-a")
        self.metadata = DocumentMetadata(filename="private.pdf", media_type="application/pdf", size_bytes=42)

    async def test_create_assigns_identity_and_rejects_supplied_ownership(self):
        document = await self.repository.create(self.context, self.metadata)
        stored = self.collection.insert_one.await_args.args[0]
        self.assertEqual(stored["tenant_id"], "tenant-a")
        self.assertEqual(stored["uploaded_by"], "user-a")
        self.assertEqual(document.status, DocumentStatus.PENDING)
        self.assertIsNotNone(document.created_at.tzinfo)
        with self.assertRaises(ValidationError):
            DocumentMetadata(**self.metadata.model_dump(), tenant_id="tenant-b")
        with self.assertRaises(TypeError):
            await self.repository.create(self.context, document)

    async def test_every_lookup_and_mutation_is_tenant_scoped(self):
        document_id = uuid4()
        await self.repository.get(self.context, document_id)
        lookup = self.collection.find_one.await_args.args[0]
        self.assertEqual(lookup["tenant_id"], "tenant-a")
        self.assertEqual(lookup["document_id"], document_id)
        self.assertIn("deleting", lookup["status"]["$nin"])
        await self.repository.soft_delete(self.context, document_id)
        deletion = self.collection.find_one_and_update.await_args.args
        self.assertEqual(deletion[0]["tenant_id"], "tenant-a")
        self.assertEqual(deletion[0]["document_id"], document_id)
        self.assertEqual(deletion[1]["$set"]["status"], "deleting")
        await self.repository.transition_status(
            self.context, document_id, expected=DocumentStatus.PENDING, target=DocumentStatus.PROCESSING,
        )
        transition = self.collection.find_one_and_update.await_args.args[0]
        self.assertEqual(transition, {"tenant_id": "tenant-a", "document_id": document_id, "status": "pending"})
        self.assertNotIn("upsert", self.collection.find_one_and_update.await_args.kwargs)

    async def test_missing_context_or_operator_identifiers_never_reach_database(self):
        for invalid in (None, {"$ne": None}, str(uuid4())):
            with self.subTest(identifier=invalid):
                with self.assertRaises(TypeError):
                    await self.repository.get(self.context, invalid)
                with self.assertRaises(TypeError):
                    await self.repository.soft_delete(self.context, invalid)
        with self.assertRaises(TypeError):
            await self.repository.create(None, self.metadata)
        with self.assertRaises(TypeError):
            await self.repository.list(None)
        self.collection.find_one.assert_not_called()
        self.collection.find_one_and_update.assert_not_called()
        self.collection.insert_one.assert_not_called()

    async def test_deletion_cannot_be_resurrected(self):
        for status in (DocumentStatus.DELETING, DocumentStatus.DELETED):
            with self.assertRaises(ValueError):
                await self.repository.transition_status(
                    self.context, uuid4(), expected=status, target=DocumentStatus.PROCESSING,
                )
        self.collection.find_one_and_update.assert_not_called()

    async def test_listing_is_scoped_bounded_and_hides_deletion(self):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.__aiter__.return_value = []
        self.collection.find.return_value = cursor
        self.assertEqual(await self.repository.list(self.context, limit=10), [])
        query = self.collection.find.call_args.args[0]
        self.assertEqual(query["tenant_id"], "tenant-a")
        self.assertEqual(set(query["status"]["$nin"]), {"uploading", "deleting", "deleted"})
        cursor.limit.assert_called_once_with(10)
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                await self.repository.list(self.context, limit=limit)


if __name__ == "__main__":
    unittest.main()
