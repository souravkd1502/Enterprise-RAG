"""Validated runtime settings shared by API and worker processes.

Call ``get_settings()`` during process startup, after configuring logging.
Importing this module does not read configuration or create service clients.
See ``configs/README.md`` for environment variables and loading behavior.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    UrlConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    """Immutable settings loaded from environment variables and a local .env.

    Field names map to uppercase environment variables without a prefix.
    Credentials and credential-bearing URLs are excluded from model repr and
    masked during serialization. Reveal them only when constructing a client.
    Validation checks configuration syntax, not service connectivity.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    jwt_issuer: NonEmptyString
    jwt_audience: NonEmptyString
    jwt_jwks_url: Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])] | None = None
    jwt_algorithm: Literal["RS256", "ES256"] = "RS256"
    jwt_tenant_id_claim: NonEmptyString = "tenant_id"
    jwt_user_id_claim: NonEmptyString = "user_id"
    auth_mode: Literal["external", "local"] = "external"
    auth_private_key_path: Path | None = Field(default=None, repr=False)
    auth_access_token_seconds: int = Field(default=900, ge=60, le=3600)
    auth_refresh_token_seconds: int = Field(default=2592000, ge=3600, le=7776000)
    auth_requests_per_minute: int = Field(default=30, ge=1, le=1000)
    auth_invitation_seconds: int = Field(default=86400, ge=300, le=604800)
    auth_invitation_development_links: bool = False
    auth_public_base_url: HttpUrl = HttpUrl("http://localhost:8000")

    mongodb_uri: SecretStr = Field(repr=False)
    mongodb_database: NonEmptyString = "enterprise_rag"
    mongodb_timeout_ms: int = Field(default=5000, ge=100, le=120000)
    mongodb_max_pool_size: int = Field(default=50, ge=1, le=1000)
    chroma_host: NonEmptyString
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    chroma_ssl: bool = False
    minio_endpoint: NonEmptyString
    minio_access_key: SecretStr = Field(repr=False)
    minio_secret_key: SecretStr = Field(repr=False)
    minio_secure: bool = True
    minio_bucket: NonEmptyString = "documents"
    minio_timeout_seconds: int = Field(default=30, ge=1, le=300)
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    redis_url: SecretStr = Field(repr=False)
    rabbitmq_url: SecretStr = Field(repr=False)

    llm_provider: NonEmptyString
    llm_model: NonEmptyString
    llm_api_key: SecretStr | None = Field(default=None, repr=False)
    llm_base_url: HttpUrl | None = Field(default=None, repr=False)
    embedding_provider: NonEmptyString
    embedding_model: NonEmptyString
    embedding_api_key: SecretStr | None = Field(default=None, repr=False)
    embedding_base_url: HttpUrl | None = Field(default=None, repr=False)

    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = Field(default=None, repr=False)
    langfuse_secret_key: SecretStr | None = Field(default=None, repr=False)
    langfuse_base_url: HttpUrl | None = Field(default=None, repr=False)

    @field_validator(
        "mongodb_uri",
        "redis_url",
        "rabbitmq_url",
        "minio_access_key",
        "minio_secret_key",
        "llm_api_key",
        "embedding_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
    )
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject blank credentials without changing their actual contents."""
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("mongodb_uri", "redis_url", "rabbitmq_url")
    @classmethod
    def validate_connection_url(
        cls, value: SecretStr, info: ValidationInfo
    ) -> SecretStr:
        """Check service URL schemes without including URLs in error messages."""
        schemes = {
            "mongodb_uri": {"mongodb", "mongodb+srv"},
            "redis_url": {"redis", "rediss"},
            "rabbitmq_url": {"amqp", "amqps"},
        }
        raw = value.get_secret_value()
        try:
            parsed = urlsplit(raw)
            valid = parsed.scheme in schemes[info.field_name] and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in raw):
            raise ValueError("must be a service URL with a supported scheme and host")
        return value

    @field_validator("chroma_host", "minio_endpoint")
    @classmethod
    def validate_endpoint(cls, value: str, info: ValidationInfo) -> str:
        """Accept bare hosts; only the MinIO endpoint may contain a port."""
        try:
            parsed = urlsplit("//" + value)
            port = parsed.port
            valid = bool(parsed.hostname) and not (
                parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
            )
            if info.field_name == "chroma_host" and port is not None:
                valid = False
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in value):
            raise ValueError(
                "must be a bare host; use separate TLS and Chroma port settings"
            )
        return value

    @model_validator(mode="after")
    def validate_identity_claim_names(self) -> Self:
        """Keep tenant and user identity distinct from JWT protocol fields."""
        reserved = {"exp", "iss", "aud", "iat", "nbf", "jti", "sid", "token_use", "auth_scope"}
        if (
            self.jwt_tenant_id_claim == self.jwt_user_id_claim
            or self.jwt_tenant_id_claim in reserved
            or self.jwt_user_id_claim in reserved
        ):
            raise ValueError(
                "Tenant and user claim names must be distinct identity claims"
            )
        return self

    @model_validator(mode="after")
    def validate_auth_mode(self) -> Self:
        """Require an explicit signing key for local auth or JWKS for external auth."""
        if self.app_env == "production" and self.auth_invitation_development_links:
            raise ValueError("Development invitation links cannot be enabled in production")
        if self.auth_mode == "external" and self.jwt_jwks_url is None:
            raise ValueError("External authentication requires JWT_JWKS_URL")
        if self.auth_mode == "local" and (
            self.auth_private_key_path is None or self.jwt_tenant_id_claim == "sub"
        ):
            raise ValueError("Local authentication requires a signing key path and a distinct tenant claim")
        return self

    @model_validator(mode="after")
    def validate_langfuse(self) -> Self:
        """Require explicit tracing credentials and destination when enabled."""
        if self.langfuse_enabled and not all(
            (
                self.langfuse_public_key,
                self.langfuse_secret_key,
                self.langfuse_base_url,
            )
        ):
            raise ValueError(
                "enabled Langfuse requires public key, secret key and base URL"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load once per process; fail startup on invalid configuration.

    Logs contain status and field names only. No handlers or global logging
    settings are installed here. Tests can call ``get_settings.cache_clear()``
    after changing environment variables; production changes require restart.
    """
    logger.debug("Loading application configuration")
    try:
        settings = Settings()
    except ValidationError as error:
        fields = sorted(
            {
                ".".join(map(str, item["loc"])) or "configuration"
                for item in error.errors(include_input=False, include_context=False)
            }
        )
        logger.error("Configuration validation failed; fields: %s", ", ".join(fields))
        raise
    logger.info("Application configuration loaded")
    return settings
