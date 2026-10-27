"""Optional local authentication endpoints; refresh/logout consume JSON token bodies."""

from typing import Annotated, AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from src.api.dependencies import bearer

from src.core.logging import log_context
from src.schemas.auth import (SignupRequest, LoginRequest, RefreshRequest,
    SelectTenantRequest, TokenResponse, ProfileResponse)
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"], responses={
    401: {"description": "Invalid credentials or revoked/expired session"},
    403: {"description": "Active workspace membership required"},
    409: {"description": "Account unavailable"},
    429: {"description": "Authentication request budget exhausted"},
    503: {"description": "Authentication storage unavailable"},
})


async def local_auth(request: Request) -> AsyncIterator[AuthService]:
    """Apply a distributed per-client budget before any expensive password hashing.

    Client IP comes from ASGI scope. Configure trusted proxy handling at the server;
    this dependency never trusts arbitrary forwarded headers on its own.
    """
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=404, detail="Local authentication is disabled")
    with log_context(request_id=uuid4().hex):
        await service.enforce_limit("client:" + (request.client.host if request.client else "unknown"))
        yield service


Service = Annotated[AuthService, Depends(local_auth)]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, response: Response, service: Service):
    """Create a global account. Optionally create its first workspace and OWNER membership."""
    _no_store(response)
    return await service.signup(str(body.email), body.password.get_secret_value(), body.name, body.workspace_name)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, service: Service):
    """Login and list workspaces. One auto-selects; multiple require select-tenant."""
    _no_store(response)
    return await service.login(str(body.email), body.password.get_secret_value(),
        body.tenant_id.hex if body.tenant_id else None)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, response: Response, service: Service):
    """Rotate once; reuse of a previously consumed signed token revokes the session."""
    _no_store(response)
    return await service.refresh(body.refresh_token.get_secret_value())


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, service: Service) -> Response:
    """Idempotently revoke the refresh token's session and its outstanding access tokens."""
    await service.logout(body.refresh_token.get_secret_value())
    response = Response(status_code=204)
    _no_store(response)
    return response


async def account_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Service,
) -> dict:
    """Validate a local account session without requiring an existing workspace."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"})
    return await service.authenticate_identity(credentials.credentials)


Account = Annotated[dict, Depends(account_user)]


@router.get("/me", response_model=ProfileResponse)
async def me(response: Response, user: Account, service: Service):
    """Return the authenticated global profile and active workspace memberships."""
    _no_store(response)
    return await service.profile(user)


@router.post("/select-tenant", response_model=TokenResponse)
async def select_tenant(body: SelectTenantRequest, response: Response, service: Service):
    """Select an authorized workspace and rotate tokens. Replace Swagger's access token."""
    _no_store(response)
    return await service.refresh(body.refresh_token.get_secret_value(), body.tenant_id.hex, select=True)
