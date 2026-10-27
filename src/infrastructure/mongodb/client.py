"""Per-process, per-event-loop async MongoDB connection lifecycle.

No connection is created on import. API and worker entry points own this context.
See ``docs/storage.md`` for consistency, timeouts, and deployment assumptions.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from src.core.config import Settings
from src.infrastructure.mongodb.indexes import ensure_document_indexes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def mongodb_database(settings: Settings) -> AsyncIterator[AsyncDatabase]:
    """Ping, ensure required indexes, yield a database, and always close the pool.

    Initialization failures abort startup with a safe error rather than a URI or
    server message. Database operations retain normal PyMongo error semantics.
    Majority concerns apply to this database's collections; there is no transaction
    spanning MongoDB and object storage. Each process/event loop needs its own pool.
    """
    client = None
    try:
        try:
            client = AsyncMongoClient(
                settings.mongodb_uri.get_secret_value(),
                appname="enterprise-rag",
                serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
                connectTimeoutMS=settings.mongodb_timeout_ms,
                timeoutMS=settings.mongodb_timeout_ms,
                maxPoolSize=settings.mongodb_max_pool_size,
                tz_aware=True,
                uuidRepresentation="standard",
            )
            database = client.get_database(
                settings.mongodb_database,
                write_concern=WriteConcern(w="majority"),
                read_concern=ReadConcern("majority"),
            )
            await client.admin.command("ping")
            await ensure_document_indexes(database)
        except (PyMongoError, ValueError):
            logger.error("MongoDB initialization failed")
            raise RuntimeError("MongoDB initialization failed") from None
        logger.info("MongoDB connection initialized")
        yield database
    finally:
        if client is not None:
            await client.close()
            logger.info("MongoDB connection closed")
