"""Local account onboarding. IDs in URLs never substitute for membership checks."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from src.api.routes.auth import Account, Service, _no_store
from src.schemas.auth import (
    AcceptInvitationRequest, InvitationRequest, InvitationResponse, MembershipResponse,
    WorkspaceRequest, WorkspaceResponse,
)
from src.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["workspaces"], responses={
    400: {"description": "Invitation expired, consumed, or email does not match"},
    401: {"description": "Valid local account access token required"},
    403: {"description": "Active membership or OWNER role required"},
    429: {"description": "Authentication request budget exhausted"},
    503: {"description": "Storage or configured invitation delivery unavailable"},
})


def tenant_service(request: Request) -> TenantService:
    return request.app.state.tenant_service


Tenants = Annotated[TenantService, Depends(tenant_service)]


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create(body: WorkspaceRequest, response: Response, user: Account, tenants: Tenants):
    """Create a tenant and initial OWNER atomically. Then call /auth/select-tenant."""
    _no_store(response)
    return await tenants.create(user, body.name)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(response: Response, user: Account, service: Service):
    """List only the authenticated user's active workspaces."""
    _no_store(response)
    return (await service.profile(user))["workspaces"]


@router.post("/invitations/accept", response_model=WorkspaceResponse)
async def accept(body: AcceptInvitationRequest, response: Response, user: Account, tenants: Tenants):
    """Consume an unexpired invitation matching your account email. Select the workspace next."""
    _no_store(response)
    return await tenants.accept(user, body.token.get_secret_value())


@router.post("/{tenant_id}/invitations", response_model=InvitationResponse, status_code=201)
async def invite(tenant_id: UUID, body: InvitationRequest, response: Response, user: Account, tenants: Tenants):
    """OWNER only. Return the invitation token/link once in development; no email is sent."""
    _no_store(response)
    return await tenants.invite(user, tenant_id.hex, str(body.email), body.role)


@router.get("/{tenant_id}/members", response_model=list[MembershipResponse])
async def members(tenant_id: UUID, response: Response, user: Account, tenants: Tenants):
    """OWNER only. List up to 1,000 membership records for this workspace."""
    _no_store(response)
    return await tenants.members(user, tenant_id.hex)
