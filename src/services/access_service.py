"""Database authorization supplements external JWT identity on every tenant request."""
import logging

from pymongo.errors import PyMongoError

from src.core.exceptions import AuthForbidden, AuthUnavailable
from src.core.tenancy import TenantContext
from src.infrastructure.mongodb.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class AccessService:
    def __init__(self, repository: TenantRepository) -> None:
        self._repository = repository

    async def require_membership(self, context: TenantContext) -> dict:
        try:
            member = await self._repository.membership(context.user_id, context.tenant_id)
        except PyMongoError:
            logger.error("Membership validation unavailable")
            raise AuthUnavailable() from None
        if member is None:
            raise AuthForbidden()
        return member
