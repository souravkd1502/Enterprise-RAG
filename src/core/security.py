"""External JWT verification and explicitly enabled local asymmetric token issuance.

Tokens cannot choose their issuer, signing keys, or allowed algorithm.
See ``docs/authentication.md`` and ``docs/local-auth.md`` for trust boundaries.
"""

import time
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID, uuid4

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError

from src.core.config import Settings
from src.core.tenancy import TenantContext


class TokenVerifier:
    """Reusable synchronous verifier with bounded JWKS fetches and key-set cache.

    Call from a thread pool in async applications. PyJWKClient caches the JWKS
    for five minutes and refreshes for unknown key IDs. Individual signing keys
    are not cached indefinitely, so removed keys expire with the key set.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks = PyJWKClient(
            str(settings.jwt_jwks_url),
            cache_jwk_set=True,
            cache_keys=False,
            lifespan=300,
            timeout=5,
        )

    def verify(self, token: str) -> TenantContext:
        """Return identity only after signature and required claims validate.

        Invalid tokens raise PyJWT errors. JWKS transport failures remain
        distinguishable so HTTP callers can return 503 rather than 401.
        Neither tokens nor decoded claims are logged or retained.
        """
        if len(token) > 16384:
            raise InvalidTokenError("Token exceeds maximum size")
        header = jwt.get_unverified_header(token)
        if header.get("alg") != self._settings.jwt_algorithm:
            raise InvalidTokenError("Unsupported signing algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise InvalidTokenError("Missing or invalid signing key identifier")
        signing_key = self._jwks.get_signing_key(kid)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[self._settings.jwt_algorithm],
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            options={
                "require": [
                    "exp",
                    "iss",
                    "aud",
                    self._settings.jwt_tenant_id_claim,
                    self._settings.jwt_user_id_claim,
                ]
            },
        )
        try:
            return TenantContext(
                tenant_id=claims[self._settings.jwt_tenant_id_claim],
                user_id=claims[self._settings.jwt_user_id_claim],
            )
        except ValueError:
            raise InvalidTokenError("Invalid identity claims") from None


@dataclass(frozen=True)
class VerifiedLocalToken:
    context: TenantContext | None
    session_id: str
    expires_at: int
    user_id: str


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    refresh_expires_in: int
    tenant_id: str | None
    user_id: str
    role: str | None = None
    workspaces: tuple[dict, ...] = ()
    tenant_selection_required: bool = False


class LocalTokenCodec:
    """One process-owned signing key; cryptographic checks alone do not grant access.

    AuthService must also verify active user/session state for every access token.
    A key rotation currently invalidates all existing local tokens; no old-key ring.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        try:
            key = serialization.load_pem_private_key(
                settings.auth_private_key_path.read_bytes(), password=None
            )
            compatible = (
                settings.jwt_algorithm == "RS256"
                and isinstance(key, rsa.RSAPrivateKey)
                and key.key_size >= 2048
            ) or (
                settings.jwt_algorithm == "ES256"
                and isinstance(key, ec.EllipticCurvePrivateKey)
                and isinstance(key.curve, ec.SECP256R1)
            )
            if not compatible:
                raise ValueError("Incompatible signing key")
        except (OSError, ValueError, TypeError, AttributeError, UnsupportedAlgorithm):
            raise RuntimeError(
                "Local authentication signing key is missing or invalid"
            ) from None
        self._private_key = key
        self._public_key = key.public_key()
        public_der = self._public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self._kid = sha256(public_der).hexdigest()[:32]

    def issue(
        self, context: TenantContext, session_id: str, refresh_expires_at: int
    ) -> IssuedTokens:
        return self.issue_identity(context.user_id, context.tenant_id, session_id, refresh_expires_at)

    def issue_identity(
        self, user_id: str, tenant_id: str | None, session_id: str, refresh_expires_at: int
    ) -> IssuedTokens:
        """Account tokens can onboard and select a tenant, but cannot access tenant data."""
        now = int(time.time())
        access_expiry = min(
            now + self._settings.auth_access_token_seconds, refresh_expires_at
        )

        def encode(use: str, expiry: int) -> str:
            return jwt.encode(
                {
                    "iss": self._settings.jwt_issuer,
                    "aud": self._settings.jwt_audience,
                    "sub": user_id,
                    "iat": now,
                    "nbf": now,
                    "exp": expiry,
                    "jti": uuid4().hex,
                    "sid": session_id,
                    "token_use": use,
                    "auth_scope": "tenant" if tenant_id is not None else "account",
                    self._settings.jwt_tenant_id_claim: tenant_id,
                    self._settings.jwt_user_id_claim: user_id,
                },
                self._private_key,
                algorithm=self._settings.jwt_algorithm,
                headers={"kid": self._kid, "typ": f"{use}+jwt"},
            )

        return IssuedTokens(
            encode("access", access_expiry),
            encode("refresh", refresh_expires_at),
            max(0, access_expiry - now),
            max(0, refresh_expires_at - now),
            tenant_id,
            user_id,
        )

    def decode(self, token: str, use: str) -> VerifiedLocalToken:
        """Verify signature, purpose, issuer/audience, times, session, and identity."""
        if len(token) > 16384 or use not in {"access", "refresh"}:
            raise InvalidTokenError("Invalid token")
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != self._settings.jwt_algorithm
            or header.get("kid") != self._kid
            or header.get("typ") != f"{use}+jwt"
        ):
            raise InvalidTokenError("Invalid token header")
        claims = jwt.decode(
            token,
            self._public_key,
            algorithms=[self._settings.jwt_algorithm],
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            options={
                "require": [
                    "exp",
                    "iat",
                    "nbf",
                    "iss",
                    "aud",
                    "sub",
                    "jti",
                    "sid",
                    "token_use",
                    "auth_scope",
                    self._settings.jwt_user_id_claim,
                ]
            },
        )
        try:
            user_id = claims[self._settings.jwt_user_id_claim]
            tenant_id = claims.get(self._settings.jwt_tenant_id_claim)
            if not isinstance(user_id, str) or not user_id or len(user_id) > 256:
                raise ValueError("Invalid identity")
            TenantContext("account", user_id)  # Apply the same visible-ID rules to account tokens.
            scope = claims["auth_scope"]
            if scope not in {"account", "tenant"} or (scope == "tenant") != (tenant_id is not None):
                raise ValueError("Invalid scope")
            context = TenantContext(tenant_id, user_id) if tenant_id is not None else None
            sid = claims["sid"]
            if (
                claims["token_use"] != use
                or claims["sub"] != user_id
                or not isinstance(sid, str)
                or UUID(sid).hex != sid
                or type(claims["exp"]) is not int
            ):
                raise ValueError("Invalid token claims")
        except (ValueError, TypeError, AttributeError):
            raise InvalidTokenError("Invalid token claims") from None
        return VerifiedLocalToken(context, sid, claims["exp"], user_id)
