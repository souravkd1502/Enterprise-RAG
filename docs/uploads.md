# PDF upload API

The document API stores original PDF bytes in MinIO and metadata in MongoDB.
All document endpoints require a verified JWT. Uploads are not yet queued for
ingestion; parsing, embeddings, download/delete endpoints, and document sharing
remain future work.

## Setup and usage

Follow [local infrastructure setup](../deploy/docker/README.md) and fill the root
`.env` with matching MinIO credentials, MongoDB connection details, and your
[JWT issuer settings](authentication.md). Install dependencies and start the API:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --no-access-log
```

Startup requires MongoDB and MinIO. It ensures MongoDB indexes and creates the
configured MinIO bucket if absent, tolerating the bucket-already-owned startup
race. No anonymous policy is installed; existing policies are not changed or
audited, so keep the bucket private. Startup failures close both connection pools.
The synchronous MinIO SDK runs in worker threads, not the request event loop.

| Setting | Default | Behavior |
| --- | --- | --- |
| `UPLOAD_MAX_BYTES` | `26214400` (25 MiB) | File limit; configurable from 1 byte through 1 GiB |
| `MINIO_TIMEOUT_SECONDS` | `30` | HTTP read timeout, 1–300 seconds |
| `MINIO_BUCKET` | `documents` | Private original-document bucket |

MinIO connections use a five-second connect timeout. HTTP retries are disabled
because ambiguous writes need service-level handling. A read timeout is not an
absolute deadline for an entire multipart upload. Each process owns its client
and HTTP pool; the pool is cleared on shutdown.

| Method and path | Behavior |
| --- | --- |
| `POST /documents` | Exactly one multipart field named `file`; return metadata with `201` |
| `GET /documents/{document_id}` | Visible metadata for a UUID owned by this uploader |
| `GET /documents?limit=50` | This uploader's visible documents, newest first; limit 1–100 |

With a real access token available in `API_TOKEN`:

```powershell
curl.exe -H "Authorization: Bearer $env:API_TOKEN" -F "file=@report.pdf;type=application/pdf" http://localhost:8000/documents
```

Responses contain `document_id`, `filename`, `media_type`, `size_bytes`, `status`,
`created_at`, and `updated_at`. They exclude authentication claims, bucket names,
object keys, credentials, and signed URLs. Successful uploads are `pending`:
bytes are stored, but no ingestion job is queued yet. Listing is bounded and has
no continuation-token interface.

## Identity and validation

Identity comes exclusively from verified JWT context. Multipart fields cannot
set ownership; extra fields are rejected. Headers and query parameters cannot
replace the authenticated tenant/user. Lookup returns the same `404` for missing
records, other tenants, or other users in the same tenant. Listing applies both
tenant and uploader filters before its limit. This initial owner-only rule does
not grant same-tenant sharing; future document ACLs must extend it explicitly.
Low-level repositories enforce tenants; trusted services enforce user permissions.

Authentication completes before multipart parsing. Streamed request bytes are
counted even without a trustworthy Content-Length. Requests are bounded by the
file limit plus 64 KiB of multipart overhead. Temporary files close after parsing
errors and after completed/failed operations. Multipart uploads spool to temporary
storage; the complete file is not read into application memory.

The service measures actual spooled length. Files must be nonempty, have a `.pdf`
extension, use `application/pdf` or `application/octet-stream`, and begin with
`%PDF-`. Stored content type is `application/pdf`. Names are reduced to basenames
and checked for length/control characters; they never become object paths.
These checks are a format gate, not full PDF validation, malware scanning, or
assurance that Docling can parse the document. Deployment ingress must also bound
request duration, concurrency, and aggregate temporary-disk use. Tenant quotas
are not implemented yet.

| Failure | HTTP result |
| --- | --- |
| Missing/invalid JWT | `401` with Bearer challenge |
| Invalid multipart shape or filename | `400` |
| Invalid UUID or listing limit | `422` |
| File or request over limit | `413` |
| Wrong extension/type or missing PDF signature | `415` |
| Missing or unauthorized metadata | `404` |
| Storage failure | Generic `503`, without raw storage errors |

## Persistence and recovery

1. Validate the PDF before writing either store.
2. Create a MongoDB intent with status `uploading`, a generated UUID, and trusted
   tenant/uploader identity. Normal get/list calls hide uploading intents.
3. Stream the original to MinIO.
4. Compare-and-set `uploading` to `pending`, then return `201`.

Paths are derived as `tenants/<SHA256 of tenant ID>/documents/<UUID hex>/original.pdf`.
The tenant hash bounds path length and avoids interpreting opaque IDs as paths;
it provides neither authorization nor encryption. The object adapter accepts
trusted context and UUIDs, never raw object paths. Its internal download-to-stream
helper releases HTTP responses even when writing fails; callers must check user
permissions first. No download API is exposed.

On an upload/finalization failure, compensation first attempts an atomic
`uploading → failed`. It removes the potentially written object only if that
transition succeeds. An ambiguous finalize might already have committed, so a
changed or unavailable metadata state causes deferred cleanup rather than deletion
of potentially valid bytes. Failed removal logs the document UUID and leaves the
durable intent for recovery. Cancellation attempts compensation under an AnyIO
shield, then propagates cancellation.

The stores do not share a transaction. Process termination, repeated cancellation,
or network/storage failure can leave stale hidden intents or orphaned objects.
Automatic reconciliation is not implemented. Inspect uploading/failed intents
using their tenant, UUID, timestamps, and deterministic object path. Never blindly
remove pending objects after ambiguous writes. Failed uploads must not enter
ingestion without confirming original bytes exist. Retries create a new UUID;
idempotency keys and deduplication are not yet implemented.

Logs include lifecycle outcomes and generated document UUIDs with scoped identity;
they exclude filenames, bytes, tokens, object paths, and raw storage errors.

## Verification

Unit tests require no services:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p 'test_*.py' -v
```

Live tests create/remove only generated test databases and buckets. Use the local
Compose credentials; never point these tests at production:

```powershell
$env:TEST_MONGODB_URI = 'mongodb://localhost:27017/?replicaSet=rs0&directConnection=true'
$env:TEST_MINIO_ENDPOINT = 'localhost:9000'
$env:TEST_MINIO_ACCESS_KEY = 'rag-local'
$env:TEST_MINIO_SECRET_KEY = 'local-minio-password'
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p 'test_*.py' -v
Remove-Item Env:TEST_MONGODB_URI, Env:TEST_MINIO_ENDPOINT, Env:TEST_MINIO_ACCESS_KEY, Env:TEST_MINIO_SECRET_KEY
```

Upload integration tests use real RSA-signed JWTs and mock only JWKS transport.
They exercise real HTTP routes, startup/shutdown, stored bytes, owner/tenant
isolation, and actual object cleanup after a simulated metadata failure.

References: [MinIO Python SDK](https://minio-py.min.io/) and
[FastAPI file handling](https://fastapi.tiangolo.com/tutorial/request-files/).
