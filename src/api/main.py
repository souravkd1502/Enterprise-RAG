"""FastAPI entry point; runtime initialization happens in lifespan, not import."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from anyio import to_thread
from pymongo.errors import PyMongoError

from src.api.routes.health import router as health_router
from src.api.routes.documents import router as documents_router
from src.api.routes.auth import router as auth_router
from src.api.routes.tenants import router as tenants_router
from src.services.access_service import AccessService
from src.services.tenant_service import TenantService
from src.infrastructure.mongodb.tenant_repository import TenantRepository
from src.core.config import get_settings
from src.core.exceptions import (
    DocumentError,
    DocumentNotFound,
    DocumentStorageError,
    InvalidDocument,
    UnsupportedDocument,
    UploadTooLarge,
    AuthError,
    AuthRejected,
    AuthRateLimited,
    AccountConflict,
    AuthUnavailable,
    AuthForbidden,
    WorkspaceRequired,
    InvitationRejected,
)
from src.core.logging import configure_logging
from src.core.security import TokenVerifier, LocalTokenCodec
from src.infrastructure.mongodb.client import mongodb_database
from src.infrastructure.mongodb.document_repository import DocumentRepository
from src.infrastructure.minio.client import minio_object_store
from src.services.document_service import DocumentService
from src.services.auth_service import AuthService
from src.infrastructure.mongodb.auth_repository import AuthRepository
from src.infrastructure.mongodb.indexes import ensure_auth_indexes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate settings and initialize process-owned MongoDB and JWT resources."""
    configure_logging()
    settings = get_settings()
    configure_logging(settings.log_level)
    async with (
        mongodb_database(settings) as database,
        minio_object_store(settings) as objects,
    ):
        auth_service = None
        repository = AuthRepository(database)
        try:
            await ensure_auth_indexes(database)
            if settings.auth_mode == "local":
                migrated = await repository.migrate_legacy_users()
                if migrated:
                    logger.info("Legacy accounts migrated: %d", migrated)
        except PyMongoError:
            logger.error("Authentication storage initialization failed")
            raise RuntimeError("Authentication storage initialization failed") from None
        if settings.auth_mode == "local":
            verifier = await to_thread.run_sync(LocalTokenCodec, settings)
            auth_service = AuthService(repository, verifier, settings)
            await auth_service.initialize()
        else:
            verifier = TokenVerifier(settings)
        app.state.mongodb = database
        app.state.token_verifier = verifier
        app.state.auth_service = auth_service
        app.state.access_service = AccessService(TenantRepository(database))
        app.state.tenant_service = TenantService(TenantRepository(database), settings)
        app.state.document_service = DocumentService(
            DocumentRepository(database),
            objects,
            settings.upload_max_bytes,
        )
        logger.info("API process started")
        try:
            yield
        finally:
            del app.state.token_verifier
            del app.state.mongodb
            del app.state.document_service
            del app.state.auth_service
            del app.state.access_service
            del app.state.tenant_service
            logger.info("API process stopped")


app = FastAPI(
    title="Enterprise RAG API",
    version="0.1.0",
    lifespan=lifespan,
    description="Local testing: signup → create workspace → select tenant → Authorize with access_token. "
    "Owners can invite an email; that account accepts, then selects the workspace. "
    "See docs/local-auth.md for a complete Swagger walkthrough.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "persistAuthorization": False,
        "displayRequestDuration": True,
    },
)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(auth_router)
app.include_router(tenants_router)


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, error: AuthError) -> JSONResponse:
    """Never expose credentials, account records, token contents, or driver details."""
    errors = {
        AuthRejected: (401, "Invalid credentials or session"),
        AccountConflict: (409, "Account unavailable"),
        AuthUnavailable: (503, "Authentication service unavailable"),
        AuthRateLimited: (429, "Too many authentication requests"),
        AuthForbidden: (403, "Active membership or required workspace role missing"),
        WorkspaceRequired: (403, "Select a workspace before accessing tenant data"),
        InvitationRejected: (
            400,
            "Invitation unavailable or does not match this account",
        ),
    }
    status, detail = errors.get(type(error), (500, "Authentication failed"))
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = "60"
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request: Request, error: RequestValidationError):
    """Pydantic input payloads must not echo passwords or refresh tokens in 422s."""
    if request.url.path.startswith(("/auth/", "/tenants")):
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid authentication input"},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, error)


@app.exception_handler(DocumentError)
async def document_error_handler(
    request: Request, error: DocumentError
) -> JSONResponse:
    """Expose fixed client messages, never storage exceptions or submitted data."""
    responses = {
        InvalidDocument: (400, "Invalid file metadata"),
        UnsupportedDocument: (415, "Only PDF files with a PDF signature are accepted"),
        UploadTooLarge: (413, "Upload exceeds configured size limit"),
        DocumentNotFound: (404, "Document not found"),
        DocumentStorageError: (503, "Document storage unavailable"),
    }
    status_code, detail = responses.get(type(error), (500, "Document operation failed"))
    return JSONResponse(status_code=status_code, content={"detail": detail})
