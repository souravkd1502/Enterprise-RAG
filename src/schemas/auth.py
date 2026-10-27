"""Strict API contracts. Secrets are omitted from representations and errors."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

Role = Literal["OWNER", "MEMBER"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Credentials(StrictModel):
    email: EmailStr = Field(max_length=254, repr=False, examples=["owner@example.com"])
    password: SecretStr = Field(repr=False, examples=["A-long-local-test-password!"])

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not 15 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Password must contain 15 to 128 characters")
        return value


class SignupRequest(Credentials):
    name: str = Field(min_length=1, max_length=120, examples=["Workspace owner"])
    workspace_name: str | None = Field(default=None, min_length=1, max_length=120,
        description="Optional: create your first workspace atomically with its OWNER membership.")

    @field_validator("name", "workspace_name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("A visible display name is required")
        return value


class LoginRequest(Credentials):
    tenant_id: UUID | None = Field(default=None,
        description="Optional workspace selection; active membership is required.")


class RefreshRequest(StrictModel):
    refresh_token: SecretStr = Field(min_length=1, max_length=16384, repr=False)


class SelectTenantRequest(RefreshRequest):
    tenant_id: UUID


class WorkspaceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120, examples=["Acme workspace"])
    _clean_name = field_validator("name")(SignupRequest.clean_name.__func__)


class WorkspaceResponse(BaseModel):
    tenant_id: str
    name: str
    status: Literal["active"]
    created_at: datetime
    role: Role


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int
    tenant_id: str | None
    user_id: str
    role: Role | None = None
    workspaces: list[WorkspaceResponse] = Field(default_factory=list)
    tenant_selection_required: bool = False


class ProfileResponse(BaseModel):
    user_id: str
    email: EmailStr
    name: str
    auth_provider: str
    workspaces: list[WorkspaceResponse]


class InvitationRequest(StrictModel):
    email: EmailStr = Field(max_length=254, examples=["member@example.com"])
    role: Role = "MEMBER"


class AcceptInvitationRequest(StrictModel):
    token: SecretStr = Field(min_length=32, max_length=256, repr=False)


class InvitationResponse(BaseModel):
    invitation_id: str
    tenant_id: str
    expires_at: datetime
    invitation_token: str = Field(repr=False)
    invitation_link: str = Field(repr=False)


class MembershipResponse(BaseModel):
    tenant_id: str
    user_id: str
    role: Role
    status: str
    joined_at: datetime
