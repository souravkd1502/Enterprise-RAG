# MongoDB document storage

The storage layer implements MongoDB pool lifecycle, document metadata, tenant
query boundaries, and MinIO original-file storage. See the [upload API](uploads.md)
for authenticated PDF upload, owner-only metadata access, and failure recovery.
Chroma/Redis/RabbitMQ clients and ingestion jobs remain unimplemented.
See [local infrastructure](../deploy/docker/README.md) to start the services.

Account, workspace, membership, invitation, session and audit collections are
documented in [authentication persistence](local-auth.md#mongodb-persistence-and-migration).
Tenant creation and OWNER membership use one MongoDB transaction. Data routes
validate current membership before applying their existing uploader permissions.

## Connection ownership and startup

`src/infrastructure/mongodb/client.py` provides the `mongodb_database(settings)`
async context manager. Each API/worker process and event loop owns its own
`AsyncMongoClient`; imports do not connect to a database. FastAPI lifespan enters
the context, pings MongoDB, ensures document indexes, and makes the database
available as `app.state.mongodb`. Application shutdown closes the pool and removes
the state reference. A connection or index failure prevents the API from serving.

The native PyMongo async driver is used. `MONGODB_TIMEOUT_MS` defaults to 5000
and bounds server selection, connection setup, and individual driver operations.
`MONGODB_MAX_POOL_SIZE` defaults to 50 per server per process; account for the
number of API/worker processes when sizing MongoDB capacity. UTC-aware BSON
datetimes and standard UUID representation are enabled. MongoDB stores datetimes
at millisecond precision, so a loaded timestamp may differ from the in-memory
creation timestamp by less than one millisecond.

Database collections use majority read and write concerns. Startup creates:

| Index | Purpose |
| --- | --- |
| Unique `(tenant_id, document_id)` | Identity uniqueness within a tenant |
| `(tenant_id, created_at descending, document_id descending)` | Stable bounded tenant listing |
| `(tenant_id, uploaded_by, created_at descending, document_id descending)` | Owner-only API listing before its limit |

Index creation is idempotent. Conflicting indexes or insufficient create-index
permissions fail startup; existing indexes are never dropped automatically.
Move index rollout to an explicit deployment migration before changing production
schemas or adopting a database account without index-management permissions.

Connection lifecycle logs contain fixed messages only. Startup driver failures
become a generic `RuntimeError`; service code should handle operation failures
at its boundary without returning driver text to API callers. Do not enable
third-party MongoDB command/body logging: it can expose stored metadata even if
application log messages exclude it. Exceptions must not be interpolated into
messages. `/health` remains process liveness; it is not a continuous DB readiness
or dependency health probe.

## Metadata and ownership

`DocumentMetadata` accepts only `filename`, `media_type`, and positive integer
`size_bytes`. It rejects extra fields such as `tenant_id`, `uploaded_by`, or
MongoDB operators. File name and content type are descriptive metadata; ingestion
must later inspect actual file content and enforce upload limits. File names
must never become trusted storage paths.

`Document` adds a UUID `document_id`, `tenant_id`, `uploaded_by`, lifecycle status,
and creation/update timestamps. These values are assigned by the repository using
verified identity. Domain models are immutable and do not import a storage client.
Creating metadata does not mean that a file has been uploaded or indexed.

## Repository contract

Construct a `DocumentRepository(database)` in the service layer and explicitly
pass `TenantContext` to every method. For example, a service receiving the context
from `get_tenant_context` can use:

```python
from src.domain.documents import DocumentMetadata
from src.infrastructure.mongodb.document_repository import DocumentRepository

repository = DocumentRepository(database)
document = await repository.create(
    context,
    DocumentMetadata(filename="report.pdf", media_type="application/pdf", size_bytes=1024),
)
loaded = await repository.get(context, document.document_id)
```

No route exposes this example yet. Convert a request's document identifier to a
UUID at the schema/API boundary. The repository rejects strings, `None`, and
operator dictionaries rather than using them as query fragments.

Every lookup and mutation filters on `tenant_id`; document operations also
filter on UUID identity. Missing and foreign-tenant documents both return `None`.
The repository does not query an unscoped ID to distinguish those cases. No method
accepts arbitrary query/update dictionaries or performs an upsert. Listing returns
at most 100 records, newest first, and currently has no continuation-page API.

Tenant filtering is an application-level boundary, not MongoDB row-level security.
Do not pass raw database handles to agent tools or external callers. Same-tenant
user/document permissions must be checked by an authorization service before
calling the repository. `uploaded_by` records attribution and is not an ACL.
Logging context never supplies identity for persistence.

## Lifecycle and deletion races

Metadata-only callers default to `pending`; the upload service starts records in
`uploading` and finalizes them only after MinIO confirms the original write.
Allowed status transitions are:

| Expected state | Allowed target |
| --- | --- |
| `uploading` | `pending`, `failed` |
| `pending` | `processing`, `failed` |
| `processing` | `ready`, `failed` |
| `failed` | `processing` |
| `deleting` | `deleted` |

`transition_status` performs an atomic compare-and-set: the filter includes the
expected status. A missing/foreign record or a stale expected state returns
`None`. This prevents a worker using an old state from restoring a document
after deletion has begun. It is not a complete ingestion lease, checkpoint, or
version-activation implementation.

`soft_delete` moves a visible document into `deleting`. Ordinary get/list calls
hide `uploading`, `deleting`, and `deleted` records. Repeated deletion returns
`None`; it never recreates a record. Physical deletion is deliberately absent.
A future cleanup worker will delete vectors, object bytes, manifests, and caches,
then mark the tombstone `deleted`. Retrieval must check authoritative active
version/status and authorization before returning source text. This increment
does not yet implement cross-store cleanup or version-safe search.

The local replica set supports transactions, but no job/outbox transaction exists
yet. Upload bytes and MongoDB metadata will still need partial-failure recovery;
they cannot participate in one atomic cross-store transaction.

## Verification

Unit tests cover ownership assignment, tenant-filtered boundaries, invalid IDs,
bounded listing, lifecycle restrictions, pool cleanup, and safe startup failure.
The integration suite in `tests/integration/test_mongodb_documents.py` exercises
real database behavior and is skipped unless `TEST_MONGODB_URI` is set. Follow
the deployment README to run it against the local replica set.

References: [PyMongo async client](https://pymongo.readthedocs.io/en/stable/api/pymongo/asynchronous/mongo_client.html)
and [async collection operations](https://pymongo.readthedocs.io/en/stable/api/pymongo/asynchronous/collection.html).
