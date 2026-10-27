"""Tenant-derived object paths and bounded-memory synchronous SDK operations."""

from functools import partial
from hashlib import sha256
from typing import BinaryIO
from uuid import UUID

from anyio import to_thread
from minio import Minio

from src.core.tenancy import TenantContext


def object_key(context: TenantContext, document_id: UUID) -> str:
    """Derive a fixed-length namespace; callers never supply raw storage paths.

    Hashing opaque tenant IDs prevents slash/control/path interpretation and keeps
    long Unicode IDs within S3 key limits. Hashes are identifiers, not secrets.
    """
    if not isinstance(context, TenantContext) or not isinstance(document_id, UUID):
        raise TypeError("Verified tenant context and a document UUID are required")
    tenant = sha256(context.tenant_id.encode("utf-8")).hexdigest()
    return f"tenants/{tenant}/documents/{document_id.hex}/original.pdf"


class ObjectStore:
    """Tenant storage boundary, not document ACL enforcement.

    Trusted services must check document ownership before reading/removing an
    existing object. Inputs and outputs are streams; document bytes are not logged.
    """

    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def upload(
        self, context: TenantContext, document_id: UUID, stream: BinaryIO, size: int,
    ) -> None:
        """Write exactly the validated length without loading the whole file."""
        key = object_key(context, document_id)
        if type(size) is not int or size <= 0:
            raise ValueError("Object size must be a positive integer")
        await to_thread.run_sync(partial(
            self._client.put_object, self._bucket, key, stream, size,
            content_type="application/pdf", num_parallel_uploads=1,
        ))

    async def download_to(
        self, context: TenantContext, document_id: UUID, destination: BinaryIO,
    ) -> None:
        """Stream into an authorized caller's destination and always release HTTP resources."""
        key = object_key(context, document_id)

        def transfer() -> None:
            response = self._client.get_object(self._bucket, key)
            try:
                for chunk in response.stream(64 * 1024):
                    destination.write(chunk)
            finally:
                response.close()
                response.release_conn()

        await to_thread.run_sync(transfer)

    async def remove(self, context: TenantContext, document_id: UUID) -> None:
        """Idempotently remove only the derived tenant/document object."""
        key = object_key(context, document_id)
        await to_thread.run_sync(self._client.remove_object, self._bucket, key)
