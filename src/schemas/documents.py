"""Public document metadata; storage paths and authentication claims stay internal."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from src.domain.documents import DocumentStatus


class DocumentResponse(BaseModel):
    """Upload/lookup result; pending means stored, not indexed or queued yet."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    filename: str
    media_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
