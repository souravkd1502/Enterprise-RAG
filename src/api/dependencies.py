"""JWT authentication dependencies and scoped request logging for protected APIs."""

import logging
from typing import Annotated, AsyncIterator
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from anyio import to_thread
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)

from src.core.logging import log_context
from src.core.security import TokenVerifier
from src.core.tenancy import TenantContext
from src.services.document_service import DocumentService

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False, scheme_name="AccessToken",
    description="Paste access_token from signup/login/select-tenant. Account tokens can onboard; document requests require a selected workspace.")


def get_document_service(request: Request) -> DocumentService:
    """Return the process-owned service; routes must also require verified context."""
    return request.app.state.document_service


def get_token_verifier(request: Request) -> TokenVerifier:
    """Return the per-process verifier created during application startup."""
    return request.app.state.token_verifier


async def authenticate(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    request: Request,
) -> TenantContext:
    """Check local session revocation or run external verification in a worker thread."""
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        local_service = getattr(request.app.state, "auth_service", None)
        if local_service is not None:
            return await local_service.authenticate_access(credentials.credentials)
        context = await to_thread.run_sync(verifier.verify, credentials.credentials)
        await request.app.state.access_service.require_membership(context)
        return context
    except PyJWKClientConnectionError:
        logger.error("JWT signing key service unavailable")
        raise HTTPException(
            status_code=503, detail="Authentication service unavailable"
        ) from None
    except (InvalidTokenError, PyJWKClientError):
        logger.debug("JWT authentication rejected")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


async def get_tenant_context(
    context: Annotated[TenantContext, Depends(authenticate)],
) -> AsyncIterator[TenantContext]:
    """Bind verified identity on the request task and restore it after handling.

    Callers receive explicit identity for service/repository calls. Request IDs
    are generated here; headers, query parameters and bodies cannot override
    tenant/user identity. This dependency does not perform document ACL checks.
    """
    with log_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        request_id=uuid4().hex,
    ):
        yield context
