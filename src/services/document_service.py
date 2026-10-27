"""PDF upload coordination, uploader-only access, and safe compensation."""

import logging
from typing import BinaryIO
from uuid import UUID

from anyio import CancelScope, to_thread
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from src.core.exceptions import (
    DocumentNotFound, DocumentStorageError, InvalidDocument,
    UnsupportedDocument, UploadTooLarge,
)
from src.core.tenancy import TenantContext
from src.domain.documents import Document, DocumentMetadata, DocumentStatus
from src.infrastructure.minio.object_store import ObjectStore
from src.infrastructure.mongodb.document_repository import DocumentRepository

logger = logging.getLogger(__name__)


def _inspect_pdf(stream: BinaryIO, filename: str, media_type: str, limit: int) -> DocumentMetadata:
    """Check actual spooled length and PDF signature; leave the stream rewound.

    This is a format gate, not full PDF validation or malware detection. Docling
    will parse content in the later ingestion pipeline.
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 255 or any(not char.isprintable() for char in name):
        raise InvalidDocument()
    if not name.lower().endswith(".pdf") or media_type.lower() not in (
        "application/pdf", "application/octet-stream",
    ):
        raise UnsupportedDocument()
    size = stream.seek(0, 2)
    stream.seek(0)
    if size > limit:
        raise UploadTooLarge()
    if not size or stream.read(5) != b"%PDF-":
        raise UnsupportedDocument()
    stream.seek(0)
    try:
        return DocumentMetadata(filename=name, media_type="application/pdf", size_bytes=size)
    except ValidationError:
        raise InvalidDocument() from None


class DocumentService:
    """Apply ownership rules and coordinate two stores without claiming atomicity.

    Only an uploader in the verified tenant may inspect/list their documents until
    document ACLs are available. Uploading intents remain hidden from normal reads.
    """

    def __init__(self, repository: DocumentRepository, objects: ObjectStore, max_bytes: int) -> None:
        self._repository = repository
        self._objects = objects
        self.max_bytes = max_bytes

    async def upload(
        self, context: TenantContext, stream: BinaryIO, *, filename: str, media_type: str,
    ) -> Document:
        metadata = await to_thread.run_sync(_inspect_pdf, stream, filename, media_type, self.max_bytes)
        try:
            document = await self._repository.create(
                context, metadata, initial_status=DocumentStatus.UPLOADING,
            )
        except PyMongoError:
            logger.error("Upload metadata intent failed")
            raise DocumentStorageError() from None
        try:
            await self._objects.upload(context, document.document_id, stream, metadata.size_bytes)
            committed = await self._repository.transition_status(
                context, document.document_id,
                expected=DocumentStatus.UPLOADING, target=DocumentStatus.PENDING,
            )
            if committed is None:
                raise DocumentStorageError()
        except BaseException as error:
            # Shield compensation on cancellation. Never delete bytes after an
            # ambiguous finalize unless a CAS first confirms failure ownership.
            with CancelScope(shield=True):
                await self._compensate(context, document.document_id)
            if not isinstance(error, Exception):
                raise
            logger.error("Document upload failed; document_id=%s", document.document_id)
            raise DocumentStorageError() from None
        logger.info("Document upload completed; document_id=%s", document.document_id)
        return committed

    async def _compensate(self, context: TenantContext, document_id: UUID) -> None:
        try:
            failed = await self._repository.transition_status(
                context, document_id,
                expected=DocumentStatus.UPLOADING, target=DocumentStatus.FAILED,
            )
            if failed is None:
                logger.warning("Upload state changed; cleanup deferred; document_id=%s", document_id)
                return
            await self._objects.remove(context, document_id)
        except Exception:
            logger.error("Upload recovery required; document_id=%s", document_id)

    async def get(self, context: TenantContext, document_id: UUID) -> Document:
        try:
            document = await self._repository.get(context, document_id)
        except PyMongoError:
            logger.error("Document metadata lookup failed")
            raise DocumentStorageError() from None
        if document is None or document.tenant_id != context.tenant_id or document.uploaded_by != context.user_id:
            raise DocumentNotFound()
        return document

    async def list(self, context: TenantContext, *, limit: int = 50) -> list[Document]:
        try:
            return await self._repository.list(context, limit=limit, owned_only=True)
        except PyMongoError:
            logger.error("Document metadata listing failed")
            raise DocumentStorageError() from None
