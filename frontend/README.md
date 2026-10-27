# Lightweight account frontend

Plain HTML, CSS and JavaScript, served by Node.js built-ins. There are no npm
dependencies, build steps, UI frameworks, external fonts or CDN requests.
The three browser assets total about 17 KB before compression.

## Run both applications

Start MongoDB/MinIO using the existing Compose setup and configure the root
`.env` for `AUTH_MODE=local`; see [local authentication](../docs/local-auth.md).
The project needs its Python `.venv` and Node.js 22+ (Node LTS recommended).

From the repository root in Git Bash, Linux or macOS:

```sh
./run.sh
```

- Frontend: http://localhost:3000
- FastAPI Swagger: http://127.0.0.1:8000/docs
- Ctrl+C stops both processes. A startup failure also stops the other process.

Stop an already-running API before using the combined launcher. It reports an
occupied port and does not terminate unrelated processes. The script uses Node
from PATH or a portable runtime under the Git-ignored `.tools/node-*/` directory.
No `npm install` is required.

To choose different ports:

```sh
API_PORT=8002 FRONTEND_PORT=3001 ./run.sh
```

`./run.sh --reload` enables Python reload. Restart the launcher after editing
frontend files, which are read into memory at Node startup.

To run only the frontend against an existing API:

```sh
node frontend/server.mjs
```

With the project-local Windows runtime, use
`./.tools/node-v24.22.1-win-x64/node.exe frontend/server.mjs` from Git Bash.
The launcher detects that runtime automatically.

## Use the UI

1. Choose **Create account** and enter your name, email and a 15–128-character
   password. Signup creates the global account; it does not require a tenant.
2. Enter a workspace name and choose **Create workspace**. MongoDB creates the
   tenant and its OWNER membership transactionally.
3. Choose **Open** beside a workspace to select it. The UI marks it **Active**.
   Names can repeat; IDs shown below each name distinguish workspaces.
4. Use **Sign out** to revoke the backend session and remove the browser cookie.
5. Sign in again with the same email/password. Existing memberships are loaded.
   One workspace selects automatically; multiple workspaces require a selection.

The page supports small screens, keyboard controls, browser form validation,
loading/disabled controls and visible error messages. API errors never echo
submitted passwords. API connectivity errors allow retry. A failed logout leaves
the session available so server-side revocation can be retried.

## Request and session design

The browser calls only the Node server on its own origin. Node forwards a small,
explicit allowlist of auth/workspace operations to FastAPI; no CORS change is
needed. FastAPI remains the authority for identity, memberships and permissions.

| Browser endpoint | FastAPI operation |
| --- | --- |
| POST /api/signup | POST /auth/signup |
| POST /api/login | POST /auth/login |
| GET /api/session | GET /auth/me |
| POST /api/tenants | POST /tenants |
| POST /api/select-tenant | POST /auth/select-tenant, then GET /auth/me |
| POST /api/logout | POST /auth/logout |

Access and refresh JWTs stay in Node process memory. The browser receives only
an opaque random session identifier in an HttpOnly, SameSite=Lax cookie. Nothing
is stored in localStorage/sessionStorage. Account data uses textContent rather
than HTML interpolation.

Each session serializes refresh, selection and logout requests, including requests
from multiple tabs. Access refresh happens shortly before expiry. Ambiguous
refresh failures discard the Node session instead of replaying a potentially
consumed refresh token. Logout clears the cookie after successful API revocation.

The server enforces same-origin POST requests, bounded JSON input, backend
timeouts, no-store responses, a content security policy and an explicit static
file allowlist. Logs record fixed session/workspace outcomes and safe failure
status codes; they exclude credentials, cookie values, emails and API payloads.

Browser sessions are intentionally held in memory for this small local frontend.
Restarting Node signs browser users out; MongoDB accounts/workspaces remain.
Multiple Node instances would need shared session storage. FastAPI sees Node as
the client, so browsers share its configured local auth request budget.

## Configuration

Node reads process environment variables, not the root Python `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| API_PORT | 8000 | API port used by the combined launcher |
| FRONTEND_PORT | 3000 | Local frontend listening port |
| API_BASE_URL | http://127.0.0.1:8000 | FastAPI address; launcher derives it from API_PORT unless overridden |
| FRONTEND_ORIGIN | http://localhost:3000 | Browser origin; launcher derives it from FRONTEND_PORT |

For local testing, both localhost and 127.0.0.1 work on the configured frontend
port. An HTTPS FRONTEND_ORIGIN sets a Secure cookie; production mode requires
HTTPS. These options do not turn this local in-memory session server into a
production deployment.

## Verify

With Node on PATH:

```sh
cd frontend
npm test
```

Tests use only Node's built-in test runner. They check cookie/token boundaries,
cross-origin rejection, request limits, workspace selection, refresh concurrency,
backend revocation and retryable logout. The live HTTP test is skipped by default.

For a disposable MongoDB database and separate local test ports, from the root:

```sh
MONGODB_DATABASE=rag_test_frontend_manual API_PORT=18000 FRONTEND_PORT=13000 ./run.sh
# In another terminal:
TEST_FRONTEND_URL=http://localhost:13000 node --test frontend/test/live.test.mjs
```

The live test creates a random test account and two same-name workspaces. Use a
disposable database and remove it after testing; never point this test at an
existing user's database. The UI currently covers account/workspace access;
invitations, document upload and chat are outside this frontend's scope.
