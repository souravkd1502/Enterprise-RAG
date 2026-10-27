# Accounts, workspaces and Swagger testing

Implements the [signup and tenant flow](signup-and-tenant-creation-flow.md): one
global user, multiple workspaces, OWNER/MEMBER memberships, email-bound invitations,
workspace selection and server-side session logout.

Swagger: **http://localhost:8000/docs**. OpenAPI: `/openapi.json`.
ReDoc: `/redoc`. These are FastAPI's built-in endpoints; no separate UI
server is needed. Documentation is public; API operations enforce authentication.

## Start locally

From the repository root in PowerShell:

```powershell
docker compose --env-file deploy/docker/.env.example -f deploy/docker/compose.yaml up -d
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
```

Copy the root `.env.example` to `.env` if missing. Keep all other example
defaults and set:

```dotenv
APP_ENV=development
AUTH_MODE=local
AUTH_PRIVATE_KEY_PATH=.secrets/auth-private.pem
AUTH_INVITATION_DEVELOPMENT_LINKS=true
AUTH_INVITATION_SECONDS=86400
AUTH_PUBLIC_BASE_URL=http://localhost:8000
JWT_ISSUER=http://localhost:8000
JWT_AUDIENCE=enterprise-rag-api
MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0&directConnection=true
MONGODB_DATABASE=enterprise_rag
MINIO_ACCESS_KEY=rag-local
MINIO_SECRET_KEY=local-minio-password
REDIS_URL=redis://localhost:6379/0
RABBITMQ_URL=amqp://rag-local:local-rabbitmq-password@localhost:5672/
LLM_PROVIDER=unconfigured
LLM_MODEL=not-configured
EMBEDDING_PROVIDER=unconfigured
EMBEDDING_MODEL=not-configured
```

These model names are placeholders for auth testing; auth does not call an LLM.
The Compose environment is separate from the root application environment.
`JWT_JWKS_URL` is unused locally. MongoDB must be a replica set to support
transactions; the supplied Compose setup initializes `rs0`.

Generate a key **once**, if the PEM does not exist, then run the server:

