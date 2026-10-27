"""Tenant-scoped document persistence; no unscoped CRUD or physical deletion."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from src.core.tenancy import TenantContext
from src.domain.documents import Document, DocumentMetadata, DocumentStatus

logger = logging.getLogger(__name__)
_HIDDEN = [DocumentStatus.UPLOADING.value, DocumentStatus.DELETING.value, DocumentStatus.DELETED.value]
_TRANSITIONS = {
    DocumentStatus.UPLOADING: {DocumentStatus.PENDING, DocumentStatus.FAILED},
    DocumentStatus.PENDING: {DocumentStatus.PROCESSING, DocumentStatus.FAILED},
    DocumentStatus.PROCESSING: {DocumentStatus.READY, DocumentStatus.FAILED},
    DocumentStatus.FAILED: {DocumentStatus.PROCESSING},
    DocumentStatus.DELETING: {DocumentStatus.DELETED},
}


def _tenant_query(context: TenantContext) -> dict:
    """Require verified identity before constructing any filter."""
    if not isinstance(context, TenantContext):
        raise TypeError("A verified TenantContext is required")
    return {"tenant_id": context.tenant_id}


def _document_query(context: TenantContext, document_id: UUID) -> dict:
    """Reject missing/non-scalar IDs, including MongoDB operator dictionaries."""
    query = _tenant_query(context)
    if not isinstance(document_id, UUID):
        raise TypeError("document_id must be a UUID")
    return {**query, "document_id": document_id}


def _document(record: dict | None) -> Document | None:
    if record is None:
        return None
    return Document.model_validate({key: value for key, value in record.items() if key != "_id"})


class DocumentRepository:
    """Require trusted identity on every operation; document ACL checks are upstream.

    Records belong to a tenant, with uploader attribution. Membership alone does
    not grant document access. Missing and foreign-tenant IDs both return None.
    Mutations never upsert or accept arbitrary fields, filters, or update operators.
    """

    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database["documents"]

    async def create(
        self, context: TenantContext, metadata: DocumentMetadata, *,
        initial_status: DocumentStatus = DocumentStatus.PENDING,
    ) -> Document:
        """Create pending/uploading metadata with server-assigned ownership and identity."""
        _tenant_query(context)
        if type(metadata) is not DocumentMetadata:
            raise TypeError("Only descriptive DocumentMetadata may be supplied")
        if initial_status not in (DocumentStatus.PENDING, DocumentStatus.UPLOADING):
            raise ValueError("Documents must start pending or uploading")
        now = datetime.now(timezone.utc)
        document = Document(
            **metadata.model_dump(), document_id=uuid4(), tenant_id=context.tenant_id,
            uploaded_by=context.user_id, status=initial_status,
            created_at=now, updated_at=now,
        )
        await self._collection.insert_one(document.model_dump())
        logger.info("Document metadata created")
        return document

    async def get(self, context: TenantContext, document_id: UUID) -> Document | None:
        """Get visible metadata in this tenant; deletion tombstones stay hidden."""
        query = _document_query(context, document_id)
        query["status"] = {"$nin": _HIDDEN}
        return _document(await self._collection.find_one(query))

    async def list(
        self, context: TenantContext, *, limit: int = 50, owned_only: bool = False,
    ) -> list[Document]:
        """Return at most 100 visible records in stable newest-first order.

        This is a bounded initial listing, not a full pagination interface.
        """
        query = _tenant_query(context)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if type(owned_only) is not bool:
            raise TypeError("owned_only must be a boolean")
        if owned_only:
            query["uploaded_by"] = context.user_id
        query["status"] = {"$nin": _HIDDEN}
        cursor = self._collection.find(query).sort([("created_at", -1), ("document_id", -1)]).limit(limit)
        return [_document(record) async for record in cursor]

    async def transition_status(
        self, context: TenantContext, document_id: UUID, *,
        expected: DocumentStatus, target: DocumentStatus,
    ) -> Document | None:
        """Compare-and-set a legal lifecycle transition; stale updates return None.

        A worker cannot resurrect deleting/deleted metadata. Version activation
        and ingestion checkpoint handling are future service-layer responsibilities.
        """
        query = _document_query(context, document_id)
        if not isinstance(expected, DocumentStatus) or not isinstance(target, DocumentStatus):
            raise TypeError("Lifecycle values must be DocumentStatus members")
        if target not in _TRANSITIONS.get(expected, set()):
            raise ValueError("Unsupported document lifecycle transition")
        query["status"] = expected.value
        record = await self._collection.find_one_and_update(
            query, {"$set": {"status": target.value, "updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if record is not None:
            logger.info("Document lifecycle transitioned")
        return _document(record)

    async def soft_delete(self, context: TenantContext, document_id: UUID) -> Document | None:
        """Hide metadata immediately; future cleanup removes vectors/blobs separately."""
        query = _document_query(context, document_id)
        query["status"] = {"$nin": [DocumentStatus.DELETING.value, DocumentStatus.DELETED.value]}
        record = await self._collection.find_one_and_update(
            query, {"$set": {"status": DocumentStatus.DELETING.value, "updated_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if record is not None:
            logger.info("Document deletion requested")
        return _document(record)
