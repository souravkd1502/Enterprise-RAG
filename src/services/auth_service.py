"""Local password authentication, workspace selection and revocable token rotation.

Accounts are global. A session has at most one selected workspace. Every access
checks the active user, session and selection; tenant data also requires a live
membership. No password, email, JWT or invitation token is written to logs.
"""
import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from anyio import CapacityLimiter, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jwt.exceptions import InvalidTokenError
from pymongo.errors import DuplicateKeyError, PyMongoError

from src.core.exceptions import (
    AccountConflict, AuthForbidden, AuthRateLimited, AuthRejected,
    AuthUnavailable, WorkspaceRequired,
)
from src.core.config import Settings
from src.core.security import IssuedTokens, LocalTokenCodec, VerifiedLocalToken
from src.core.tenancy import TenantContext
from src.infrastructure.mongodb.auth_repository import AuthRepository

logger = logging.getLogger(__name__)


def _digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


class AuthService:
    """Only refresh hashes persist. Signed refresh replay revokes its session.

    Clients must serialize refresh/selection requests. Switching workspace rotates
    refresh credentials and immediately invalidates older access-token selections.
    """
    def __init__(self, repository: AuthRepository, codec: LocalTokenCodec, settings: Settings) -> None:
        self._repository = repository
        self._codec = codec
        self._settings = settings
        self._passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
        self._password_limiter = CapacityLimiter(4)
        self._dummy_hash = None

    async def initialize(self) -> None:
        self._dummy_hash = await to_thread.run_sync(self._passwords.hash, token_urlsafe(32))

    async def enforce_limit(self, scope: str, maximum: int | None = None) -> None:
        try:
            allowed = await self._repository.rate_allowed(
                scope, maximum or self._settings.auth_requests_per_minute)
        except PyMongoError:
            logger.error("Authentication rate-limit storage unavailable")
            raise AuthUnavailable() from None
        if not allowed:
            raise AuthRateLimited()

    async def signup(self, email: str, password: str, name: str, workspace_name: str | None = None) -> IssuedTokens:
        encoded = await to_thread.run_sync(
            self._passwords.hash, password, limiter=self._password_limiter)
        try:
            user = await self._repository.create_user(email.casefold(), encoded, name, workspace_name)
            tokens = await self._new_session(user["user_id"])
        except DuplicateKeyError:
            raise AccountConflict() from None
        except PyMongoError:
            logger.error("Signup persistence failed")
            raise AuthUnavailable() from None
        logger.info("Local account registered")
        return tokens

    async def login(self, email: str, password: str, tenant_id: str | None = None) -> IssuedTokens:
        await self.enforce_limit("account:" + email.casefold(), 10)
        try:
            user = await self._repository.find_email(email.casefold())
            encoded = user["password_hash"] if user else self._dummy_hash
            def verify() -> bool:
                try:
                    return self._passwords.verify(encoded, password)
                except (VerificationError, InvalidHashError):
                    return False
            valid = await to_thread.run_sync(verify, limiter=self._password_limiter)
            if not valid or user is None or not user["active"]:
                raise AuthRejected()
            tokens = await self._new_session(user["user_id"], tenant_id)
        except PyMongoError:
            logger.error("Login persistence failed")
            raise AuthUnavailable() from None
        logger.info("Local login completed")
        return tokens

    async def _selection(self, user_id: str, tenant_id: str | None = None, auto_select: bool = False) -> tuple[str | None, list[dict], dict | None]:
        workspaces = await self._repository.tenants.workspaces(user_id)
        if tenant_id is None and auto_select and len(workspaces) == 1:
            tenant_id = workspaces[0]["tenant_id"]
        selected = next((w for w in workspaces if w["tenant_id"] == tenant_id), None)
        if tenant_id is not None and selected is None:
            raise AuthForbidden()
        return tenant_id, workspaces, selected

    def _describe(self, tokens: IssuedTokens, workspaces: list[dict], selected: dict | None) -> IssuedTokens:
        return replace(tokens, workspaces=tuple(workspaces),
            role=selected["role"] if selected else None,
            tenant_selection_required=tokens.tenant_id is None and len(workspaces) > 1)

    async def _new_session(self, user_id: str, tenant_id: str | None = None) -> IssuedTokens:
        tenant_id, workspaces, selected = await self._selection(user_id, tenant_id, auto_select=True)
        sid = uuid4().hex
        expiry = int(time.time()) + self._settings.auth_refresh_token_seconds
        tokens = await to_thread.run_sync(self._codec.issue_identity, user_id, tenant_id, sid, expiry)
        await self._repository.create_session(user_id, sid, _digest(tokens.refresh_token),
            datetime.fromtimestamp(expiry, timezone.utc), tenant_id)
        return self._describe(tokens, workspaces, selected)

    async def _identity(self, token: str) -> tuple[dict, VerifiedLocalToken]:
        """Verify once; selected tenant must still match the stored session."""
        try:
            verified = await to_thread.run_sync(self._codec.decode, token, "access")
            session = await self._repository.active_session(verified.user_id, verified.session_id)
            user = await self._repository.find_user(verified.user_id) if session else None
            tenant_id = verified.context.tenant_id if verified.context else None
            if session is None or user is None or session.get("tenant_id") != tenant_id:
                raise AuthRejected()
            return user, verified
        except InvalidTokenError:
            raise AuthRejected() from None
        except PyMongoError:
            logger.error("Session validation unavailable")
            raise AuthUnavailable() from None

    async def authenticate_identity(self, token: str) -> dict:
        """Allow a verified account to onboard without requiring a workspace."""
        user, _ = await self._identity(token)
        return user

    async def authenticate_access(self, token: str) -> TenantContext:
        user, verified = await self._identity(token)
        if verified.context is None:
            raise WorkspaceRequired()
        try:
            member = await self._repository.tenants.membership(
                user["user_id"], verified.context.tenant_id)
        except PyMongoError:
            raise AuthUnavailable() from None
        if member is None:
            raise AuthForbidden()
        return verified.context

    async def profile(self, user: dict) -> dict:
        try:
            return {key: user[key] for key in ("user_id", "email", "name", "auth_provider")} | {
                "workspaces": await self._repository.tenants.workspaces(user["user_id"])}
        except PyMongoError:
            raise AuthUnavailable() from None

    async def refresh(self, token: str, tenant_id: str | None = None, *, select: bool = False) -> IssuedTokens:
        try:
            verified = await to_thread.run_sync(self._codec.decode, token, "refresh")
            if await self._repository.find_user(verified.user_id) is None:
                raise AuthRejected()
            target = tenant_id if select else (verified.context.tenant_id if verified.context else None)
            target, workspaces, selected = await self._selection(verified.user_id, target)
            tokens = await to_thread.run_sync(self._codec.issue_identity,
                verified.user_id, target, verified.session_id, verified.expires_at)
            rotated = await self._repository.rotate(verified.user_id, verified.session_id,
                _digest(token), _digest(tokens.refresh_token), target)
            if rotated is None:
                await self._repository.revoke(verified.user_id, verified.session_id)
                logger.warning("Refresh token rejected; session revoked")
                raise AuthRejected()
        except InvalidTokenError:
            raise AuthRejected() from None
        except PyMongoError:
            logger.error("Refresh persistence failed")
            raise AuthUnavailable() from None
        logger.info("Workspace selected" if select else "Refresh token rotated")
        return self._describe(tokens, workspaces, selected)

    async def logout(self, token: str) -> None:
        try:
            verified = await to_thread.run_sync(self._codec.decode, token, "refresh")
        except InvalidTokenError:
            return
        try:
            await self._repository.revoke(verified.user_id, verified.session_id)
        except PyMongoError:
            logger.error("Logout persistence failed")
            raise AuthUnavailable() from None
        logger.info("Local session revoked")
