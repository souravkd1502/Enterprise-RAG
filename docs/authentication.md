# JWT authentication and tenant context

This page describes the compatibility `AUTH_MODE=external` mode. For API-owned
signup/login, logout, and token refresh, see [local authentication](local-auth.md).
External mode consumes access tokens issued by your identity provider and leaves
registration/session management with that provider. Authentication yields an immutable
`TenantContext(tenant_id, user_id)`; authorization remains the responsibility of
services and repositories. Protected document requests also require an active
tenant and membership in MongoDB through AccessService; uploader-only document
permissions and tenant-scoped storage apply after membership authorization.

## Configure your issuer

Supply the following settings in `.env` or the process environment. No issuer or
audience is inferred from an incoming token, and there is no authentication bypass.

| Variable | Requirement |
| --- | --- |
| `JWT_ISSUER` | Required exact issuer claim value, including any trailing slash |
| `JWT_AUDIENCE` | Required audience identifying this API, not a frontend client |
| `JWT_JWKS_URL` | Required trusted HTTPS endpoint returning the issuer's public signing keys |
| `JWT_ALGORITHM` | `RS256` by default; alternatively `ES256`, chosen to match the issuer |
| `JWT_TENANT_ID_CLAIM` | `tenant_id` by default; a top-level claim name |
| `JWT_USER_ID_CLAIM` | `user_id` by default; set to `sub` if your issuer uses subject identity |

Tenant/user claim names must be distinct and cannot reuse protocol fields such
as `iss`, `aud`, or `exp`. Nested claim paths are not supported. Each external
token identifies one tenant. Provision the tenant and membership in MongoDB using
the exact issuer IDs; a valid JWT cannot create membership automatically.
Local mode supports workspace selection; see [local authentication](local-auth.md).

Use an issuer/audience/token policy intended for API access tokens. A valid
signature alone does not distinguish an ID token from an access token with the
same claims. Provider-specific token-type or scope policies can be added once
the provider contract is known. This implementation supports asymmetric JWKS
verification; shared-secret HS256 tokens are not supported.

All required infrastructure/model settings from the configuration guide are
still required at startup, even though their clients are not implemented yet.

## Verification and failure behavior

`TokenVerifier` checks the configured algorithm and a nonempty signing key ID
before selecting a key from the configured JWKS. It then verifies the signature,
issuer, audience, and required expiry and identity claims. Optional `nbf` and
`iat` claims are validated by PyJWT when present. There is no clock-skew allowance;
keep host clocks synchronized. Tokens are limited to 16 KiB.

Unverified header data is used only to reject disallowed algorithms and select
a key ID from the trusted key set. Token-supplied `jku`, `x5u`, or issuer values
never choose a network endpoint. JWKS fetches use a five-second timeout, a
five-minute key-set cache, and the library's unknown-key refresh behavior. Key
rotation depends on the provider retaining an overlap window. Removed keys can
remain usable until the cached key set expires; there is no token revocation
lookup. Restart processes if immediate cache invalidation is needed.

The verifier is synchronous. FastAPI runs the authentication dependency in its
thread pool so key retrieval does not block the event loop. Each API process
owns its verifier; no network request occurs merely by importing modules or
constructing the verifier. JWKS availability is not a startup readiness check.

| Condition | HTTP result |
| --- | --- |
| Missing/non-Bearer authentication | `401`, with `WWW-Authenticate: Bearer` |
| Malformed/expired token, wrong signature/issuer/audience, missing or invalid identity, unknown key ID | Generic `401`, with Bearer challenge |
| JWKS connection failure | Generic `503`; no token or remote exception details exposed |
| Valid identity lacks active tenant/membership | `403`; database authorization fails closed |
| Valid member lacks uploader permission on a document | `404` to avoid disclosing another uploader's document |

Configuration errors fail startup. Invalid-token diagnostics are DEBUG messages;
JWKS connectivity failures are ERROR messages. Neither logs decoded claims or
token contents. Other unexpected verifier failures remain server errors, not an
authentication bypass.

## Protecting a route

Every tenant-owned endpoint must explicitly depend on `get_tenant_context` and
pass that context into services. Document upload and metadata routes use this
dependency; do not add tenant-owned endpoints without it.

```python
from typing import Annotated
from fastapi import Depends
from src.api.dependencies import get_tenant_context
from src.core.tenancy import TenantContext

# Example signature for a future route; not an implemented document service.
async def list_documents(
    context: Annotated[TenantContext, Depends(get_tenant_context)],
):
    return await document_service.list_documents(context=context)
```

The dependency extracts `Authorization: Bearer <token>`, obtains verified identity,
and binds tenant/user identifiers plus a generated request ID for logging. The
async generator keeps logging context on the request task and restores it on
exit. Sync service calls made through FastAPI inherit the request context; new
background jobs need their own verified ownership and scope.

Tenant and user identifiers must be opaque, case-sensitive, nonempty strings of
at most 256 characters, without whitespace/control characters. No coercion or
normalization is performed. Headers, query parameters, bodies, logging extras,
and agent arguments cannot replace verified identity. Never read logging context
as the authorization source. Pass `TenantContext` explicitly into tenant-owned
MongoDB queries, vector filters, object access, cache keys, and job creation.

## Startup and health

Install runtime and test dependencies from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
```

After filling `.env`, start the application with Uvicorn:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --no-access-log
```

The lifespan loads configuration, initializes JSON application logging, connects
to MongoDB and ensures document indexes, initializes MinIO, and creates the JWT verifier.
Both stores must be available before startup completes; see [local infrastructure](../deploy/docker/README.md).
`/health` is intentionally public and returns
`{"status":"ok"}`. It checks process liveness only, not MongoDB, RabbitMQ, JWKS,
or other service readiness. FastAPI's documentation/schema endpoints are also
public; they expose route descriptions, not configuration or tenant data.

The CLI's server lifecycle logs use Uvicorn's own handlers. To have server logs
delegate to the application's JSON root logger too, launch programmatically:

```python
import uvicorn

uvicorn.run("src.api.main:app", log_config=None, access_log=False)
```

Access logs are disabled in both examples to avoid logging private URL/query data.
Application JSON startup logs begin when the lifespan configures root logging.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p 'test_*.py' -v
```

Tests generate temporary RSA keys and verify real signatures against a mocked
JWKS transport. They require no real identity provider or external services.
Coverage includes invalid signatures, expiry/issuer/audience/identity rejection,
algorithm restrictions, unknown keys, `sub` mapping, HTTP error handling,
concurrent tenant logging, spoofed headers/query parameters, and application
startup/shutdown. Live issuer connectivity and provider-specific claims still
need verification once your actual settings are supplied.

References: [PyJWT verification API](https://pyjwt.readthedocs.io/en/stable/api.html),
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), and
[FastAPI HTTP security](https://fastapi.tiangolo.com/reference/security/).
