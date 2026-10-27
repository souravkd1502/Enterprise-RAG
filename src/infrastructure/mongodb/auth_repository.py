"""Global accounts and revocable sessions; tenant access lives in memberships."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from src.infrastructure.mongodb.tenant_repository import TenantRepository


class AuthRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._users = database["auth_users"]
        self._sessions = database["auth_sessions"]
        self._limits = database["auth_rate_limits"]
        self.tenants = TenantRepository(database)

    async def create_user(self, email: str, password_hash: str, name: str, workspace_name: str | None = None) -> dict:
        user = {
            "email": email, "password_hash": password_hash, "active": True,
            "user_id": uuid4().hex, "name": name, "auth_provider": "local",
            "schema_version": 2, "created_at": datetime.now(timezone.utc),
        }
        tenant_id = uuid4().hex
        async def create(session):
            await self._users.insert_one(dict(user), session=session)
            if workspace_name is not None:
                await self.tenants.insert_workspace(user["user_id"], workspace_name, tenant_id, session)
            await self.tenants.record("account.created", user["user_id"], session=session)
        await self.tenants.transaction(create)
        return user

    async def migrate_legacy_users(self) -> int:
        """Add missing workspace records without changing old document tenant IDs.

        Upserts and a schema marker make restart/retry safe. Old JWTs must be
        replaced by logging in because account/tenant scope is now explicit.
        """
        count = 0
        async for user in self._users.find({"tenant_id": {"$exists": True}, "schema_version": {"$ne": 2}}):
            async def migrate(session):
                now = user["created_at"]
                await self.tenants.tenants.update_one({"tenant_id": user["tenant_id"]}, {
                    "$setOnInsert": {"name": "Legacy workspace", "status": "active", "created_at": now},
                }, upsert=True, session=session)
                await self.tenants.memberships.update_one({
                    "tenant_id": user["tenant_id"], "user_id": user["user_id"],
                }, {"$setOnInsert": {"role": "OWNER", "status": "active", "joined_at": now}},
                    upsert=True, session=session)
                await self._users.update_one({"_id": user["_id"]}, {"$set": {
                    "name": user.get("name", "User"), "auth_provider": "local", "schema_version": 2,
                }}, session=session)
            await self.tenants.transaction(migrate)
            count += 1
        return count

    async def find_email(self, email: str) -> dict | None:
        return await self._users.find_one({"email": email})

    async def find_user(self, user_id: str) -> dict | None:
        return await self._users.find_one({"user_id": user_id, "active": True})

    async def create_session(self, user_id: str, session_id: str, token_hash: str, expires_at: datetime, tenant_id: str | None = None) -> None:
        async def create(session):
            await self._sessions.insert_one({
                "_id": session_id, "tenant_id": tenant_id, "user_id": user_id,
                "refresh_hash": token_hash, "expires_at": expires_at, "revoked": False,
                "created_at": datetime.now(timezone.utc),
            }, session=session)
            await self.tenants.record("session.created", user_id, tenant_id, session=session)
        await self.tenants.transaction(create)

    async def active_session(self, user_id: str, session_id: str) -> dict | None:
        return await self._sessions.find_one({
            "_id": session_id, "user_id": user_id, "revoked": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        })

    async def rotate(self, user_id: str, session_id: str, previous_hash: str, next_hash: str, tenant_id: str | None) -> dict | None:
        """Compare-and-swap the refresh hash and workspace in a single write."""
        return await self._sessions.find_one_and_update({
            "_id": session_id, "user_id": user_id, "revoked": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)}, "refresh_hash": previous_hash,
        }, {"$set": {"refresh_hash": next_hash, "tenant_id": tenant_id,
                     "updated_at": datetime.now(timezone.utc)}}, return_document=ReturnDocument.AFTER)

    async def revoke(self, user_id: str, session_id: str) -> None:
        async def revoke(session):
            record = await self._sessions.find_one_and_update({
                "_id": session_id, "user_id": user_id, "revoked": False,
            }, {"$set": {"revoked": True, "revoked_at": datetime.now(timezone.utc)}},
                return_document=ReturnDocument.AFTER, session=session)
            if record:
                await self.tenants.record("session.revoked", user_id, record.get("tenant_id"), session=session)
        await self.tenants.transaction(revoke)

    async def rate_allowed(self, scope: str, maximum: int) -> bool:
        """Distributed fixed-minute budget. TTL is cleanup, not enforcement."""
        now = int(datetime.now(timezone.utc).timestamp())
        key = sha256(f"{scope}:{now // 60}".encode()).hexdigest()
        query = {"_id": key}
        update = {"$inc": {"count": 1}, "$setOnInsert": {
            "expires_at": datetime.fromtimestamp((now // 60 + 2) * 60, timezone.utc),
        }}
        try:
            record = await self._limits.find_one_and_update(query, update, upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            record = await self._limits.find_one_and_update(query, {"$inc": {"count": 1}}, return_document=ReturnDocument.AFTER)
        return record is not None and record["count"] <= maximum
