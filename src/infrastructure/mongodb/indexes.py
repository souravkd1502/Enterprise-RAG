"""Idempotent indexes for tenant-scoped document identity and bounded listing."""

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase


async def ensure_document_indexes(database: AsyncDatabase) -> None:
    """Fail startup if required indexes cannot be created; never drop indexes."""
    await database["documents"].create_indexes([
        IndexModel(
            [("tenant_id", ASCENDING), ("document_id", ASCENDING)],
            name="tenant_document_unique", unique=True,
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("created_at", DESCENDING), ("document_id", DESCENDING)],
            name="tenant_document_listing",
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("uploaded_by", ASCENDING), ("created_at", DESCENDING), ("document_id", DESCENDING)],
            name="tenant_uploader_document_listing",
        ),
    ])


async def ensure_auth_indexes(database: AsyncDatabase) -> None:
    """Local auth uniqueness and expiry cleanup; session expiry is checked in queries."""
    await database["auth_users"].create_indexes([
        IndexModel([("email", ASCENDING)], name="auth_email_unique", unique=True),
        IndexModel([("tenant_id", ASCENDING), ("user_id", ASCENDING)], name="auth_identity_unique", unique=True),
        IndexModel([("user_id", ASCENDING)], name="auth_user_id_unique", unique=True),
    ])
    await database["auth_sessions"].create_indexes([
        IndexModel([("expires_at", ASCENDING)], name="auth_session_expiry", expireAfterSeconds=0),
    ])
    await database["auth_rate_limits"].create_indexes([
        IndexModel([("expires_at", ASCENDING)], name="auth_limit_expiry", expireAfterSeconds=0),
    ])
    await database["tenants"].create_indexes([
        IndexModel([("tenant_id", ASCENDING)], name="tenant_id_unique", unique=True),
    ])
    await database["memberships"].create_indexes([
        IndexModel([("tenant_id", ASCENDING), ("user_id", ASCENDING)], name="membership_unique", unique=True),
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_memberships"),
    ])
    await database["invitations"].create_indexes([
        IndexModel([("token_hash", ASCENDING)], name="invitation_token_unique", unique=True),
        IndexModel([("tenant_id", ASCENDING), ("email", ASCENDING), ("expires_at", ASCENDING)], name="tenant_invitations"),
    ])
    await database["audit_events"].create_indexes([
        IndexModel([("tenant_id", ASCENDING), ("created_at", DESCENDING)], name="tenant_audit"),
    ])
