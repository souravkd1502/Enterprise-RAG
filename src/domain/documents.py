"""Document metadata and lifecycle values, independent of storage clients."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DocumentStatus(StrEnum):
    """Metadata lifecycle; READY alone is not an authorization/searchability check."""

    UPLOADING = "uploading"
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class DocumentMetadata(BaseModel):
    """Caller-supplied descriptive fields; never accept ownership from a payload.

    File names are display metadata, not filesystem paths or object-store keys.
    Actual MIME detection, upload limits, and content hashing belong to ingestion.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    filename: Annotated[NonEmptyText, Field(max_length=255)] = Field(repr=False)
    media_type: Annotated[NonEmptyText, Field(max_length=127)]
    size_bytes: int = Field(gt=0, strict=True)


class Document(DocumentMetadata):
    """Persisted metadata with repository-assigned identity and UTC timestamps.

    A metadata record does not prove that blob upload or indexing has completed.
    No arbitrary metadata map is accepted, preventing ownership/operator injection.
    """

    document_id: UUID
    tenant_id: str
    uploaded_by: str
    status: DocumentStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
