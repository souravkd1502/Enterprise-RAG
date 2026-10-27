"""Authenticated PDF upload and uploader-only metadata endpoints.

Multipart parsing happens inside the authenticated endpoint and counts bytes
before spooling. Both declared and streamed lengths are checked.
"""

from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from src.api.dependencies import get_document_service, get_tenant_context
from src.core.exceptions import UploadTooLarge
from src.core.tenancy import TenantContext
from src.schemas.documents import DocumentResponse
from src.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
Service = Annotated[DocumentService, Depends(get_document_service)]


class _MultipartTooLarge(MultiPartException):
    """Close partially spooled files through the multipart parser's error path."""


async def _bounded_stream(request: Request, limit: int) -> AsyncGenerator[bytes, None]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise _MultipartTooLarge("Upload exceeds request limit")
        yield chunk


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "additionalProperties": False,
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                },
            },
        }
    },
)
async def upload_document(request: Request, context: Tenant, service: Service):
    """Accept one multipart field named file, containing a PDF, after JWT verification."""
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "multipart/form-data"
    ):
        raise HTTPException(
            status_code=415, detail="Use multipart/form-data with one PDF file"
        )
    request_limit = service.max_bytes + 64 * 1024
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid Content-Length"
            ) from None
        if declared < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared > request_limit:
            raise UploadTooLarge()
    parser = MultiPartParser(
        request.headers,
        _bounded_stream(request, request_limit),
        max_files=1,
        max_fields=0,
    )
    try:
        form = await parser.parse()
    except _MultipartTooLarge:
        raise UploadTooLarge() from None
    except MultiPartException:
        raise HTTPException(
            status_code=400, detail="Exactly one file field named file is required"
        ) from None
    try:
        file = form.get("file")
        if len(form.multi_items()) != 1 or not isinstance(file, UploadFile):
            raise HTTPException(
                status_code=400, detail="Exactly one file field named file is required"
            )
        return await service.upload(
            context,
            file.file,
            filename=file.filename or "",
            media_type=file.content_type or "",
        )
    finally:
        await form.close()


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    context: Tenant,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """List at most 100 visible documents uploaded by this user in this tenant."""
    return await service.list(context, limit=limit)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: UUID, context: Tenant, service: Service):
    """Return metadata or the same 404 for missing, foreign, or other-user documents."""
    return await service.get(context, document_id)