```powershell
New-Item -ItemType Directory -Force .secrets
.\.venv\Scripts\python.exe -c "from cryptography.hazmat.primitives.asymmetric import rsa; from cryptography.hazmat.primitives import serialization; key = rsa.generate_private_key(public_exponent=65537, key_size=3072); open('.secrets/auth-private.pem', 'xb').write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Exclusive creation refuses to overwrite a key. `.env` and `.secrets/` are ignored
by Git. All API processes must share the key and MongoDB database. RS256 requires
RSA >=2048 bits; ES256 requires P-256. Key replacement invalidates existing JWTs.
Encrypted PEMs and overlapping key rotation are not supported.

## Complete Swagger walkthrough

Use **Try it out**, edit JSON, and **Execute**. Keep the latest refresh token
privately; Swagger does not manage token refresh.

1. **Sign up:** `POST /auth/signup`:

   ```json
   {
     "email": "owner@example.com",
     "password": "A-long-local-test-password!",
     "name": "Workspace owner"
   }
   ```

   Returns 201, a global user_id, tokens, tenant_id null and an empty workspace list.
   Account-only tokens can onboard and accept invitations. Document access returns
   403 until a workspace is selected.

2. Click **Authorize** and paste **only** the access_token (without Bearer).
   Call `POST /tenants` with:

   ```json
   {"name": "Acme workspace"}
   ```

   Save tenant_id. The tenant and initial OWNER membership commit together.
   Workspace names are labels and can repeat.

3. **Select the workspace:** `POST /auth/select-tenant`:

   ```json
   {"tenant_id": "<tenant_id>", "refresh_token": "<current refresh_token>"}
   ```

   Save the new refresh token. Replace Swagger's **Authorize** access token with
   the new access_token. The previous account-only token no longer matches this
   session's selected workspace. `GET /auth/me` returns the profile/workspaces.

4. **Invite:** as OWNER, `POST /tenants/{tenant_id}/invitations`:

   ```json
   {"email": "member@example.com", "role": "MEMBER"}
   ```

   Returns invitation_token and invitation_link **once** to the OWNER.
   No email is sent. Copy the token for the recipient. The link opens Swagger
   with the token in the URL fragment; it does **not** automatically fill/submit
   a request. URL fragments are not sent to the server or HTTP access logs.

5. Sign up member@example.com with a name/password, omitting workspace_name.
   Existing users use `POST /auth/login`. Replace Swagger's authorization with
   the recipient's access token.

6. **Accept:** `POST /tenants/invitations/accept`:

   ```json
   {"token": "<invitation_token>"}
   ```

   The authenticated email must match. Acceptance creates membership and consumes
   the invitation atomically. Wrong-email, expired and reused tokens return the
   same 400. A second invitation preserves an already-active membership's role.

7. Select the joined workspace using the recipient's refresh token (step 3).
   Replace Swagger's authorization. The global user_id stays the same; role is
   MEMBER in this workspace. Members cannot invite or list members.
   Document routes also retain their existing uploader-only permissions.

8. Create or join another workspace to test multiple memberships. `GET /tenants`
   lists active workspaces. Login auto-selects a sole workspace; with multiple,
   it returns tenant_id null and tenant_selection_required true. Select one.
   Login optionally accepts tenant_id and checks active membership.

9. `POST /auth/refresh` accepts the current refresh_token and returns a replacement
   pair. Save both. Rotation preserves the selected tenant and absolute expiry.

10. `POST /auth/logout` accepts the latest refresh_token and returns 204.
    This session's access/refresh tokens stop working. Clear Swagger's **Authorize**
    manually; the server cannot clear a browser's in-memory bearer value.
    Other login sessions remain active. Login again to start a new session.

For faster owner setup, signup accepts optional workspace_name: user, tenant and
OWNER membership commit in one transaction, and the sole workspace auto-selects.
Signup rejects caller-supplied user_id, tenant_id and role.

## API contract

| Endpoint | Input / permission | Result |
| --- | --- | --- |
| POST /auth/signup | email, password, name, optional workspace_name | 201 account and tokens |
| POST /auth/login | email, password, optional tenant_id | Tokens and workspace choices |
| GET /auth/me | Account/tenant access Bearer | Global profile and active workspaces |
| POST /auth/select-tenant | tenant_id, current refresh_token | Rotated tokens for authorized tenant |
| POST /auth/refresh | current refresh_token | Replacement pair |
| POST /auth/logout | refresh_token | 204, session revoked |
| POST /tenants | Account/tenant access Bearer, name | 201 workspace and OWNER membership |
| GET /tenants | Account/tenant access Bearer | Active workspaces |
| POST /tenants/{tenant_id}/invitations | OWNER, email, OWNER/MEMBER role | 201 development invitation |
| POST /tenants/invitations/accept | Account/tenant access Bearer, token | Joined workspace and role |
| GET /tenants/{tenant_id}/members | OWNER | Up to 1,000 membership records |

IDs are random UUID hex strings; tenant inputs also accept hyphenated UUIDs.
Unknown fields are rejected. Sensitive validation failures do not echo input.
Auth/workspace responses use Cache-Control no-store; Swagger does not persist
authorization across reloads. No authentication cookies are set.

## MongoDB persistence and migration

The configured MONGODB_DATABASE stores:

| Collection | Information and invariant |
| --- | --- |
| auth_users | Unique global user_id and case-folded email, name, auth_provider, password_hash, active, created_at |
| tenants | Unique tenant_id, display name, status, created_at |
| memberships | Unique (tenant_id, user_id), role, status, joined_at |
| invitations | invitation_id, tenant_id, email, role, token_hash, expires_at, accepted_at, invited_by, accepted_by on consumption |
| auth_sessions | Session ID in _id, global user_id, nullable selected tenant_id, refresh_hash, expires_at, revoked, revoked_at |
| auth_rate_limits | Hashed client/account window keys, counts, TTL cleanup |
| audit_events | event_id, actor_id, nullable tenant_id, action, created_at |

Only salted Argon2id password hashes and SHA-256 token digests persist.
Invitation tokens contain 256 bits of randomness and expire after 24 hours by
default. Expiry is enforced in queries, independently of TTL cleanup. Invitations
and audit records have no automatic retention policy yet.

Transactions use snapshot reads and majority writes. Workspace+OWNER creation,
optional combined signup, invitation creation+audit, acceptance+membership+audit,
session creation+audit and revocation+audit are atomic. Refresh compares/replaces
the hash and workspace in one atomic write. Transaction callbacks contain database
work only, allowing safe MongoDB retries.

Legacy one-tenant local users migrate additively at startup: keep user/tenant IDs
and existing documents, create a Legacy workspace and OWNER membership, and mark
schema version 2. The legacy tenant_id field remains but is not authorization.
Migration is idempotent. Existing local JWTs require fresh login because the new
format requires explicit account/tenant scope. Duplicate/index conflicts abort
startup; no records or indexes are automatically dropped.

Inspect local data:

```powershell
docker compose --env-file deploy/docker/.env.example -f deploy/docker/compose.yaml exec mongodb mongosh enterprise_rag --quiet --eval 'db.tenants.find({}, {_id:0}).toArray()'
docker compose --env-file deploy/docker/.env.example -f deploy/docker/compose.yaml exec mongodb mongosh enterprise_rag --quiet --eval 'db.memberships.find({}, {_id:0}).toArray()'
```

## Security and operational behavior

Passwords contain 15-128 characters and are not trimmed/truncated. Argon2id uses
64 MiB, three iterations, parallelism one, and a four-operation thread limiter
per process. Missing accounts still perform a dummy verification. Missing/disabled
users and wrong passwords share a generic 401; duplicate signup returns generic 409.

Every local access checks signature, algorithm, key ID, issuer, audience, purpose,
expiry, active global user, unexpired/unrevoked session and matching selection.
Tenant data additionally requires a current active membership and active tenant.
Roles come from MongoDB. Browser-provided IDs cannot grant membership. Membership
removal blocks new data requests immediately; already-authorized work is not cancelled.

Access defaults to 15 minutes and refresh sessions to 30 days absolute. Refresh
does not extend expiry. Signed refresh replay revokes the entire session.
Serialize refresh/selection requests: concurrent refreshes have one winner and the
replay loser revokes its session. After ambiguous rotation/network failure, login
again instead of retrying old credentials. Logout is idempotent for malformed,
expired and already-revoked tokens.

Auth/workspace operations share a Mongo-backed client-IP budget (30/minute by
default); login also has a normalized-account budget (10/minute). A fixed window
permits boundary bursts. Limits fail closed on storage failure. Configure trusted
proxy handling and ingress request-size/time limits for shared deployments.

Logs contain constant outcomes, available request context, and no email, password,
token or hash payloads. Audit events cover accounts, session creation/revocation,
tenant creation and invitations. Broader document-access auditing, audit export,
retention and tamper protection remain separate work. Do not enable Mongo command
debugging or request/response-body logging.

## External SSO and remaining scope

AUTH_MODE=external still verifies issuer JWKS JWTs. Document access now also requires
a pre-provisioned active tenant/membership in MongoDB matching verified IDs.
JWT claims alone do not create membership. Local auth/workspace onboarding returns
404 in external mode. Provider-specific account provisioning, registration,
refresh/revocation and SSO logout need an IdP integration.

Development invitation delivery requires AUTH_INVITATION_DEVELOPMENT_LINKS=true;
production configuration rejects it. Disabled delivery returns 503 before creating
an invitation. SMTP, email verification, password recovery, MFA, member removal/role
editing, workspace settings/deletion, last-owner policy, member-list pagination and
tenant-wide document sharing remain future work. RAG ingestion and chat are still
unimplemented. A [lightweight Node.js frontend](../frontend/README.md)
now provides signup, tenant creation, workspace selection, sign-in and logout.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -v
$env:TEST_MONGODB_URI = 'mongodb://localhost:27017/?replicaSet=rs0&directConnection=true'
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_local_auth.py -v
Remove-Item Env:TEST_MONGODB_URI
```

Live tests use temporary keys and generated disposable databases. They cover
account onboarding, workspace selection, roles, invitation expiry/email/reuse/
concurrency, membership revocation, transaction rollback, migration and logout.

References: [MongoDB transactions](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/),
[FastAPI Swagger configuration](https://fastapi.tiangolo.com/how-to/configure-swagger-ui/),
[FastAPI HTTP security](https://fastapi.tiangolo.com/reference/security/).
