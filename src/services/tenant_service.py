"""Workspace onboarding and one-time, email-bound development invitations."""
import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from urllib.parse import quote

from pymongo.errors import PyMongoError

from src.core.config import Settings
from src.core.exceptions import AuthUnavailable
from src.core.logging import log_context
from src.infrastructure.mongodb.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class TenantService:
    def __init__(self, repository: TenantRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def create(self, user: dict, name: str) -> dict:
        try:
            workspace = await self._repository.create_workspace(user["user_id"], name)
        except PyMongoError:
            logger.error("Workspace creation failed")
            raise AuthUnavailable() from None
        with log_context(user_id=user["user_id"], tenant_id=workspace["tenant_id"]):
            logger.info("Workspace created")
        return workspace

    async def invite(self, user: dict, tenant_id: str, email: str, role: str) -> dict:
        # There is deliberately no silent production fallback or SMTP delivery.
        if not self._settings.auth_invitation_development_links:
            raise AuthUnavailable()
        token = token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(seconds=self._settings.auth_invitation_seconds)
        try:
            invitation_id = await self._repository.invite(user["user_id"], tenant_id,
                email.casefold(), role, sha256(token.encode()).hexdigest(), expires)
        except PyMongoError:
            logger.error("Invitation persistence failed")
            raise AuthUnavailable() from None
        with log_context(user_id=user["user_id"], tenant_id=tenant_id):
            logger.info("Workspace invitation created")
        # The fragment is never sent in HTTP request URLs or server access logs.
        link = str(self._settings.auth_public_base_url).rstrip("/") + "/docs#invitation_token=" + quote(token)
        return {"invitation_id": invitation_id, "tenant_id": tenant_id,
                "expires_at": expires, "invitation_token": token, "invitation_link": link}

    async def accept(self, user: dict, token: str) -> dict:
        try:
            workspace = await self._repository.accept(user, sha256(token.encode()).hexdigest())
        except PyMongoError:
            logger.error("Invitation acceptance failed")
            raise AuthUnavailable() from None
        with log_context(user_id=user["user_id"], tenant_id=workspace["tenant_id"]):
            logger.info("Workspace invitation accepted")
        return workspace

    async def members(self, user: dict, tenant_id: str) -> list[dict]:
        try:
            return await self._repository.members(user["user_id"], tenant_id)
        except PyMongoError:
            logger.error("Workspace member listing failed")
            raise AuthUnavailable() from None
