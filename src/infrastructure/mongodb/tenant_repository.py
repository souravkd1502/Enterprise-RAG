"""Workspace persistence. Transactions keep owners, memberships and invitations consistent.

Callbacks may be retried by MongoDB; generate IDs before starting a transaction
and perform no email, token delivery, or other external side effects inside one.
"""
from datetime import datetime, timezone
from uuid import uuid4
from typing import Awaitable, Callable, TypeVar

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from src.core.exceptions import AuthForbidden, InvitationRejected


T = TypeVar("T")


class TenantRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self.database = database
        self.tenants = database["tenants"]
        self.memberships = database["memberships"]
        self.invitations = database["invitations"]
        self.audit = database["audit_events"]

    async def transaction(self, callback: Callable[[AsyncClientSession], Awaitable[T]]) -> T:
        async with self.database.client.start_session() as session:
            return await session.with_transaction(
                callback, read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    async def record(self, action: str, user_id: str, tenant_id: str | None = None, *, session: AsyncClientSession | None = None) -> None:
        await self.audit.insert_one({
            "event_id": uuid4().hex, "action": action, "actor_id": user_id,
            "tenant_id": tenant_id, "created_at": datetime.now(timezone.utc),
        }, session=session)

    async def insert_workspace(self, user_id: str, name: str, tenant_id: str, session: AsyncClientSession) -> dict:
        now = datetime.now(timezone.utc)
        tenant = {"tenant_id": tenant_id, "name": name, "status": "active", "created_at": now}
        await self.tenants.insert_one(dict(tenant), session=session)
        await self.memberships.insert_one({
            "tenant_id": tenant_id, "user_id": user_id, "role": "OWNER",
            "status": "active", "joined_at": now,
        }, session=session)
        await self.record("tenant.created", user_id, tenant_id, session=session)
        return {**tenant, "role": "OWNER"}

    async def create_workspace(self, user_id: str, name: str) -> dict:
        tenant_id = uuid4().hex
        async def create(session):
            return await self.insert_workspace(user_id, name, tenant_id, session)
        return await self.transaction(create)

    async def membership(self, user_id: str, tenant_id: str, *, session: AsyncClientSession | None = None) -> dict | None:
        tenant = await self.tenants.find_one(
            {"tenant_id": tenant_id, "status": "active"}, session=session)
        if tenant is None:
            return None
        return await self.memberships.find_one({
            "tenant_id": tenant_id, "user_id": user_id, "status": "active",
            "role": {"$in": ["OWNER", "MEMBER"]},
        }, session=session)

    async def workspaces(self, user_id: str) -> list[dict]:
        result = []
        async for membership in self.memberships.find({
            "user_id": user_id, "status": "active", "role": {"$in": ["OWNER", "MEMBER"]},
        }).sort("joined_at", 1):
            tenant = await self.tenants.find_one({
                "tenant_id": membership["tenant_id"], "status": "active",
            }, {"_id": 0})
            if tenant:
                result.append({**tenant, "role": membership["role"]})
        return result

    async def invite(self, actor_id: str, tenant_id: str, email: str, role: str, token_hash: str, expires_at: datetime) -> str:
        invitation_id = uuid4().hex
        async def create(session):
            member = await self.membership(actor_id, tenant_id, session=session)
            if member is None or member["role"] != "OWNER":
                raise AuthForbidden()
            await self.invitations.insert_one({
                "invitation_id": invitation_id, "tenant_id": tenant_id, "email": email,
                "role": role, "token_hash": token_hash, "expires_at": expires_at,
                "accepted_at": None, "invited_by": actor_id,
                "created_at": datetime.now(timezone.utc),
            }, session=session)
            await self.record("invitation.created", actor_id, tenant_id, session=session)
        await self.transaction(create)
        return invitation_id

    async def accept(self, user: dict, token_hash: str) -> dict:
        async def consume(session):
            invitation = await self.invitations.find_one_and_update({
                "token_hash": token_hash, "email": user["email"], "accepted_at": None,
                "expires_at": {"$gt": datetime.now(timezone.utc)},
            }, {"$set": {"accepted_at": datetime.now(timezone.utc),
                         "accepted_by": user["user_id"]}},
                return_document=ReturnDocument.AFTER, session=session)
            if invitation is None:
                raise InvitationRejected()
            tenant_id = invitation["tenant_id"]
            tenant = await self.tenants.find_one({
                "tenant_id": tenant_id, "status": "active",
            }, {"_id": 0}, session=session)
            if tenant is None:
                raise InvitationRejected()
            existing = await self.memberships.find_one({
                "tenant_id": tenant_id, "user_id": user["user_id"],
            }, session=session)
            # Accepting another invitation must not silently change an active role.
            role = existing["role"] if existing and existing["status"] == "active" else invitation["role"]
            await self.memberships.update_one({
                "tenant_id": tenant_id, "user_id": user["user_id"],
            }, {"$set": {"role": role, "status": "active"},
                "$setOnInsert": {"joined_at": datetime.now(timezone.utc)}},
                upsert=True, session=session)
            await self.record("invitation.accepted", user["user_id"], tenant_id, session=session)
            return {**tenant, "role": role}
        return await self.transaction(consume)

    async def members(self, user_id: str, tenant_id: str) -> list[dict]:
        member = await self.membership(user_id, tenant_id)
        if member is None or member["role"] != "OWNER":
            raise AuthForbidden()
        return await self.memberships.find(
            {"tenant_id": tenant_id}, {"_id": 0}
        ).sort("joined_at", 1).to_list(length=1000)
