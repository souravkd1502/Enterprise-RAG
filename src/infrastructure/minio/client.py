"""Process-owned MinIO client and HTTP pool; all SDK calls stay off the event loop."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from anyio import to_thread
from minio import Minio
from minio.error import MinioException, S3Error
from urllib3 import PoolManager, Timeout
from urllib3.exceptions import HTTPError

from src.core.config import Settings
from src.infrastructure.minio.object_store import ObjectStore

logger = logging.getLogger(__name__)


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except S3Error as error:
            if error.code != "BucketAlreadyOwnedByYou":
                raise


@asynccontextmanager
async def minio_object_store(settings: Settings) -> AsyncIterator[ObjectStore]:
    """Ensure the bucket at startup and clear the owned connection pool on exit.

    No public policy is installed. Pre-existing buckets must also be private.
    Retries are disabled: ambiguous writes are handled by the upload service.
    Each worker process needs its own client/pool; do not share across processes.
    """
    pool = PoolManager(
        timeout=Timeout(connect=5, read=settings.minio_timeout_seconds),
        retries=False, cert_reqs="CERT_REQUIRED",
    )
    try:
        try:
            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key.get_secret_value(),
                secret_key=settings.minio_secret_key.get_secret_value(),
                secure=settings.minio_secure, http_client=pool,
            )
            await to_thread.run_sync(_ensure_bucket, client, settings.minio_bucket)
        except (MinioException, HTTPError, OSError, ValueError):
            logger.error("MinIO initialization failed")
            raise RuntimeError("MinIO initialization failed") from None
        logger.info("MinIO connection initialized")
        yield ObjectStore(client, settings.minio_bucket)
    finally:
        pool.clear()
        logger.info("MinIO connection pool closed")
