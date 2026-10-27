# Runtime configuration

`src/core/config.py` is the single runtime settings definition for the API and
workers. It validates configuration only: it does not open connections, configure
logging handlers, select model adapters, or check whether services are reachable.
Runtime policy files can live in this directory later. Never store secrets here.

## Setup and loading

From the repository root, install the package into your virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Fill in the required values in `.env`; the example intentionally contains no
credentials and is not a working deployment configuration. Start processes from
the repository root when using that file. `.env` is resolved from the current
working directory; parent directories are not searched. Production deployments
should inject environment variables through their secret/configuration mechanism.

Configure application logging first, then call `get_settings()` at startup:

```python
from src.core.config import get_settings

settings = get_settings()
# Only a service client should need the revealed credential:
# settings.mongodb_uri.get_secret_value()
```

No configuration loads at import time. The first successful call is cached for
the life of each process; API and worker processes have independent caches.
Settings are immutable. Restart processes after changing configuration.

For direct `Settings(...)` construction, precedence is constructor arguments,
environment variables, `.env`, then defaults. Variable matching is case
insensitive; use uppercase names for consistency. Empty environment and dotenv
values are ignored: optional values use their defaults, while required values
remain missing. Whitespace-only strings and secrets are rejected. Secrets are
preserved exactly rather than stripped.

Unknown dotenv entries and constructor arguments are rejected to catch typos.
Unrelated process environment variables are ignored by Pydantic Settings.
`Settings(_env_file=None, ...)` disables dotenv loading for isolated callers;
environment variables still apply.

## Variables

| Variable | Default / requirement | Meaning |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, or `production`; production forbids development invitation links |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; applied during API startup |
| `AUTH_MODE` | `external` | External JWKS verification or API-owned `local` accounts/sessions |
| `AUTH_PRIVATE_KEY_PATH` | Unset | Required PEM signing-key path in local mode; never committed |
| `AUTH_ACCESS_TOKEN_SECONDS` | `900` | Local access-token lifetime, 60–3600 seconds |
| `AUTH_REFRESH_TOKEN_SECONDS` | `2592000` | Absolute local refresh-session lifetime, 3600–7776000 seconds |
| `AUTH_REQUESTS_PER_MINUTE` | `30` | Local auth endpoint client budget, 1–1000 per fixed minute |
| `AUTH_INVITATION_SECONDS` | `86400` | Invitation lifetime, 300–604800 seconds |
| `AUTH_INVITATION_DEVELOPMENT_LINKS` | `false` | Return invitation token/link once to OWNER for local testing; forbidden in production |
| `AUTH_PUBLIC_BASE_URL` | `http://localhost:8000` | Configured base URL for development Swagger invitation links |
| `JWT_ISSUER` | Required | Exact trusted issuer claim value |
| `JWT_AUDIENCE` | Required | Audience identifying this API |
| `JWT_JWKS_URL` | Required in external mode | HTTPS signing-key endpoint; unused in local mode |
| `JWT_ALGORITHM` | `RS256` | Allowed signing algorithm: `RS256` or `ES256` |
| `JWT_TENANT_ID_CLAIM` | `tenant_id` | Top-level tenant identity claim name |
| `JWT_USER_ID_CLAIM` | `user_id` | Top-level user identity claim name; use `sub` if appropriate |
| `MONGODB_URI` | Required | `mongodb://` or `mongodb+srv://` URL; treated as a secret |
| `MONGODB_DATABASE` | `enterprise_rag` | Application database name |
| `MONGODB_TIMEOUT_MS` | `5000` | Driver operation, connection, and server-selection timeout; 100–120000 ms |
| `MONGODB_MAX_POOL_SIZE` | `50` | Maximum pool size per server per process; 1–1000 |
| `CHROMA_HOST` | Required | Hostname/IP only, without scheme, path, credentials, or port |
| `CHROMA_PORT` | `8000` | Integer from 1 through 65535 |
| `CHROMA_SSL` | `false` | Whether the future Chroma client uses TLS |
| `MINIO_ENDPOINT` | Required | Hostname/IP with optional port, e.g. `localhost:9000`; no URL scheme |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Required | Object-storage credentials |
| `MINIO_SECURE` | `true` | Whether the future MinIO client uses TLS; example overrides to `false` for local use |
| `MINIO_BUCKET` | `documents` | Bucket name; provider-specific naming rules remain the client's responsibility |
| `MINIO_TIMEOUT_SECONDS` | `30` | MinIO read timeout, 1–300 seconds; connect timeout is five seconds |
| `UPLOAD_MAX_BYTES` | `26214400` | Maximum PDF size, 1 byte–1 GiB; default 25 MiB |
| `REDIS_URL` | Required | `redis://` or `rediss://` URL; treated as a secret |
| `RABBITMQ_URL` | Required | `amqp://` or `amqps://` URL; treated as a secret |
| `LLM_PROVIDER`, `LLM_MODEL` | Required | Chat provider and model identifiers |
| `LLM_API_KEY` | Unset | Optional secret; local models may not require authentication |
| `LLM_BASE_URL` | Unset | Optional HTTP(S) endpoint for the model adapter |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL` | Required | Independent embedding provider and model identifiers |
| `EMBEDDING_API_KEY` | Unset | Optional embedding provider secret; independent of chat credentials |
| `EMBEDDING_BASE_URL` | Unset | Optional HTTP(S) embedding endpoint |
| `LANGFUSE_ENABLED` | `false` | Explicit tracing opt-in |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Unset | Both required when tracing is enabled |
| `LANGFUSE_BASE_URL` | Unset | Explicit HTTP(S) tracing destination; required when enabled |

Use `true` or `false` for boolean variables. URL credentials containing reserved
characters must be percent-encoded. Provider identifiers are deliberately not
restricted to an enum. Adapter-specific credentials, endpoint compatibility,
database/bucket naming, and connection readiness must be checked by their clients.
All required settings must currently be supplied by both API and worker processes.
See [JWT authentication](../docs/authentication.md) for identity-provider setup,
the protected-route dependency, and the API startup command.
See [local infrastructure](../deploy/docker/README.md) for host connection values;
the environment example uses Chroma port 8001 to leave port 8000 for FastAPI.

## Logging and secret handling

The module uses logger `src.core.config`. It emits a DEBUG load attempt, an INFO
success once per cached load, or an ERROR listing invalid field names. It never
logs configuration values or exception tracebacks. It does not install handlers
or call `basicConfig`; the process entry point owns logging configuration. See
[logging setup and tenant context](../docs/logging.md) for the startup sequence.

Credential fields and credential-bearing service URLs use `SecretStr` and are
excluded from the settings representation. String validation errors hide input
values. Do not log settings dumps, raw environment variables, or
`ValidationError.errors()`/`.json()`: structured errors can still contain original
input. For diagnostics use field locations and error types with
`errors(include_input=False, include_context=False)`. Unknown dotenv key names
appear in failure logs, so never place sensitive data in variable names.

HTTP endpoint overrides are not credential containers: keep API keys in their
dedicated secret variables, rather than URL userinfo or query parameters.

## Verification

The focused tests use the standard library and require no running services:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p test_config.py -v
```

Tests isolate the environment and disable dotenv loading where appropriate.
After changing environment variables in tests, clear the process cache with
`get_settings.cache_clear()` before and after use.

Settings loading follows the [Pydantic Settings documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
