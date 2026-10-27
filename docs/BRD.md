# Business Requirements Document: Enterprise RAG

| Control | Value |
| --- | --- |
| Version | 1.1 |
| Status | Draft for stakeholder review; not an approved delivery commitment |
| Baseline date | 2026-10-28 (Asia/Calcutta) |
| Product | Multi-tenant, document-grounded question-answering API |
| Business owner / approver | To be assigned |
| Evidence | Repository code, existing roadmap, architecture and implementation guides |
| Remaining scope | 75 tracked functional features: 58 not implemented, 17 partial |

## 1. Executive summary

The product will let authenticated users ingest authorized enterprise documents and
ask questions that return evidence-grounded answers with resolvable source/page
citations. Tenant isolation, document permissions, reliable asynchronous processing,
quality measurement and operational recovery are business requirements throughout
the workflow.

The current system implements identity/session foundations, PDF upload and storage,
metadata access, logging and local infrastructure. It does not yet parse/index
uploaded documents or answer questions. An upload reaching `pending` means original
bytes and metadata were stored; it does not mean ingestion was queued or content is
searchable.

This BRD specifies the remaining work. It is not a claim of production readiness,
a delivery estimate, or a guarantee of model answer accuracy. The companion
[complete feature checklist](remaining-features.md) uses the same requirement IDs.

## 2. Business problem and objectives

Enterprise knowledge is difficult to search when it is spread across documents and
when ordinary model responses cannot show the evidence or respect existing access
boundaries. The system must make authorized knowledge usable without introducing
cross-tenant disclosure or untraceable model output.

| Objective | Business result | Evidence of success |
| --- | --- | --- |
| BO-01 Discover knowledge | Users find relevant information from their authorized documents | Approved retrieval/answer evaluation baseline and user acceptance scenarios |
| BO-02 Trust answers | Answers include verifiable citations or explicitly abstain | Citation correctness and insufficient-evidence tests meet approved thresholds |
| BO-03 Protect access | Identity and document permissions apply across every store and tool | No cross-tenant/unauthorized-source disclosure in required isolation tests |
| BO-04 Operate reliably | Interrupted processing can be observed and recovered without duplicate searchable content | Duplicate-delivery, crash, deletion and recovery tests pass |
| BO-05 Control quality/cost | Teams can measure answer quality, latency, failures and model consumption | Langfuse/metrics and versioned Ragas reports support release decisions |
| BO-06 Support teams | Authorized tenant administrators can manage membership and document sharing | Approved role/ACL matrix and tenant-management acceptance scenarios |

## 3. Stakeholders and users

| Stakeholder/persona | Responsibilities / needs |
| --- | --- |
| Business sponsor / product owner | Approve scope, priorities, success thresholds and rollout decisions |
| Document contributor | Upload/manage permitted content and monitor processing outcomes |
| Knowledge consumer | Ask questions and inspect authorized evidence/citations |
| Tenant administrator | Manage membership, role assignments and document access |
| Platform operator | Deploy, monitor, diagnose, recover, back up and restore the system |
| Security/privacy owner | Approve access, identity, content-export, retention and audit policies |
| Quality/evaluation owner | Curate datasets, define metrics, review failures and approve regression gates |

These are intended personas. OWNER/MEMBER onboarding permissions are implemented;
broader role administration and document sharing remain future work. No stakeholder names, delivery dates or staffing assumptions were supplied.

## 4. Current-state baseline and evidence

| Implemented area | Current behavior / boundary | Repository evidence |
| --- | --- | --- |
| Identity | External JWT verification; optional local signup/login/logout/refresh with Argon2id, session state and replay revocation | [security](../src/core/security.py), [auth service](../src/services/auth_service.py), [local auth guide](local-auth.md) |
| Tenant context | Verified identity plus active MongoDB membership; global local accounts, separate transactional workspaces and OWNER/MEMBER roles | [tenancy](../src/core/tenancy.py), [API dependencies](../src/api/dependencies.py) |
| Document API | PDF upload, metadata lookup and bounded first-page listing; service access is uploader-only | [routes](../src/api/routes/documents.py), [service](../src/services/document_service.py), [upload guide](uploads.md) |
| Persistence | MinIO originals, MongoDB metadata/indexes, guarded lifecycle state changes and soft-delete primitives | [object store](../src/infrastructure/minio/object_store.py), [repository](../src/infrastructure/mongodb/document_repository.py), [storage guide](storage.md) |
| Recovery foundation | Upload intents and best-effort compensation; no automatic orphan/stale-intent reconciler | [document service](../src/services/document_service.py) |
| Logging | JSON stdout, scoped identifiers and defensive secret masking; no Langfuse trace implementation | [logging](../src/core/logging.py), [logging guide](logging.md) |
| Operations | Local Compose services and API liveness; no production API/worker image or deployment contract | [Compose guide](../deploy/docker/README.md), [health route](../src/api/routes/health.py) |
| Existing validation | Unit/integration suites cover implemented auth/storage boundaries; RAG quality has no implemented runner | [unit tests](../tests/unit), [integration tests](../tests/integration), [eval scaffold](../evals/README.md) |

Many RAG modules remain placeholders. A module count is not a feature count:
features span multiple modules. Auth/storage tests cover implemented boundaries;
they do not establish RAG quality or production readiness. See the current
[local auth guide](local-auth.md) for implementation scope and verification commands.

## 5. Scope and counting rules

A tracked feature is one named, independently reviewable functional delivery item
with acceptance criteria below. Subtasks, classes, configuration fields, test
cases and nonfunctional requirements are not counted as additional features.
Completed foundations are excluded; unfinished extensions to those foundations
are counted once as partial. Some features are prerequisites for others; the
count is not an effort estimate and must not be turned into a completion percentage.

The 75-item inventory includes the original roadmap, documented implementation
gaps and explicitly identified enterprise/local-account extensions. P2 entries
are conditional options, not implied commitments. Local-account enhancements apply
when local identity is used; an external provider may fulfill parts of that scope,
but the required behavior/policy must still be verified for the selected provider.

| Priority | Count | Proposed meaning |
| --- | ---: | --- |
| P0 | 37 | Core document-to-answer workflow and controlled-pilot release requirements |
| P1 | 26 | Enterprise completion, team support and operational/account hardening |
| P2 | 12 | Optional/decision-dependent enhancements requiring explicit scope approval |
| **Total** | **75** | **58 not implemented + 17 partial** |

### In scope

- API-first document ingestion, reliable workers, search, grounded answers and citations.
- Tenant/user access across storage, retrieval, tools, conversations, caches and traces.
- The required stack and independently configurable chat/embedding models.
- Document lifecycle, evaluation, observability and operating/recovery capabilities.
- Local identity completion only where local authentication is selected.

### Not assumed in this scope

- A full RAG web/mobile client, billing, payment processing or public plugin marketplace.
  A lightweight Node.js account/workspace UI is implemented; see the
  [frontend guide](../frontend/README.md).
- Custom model training/fine-tuning or a particular LLM vendor.
- Unapproved source connectors, unrestricted web crawling or arbitrary agent actions.
- A specific regulatory certification, geographic residency promise, availability SLA
  or fully isolated per-tenant deployment without an explicit business decision.
- A promise that all optional features or Kubernetes are necessary for the first pilot.

## 6. Required technology responsibilities

| Technology | Required responsibility / decision boundary |
| --- | --- |
| FastAPI | Authenticated API contracts, request validation, dependency lifecycle and streaming |
| LangChain | Approved chat/embedding/retriever integrations behind service/adaptor contracts |
| LangGraph | Explicit query execution state, routing and bounded tool/model execution |
| Docling | Document conversion with an approved format/OCR policy and provenance preservation |
| ChromaDB | Tenant-scoped embeddings/chunk retrieval; never the authority for user membership |
| MinIO | Private original files and approved derived artifacts |
| MongoDB | Authoritative metadata, versions, jobs/outbox, conversations, permissions and local identity/session records |
| Redis | Expiring caches and general RAG quota/rate counters; not authoritative job state |
| RabbitMQ | Durable job delivery, retry and dead-letter routing |
| Langfuse | Approved trace/evaluation visibility and model consumption correlation |
| Ragas | Offline versioned retrieval/answer evaluation |
| LLM provider | Selected later; chat and embedding choices remain independent |

Local containers exist for infrastructure services, but ChromaDB, RabbitMQ and
Redis application adapters are still missing. LangChain, LangGraph, Docling,
Langfuse and Ragas runtime integrations are not yet implemented.

## 7. Target business journeys

### 7.1 Identity and tenant access

A user authenticates through the selected local/external mode. The service derives
trusted tenant/user identity; requests cannot replace it. Team membership and
sharing are explicit grants rather than a tenant ID supplied by a caller. Local
self-signup creates a global account and optionally a workspace. Authenticated
users can create workspaces or accept email-bound invitations, then select an active
membership. Development invitation links are returned once in Swagger; production
delivery and provider-specific SSO provisioning remain future work.

### 7.2 Document to searchable knowledge

An authorized upload stores original bytes and metadata. An ingestion submission
creates durable job/publication intent, publishes a small identifier-only queue
message, and returns a trackable job. A worker validates ownership, parses,
normalizes, chunks and embeds, then commits vectors and a manifest. Searchability
is enabled only for a completed active index/version. Retries and restarts do not
produce duplicate logical results.

### 7.3 Question to cited answer

An authenticated question enters a bounded graph. Retrieval applies current tenant,
owner/ACL and version rules, selects evidence and fits a context budget. Generation
uses the selected provider and versioned prompt. The response supplies valid
source/page citations or an explicit insufficient-evidence outcome. All evidence
returned to the caller remains subject to current authorization.

### 7.4 Replace, revoke or delete content

An authorized lifecycle change makes stale or revoked content unavailable at the
serving boundary. Replacement indexes activate safely; deletion hides content
before asynchronous cleanup. Associated objects, vectors, manifests, caches and
relevant derived records are handled according to the approved policy. Operators
can observe and reconcile partial failures.

### 7.5 Evaluate and operate

Reviewed questions and expected evidence drive reproducible evaluations. Operators
use redacted traces, metrics and job state to diagnose failures and control cost.
Releases compare against approved baselines and support documented rollback,
replay, reconciliation and recovery procedures.

## 8. Functional requirements: complete remaining inventory

Every row below is unfinished. Partial describes an existing foundation, not a
completed requirement. The implementation trace identifies likely ownership; it
is not a directive to create unnecessary modules or a commitment to that exact API.

### Document ingestion

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-001 | Asynchronous ingestion submission and job tracking | P0 | Not implemented | Submit an authorized stored PDF once and expose tenant/user-scoped job state and safe failure information. | `src/services/ingestion_service.py`; `src/api/routes/jobs.py` |
| FR-002 | Docling PDF parsing and OCR policy | P0 | Not implemented | Convert text PDFs into structured content; classify scanned, encrypted, corrupt and unsupported files with explicit outcomes; apply an agreed OCR policy. | `src/ingestion/parsing/docling_parser.py` |
| FR-003 | Additional document formats | P2 | Not implemented | Upload and parse DOCX and an approved format allowlist with format-specific validation and regression fixtures. | `src/ingestion/connectors`; `src/ingestion/parsing` |
| FR-004 | Content normalization and source provenance | P0 | Not implemented | Preserve document/version identifiers and page, section and table locators through normalized content. | `src/ingestion/parsing/normalization.py`; `src/ingestion/processing/metadata.py` |
| FR-005 | Structure-aware chunking | P0 | Not implemented | Create reproducible chunks with configurable size/overlap and stable source locators; test tables and section boundaries. | `src/ingestion/processing/chunking.py` |
| FR-006 | Embedding execution and batching | P0 | Not implemented | Embed chunks in bounded batches, persist embedding configuration, and handle transient and permanent provider failures. | `src/ingestion/processing/embeddings.py` |
| FR-007 | Chroma indexing and chunk manifests | P0 | Not implemented | Write tenant-scoped chunks and embeddings, record a durable manifest, and prevent incomplete indexes from becoming searchable. | `src/ingestion/indexing/index_writer.py`; `src/infrastructure/chromadb` |
| FR-008 | Approved web-source ingestion | P2 | Not implemented | Ingest only allowlisted sources with ownership, size, URL/network and crawl-boundary controls; preserve source provenance. | `src/ingestion/connectors/web.py`; `src/ingestion/connectors/registry.py` |

### Queue and worker reliability

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-009 | Transactional job/outbox intent and dispatch | P0 | Not implemented | Persist job plus publication intent atomically and recover interrupted dispatch without silently losing work. | `src/infrastructure/mongodb/outbox_repository.py`; `src/infrastructure/mongodb/job_repository.py` |
| FR-010 | RabbitMQ connection, topology and confirmed publishing | P0 | Not implemented | Declare durable delivery/retry/dead-letter topology and publish identifier-only messages with publisher confirmation. | `src/infrastructure/rabbitmq` |
| FR-011 | Ingestion worker consumption and acknowledgements | P0 | Not implemented | Validate job ownership, consume with bounded prefetch/concurrency and acknowledge only after durable stage state. | `src/workers/ingestion_worker.py`; `src/workers/handlers.py` |
| FR-012 | Bounded retries and dead-letter handling | P0 | Not implemented | Retry eligible failures with backoff, stop poison-message loops and retain terminal failures for investigation. | `src/workers/retry_policy.py`; `src/infrastructure/rabbitmq/topology.py` |
| FR-013 | Idempotent ingestion and deterministic writes | P0 | Not implemented | Delivering the same job more than once produces one logical result without duplicate chunks or searchable versions. | `src/ingestion/idempotency.py` |
| FR-014 | Durable stage checkpoints and resume | P1 | Not implemented | Resume interrupted jobs from verified committed stages without trusting stale or cross-tenant checkpoints. | `src/ingestion/checkpoints.py` |
| FR-015 | Job cancellation | P1 | Not implemented | Only an authorized caller can cancel a job; workers honor cancellation at safe boundaries and leave recoverable state. | `src/domain/jobs.py`; `src/workers/handlers.py` |

### Document lifecycle

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-016 | Upload request idempotency | P1 | Not implemented | Retrying the same authorized idempotency key does not create another upload; mismatched payload reuse is rejected. | `src/services/document_service.py`; `src/api/routes/documents.py` |
| FR-017 | Tenant-scoped content deduplication | P1 | Not implemented | Detect matching content hashes within authorized tenant scope without disclosing another tenant's documents. | `src/domain/documents.py`; `src/services/document_service.py` |
| FR-018 | Document version history and safe replacement | P1 | Partial | Persist versions and atomically select an active completed version; retrieval rejects superseded or incomplete versions. Current lifecycle status is not version management. | `src/domain/documents.py`; `src/ingestion/indexing/version_activation.py` |
| FR-019 | Reindexing and index-policy migration | P1 | Not implemented | Rebuild for model/dimension/chunker changes without corrupting the active index; support validation and safe cutover. | `src/ingestion/indexing`; `scripts` |
| FR-020 | Authorized deletion and cross-store cleanup | P0 | Partial | Provide a delete API, hide content immediately and reliably remove related objects, vectors, manifests and caches. Repository tombstones and an object remove helper already exist. | `src/services/deletion_service.py`; `src/ingestion/indexing/cleanup.py` |
| FR-021 | Automatic stale-upload and orphan reconciliation | P0 | Partial | Recover stale uploading/failed intents and orphaned storage safely; never delete a possibly committed pending object. Current compensation/logging is only a foundation. | `src/workers/maintenance_worker.py`; `src/services/document_service.py` |
| FR-022 | Document retention and purge schedules | P1 | Not implemented | Apply approved document/derived-data retention and purge policies with tenant boundaries and recorded outcomes. | `src/workers/maintenance_worker.py`; `src/ingestion/indexing/cleanup.py` |
| FR-023 | Authorized original-document download API | P1 | Partial | Expose original bytes only after current owner/ACL checks and release resources on disconnect. An internal download-to-stream helper already exists. | `src/api/routes/documents.py`; `src/infrastructure/minio/object_store.py` |
| FR-024 | Cursor pagination for document metadata | P1 | Partial | Traverse authorized metadata in stable bounded pages with no skipped/duplicated records under the documented consistency model. Current listing returns only a bounded first page. | `src/api/routes/documents.py`; `src/infrastructure/mongodb/document_repository.py` |

### Models and provider controls

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-025 | LangChain chat-model adapters and factory | P0 | Not implemented | Invoke at least one approved provider through a configurable LangChain chat adapter; keep provider-specific code behind the factory. | `src/infrastructure/llm/chat_models.py`; `src/infrastructure/llm/factory.py` |
| FR-026 | Independent embedding-model adapters | P0 | Not implemented | Select and validate embedding provider/model/dimension independently from the chat model and record the index compatibility contract. | `src/infrastructure/llm/embedding_models.py` |
| FR-027 | Provider timeouts, retry policy and concurrency controls | P0 | Not implemented | Bound chat/embedding operations, classify failures and avoid unbounded retries or concurrency; any fallback requires explicit compatibility policy. | `src/infrastructure/llm`; `configs` |

### Retrieval

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-028 | Chroma vector retrieval | P0 | Not implemented | Return relevant indexed chunks for an authorized query with configured top-k and reproducible retrieval inputs. | `src/retrieval/strategies/vector.py`; `src/infrastructure/chromadb/vector_store.py` |
| FR-029 | Retrieval authorization and active-version enforcement | P0 | Partial | Apply tenant and owner/ACL filters before retrieval and recheck current version/status before exposing source text. Existing metadata isolation does not cover vector search. | `src/retrieval/filters.py`; `src/services/access_service.py` |
| FR-030 | Lexical search index and retrieval | P2 | Not implemented | Provision a suitable lexical index and evaluate its retrieval independently; do not treat a placeholder or unindexed scan as lexical search. | `src/retrieval/strategies/lexical.py` |
| FR-031 | Hybrid rank fusion | P2 | Not implemented | Fuse vector/lexical rankings reproducibly and demonstrate improvement against the approved evaluation baseline. | `src/retrieval/strategies/hybrid.py` |
| FR-032 | Reranking | P2 | Not implemented | Rerank authorized candidates with bounded latency/cost and measured relevance benefit. | `src/retrieval/reranking.py` |
| FR-033 | Context assembly and evidence budgeting | P0 | Not implemented | Deduplicate selected evidence, preserve locators and fit the model context budget without mixing authorization scopes. | `src/retrieval/context_builder.py` |

### LangGraph orchestration

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-034 | Basic LangGraph state and execution flow | P0 | Not implemented | Run an explicit retrieve/generate graph with validated state and reproducible execution outcomes. | `src/agents/graph.py`; `src/agents/state.py`; `src/agents/routing.py` |
| FR-035 | Planning and allowlisted agent tools | P2 | Not implemented | Use only approved search/fetch tools; the planner cannot choose identity, grant permissions or execute arbitrary external actions. | `src/agents/nodes/plan.py`; `src/agents/tools` |
| FR-036 | Relevance grading and conditional query rewriting | P2 | Not implemented | Grade evidence and rewrite only under an explicit policy; terminate or abstain when additional attempts cannot help. | `src/agents/nodes/grade.py`; `src/agents/nodes/rewrite.py` |
| FR-037 | Answer evidence verification and repair policy | P1 | Not implemented | Check claims against supplied evidence and apply bounded repair or abstention instead of treating fluent output as proof. | `src/agents/nodes/verify.py` |
| FR-038 | Graph execution budgets and termination | P0 | Not implemented | Enforce iteration, tool-call, token and wall-clock limits and return a safe terminal outcome when a budget expires. | `src/agents/budgets.py`; `src/agents/routing.py` |

### Answers and chat API

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-039 | Grounded question-answer API | P0 | Not implemented | Accept an authenticated question and return an evidence-based answer from authorized indexed documents through the selected model. | `src/api/routes/chat.py`; `src/services/chat_service.py`; `src/generation/answer_service.py` |
| FR-040 | Source/page citations and locator validation | P0 | Not implemented | Every returned citation resolves to authorized source evidence; no invented document IDs or page references are accepted. | `src/retrieval/citations.py`; `src/generation/answer_service.py` |
| FR-041 | Insufficient-evidence abstention | P0 | Not implemented | Queries with inadequate or inaccessible evidence return an explicit insufficient-evidence outcome rather than unsupported claims. | `src/generation/answer_service.py` |
| FR-042 | Streaming answers and disconnect handling | P1 | Not implemented | Stream authorized responses using a documented event contract and stop/release provider work on disconnect or cancellation. | `src/generation/streaming.py` |
| FR-043 | Validated structured-answer mode | P2 | Not implemented | Return schema-valid structured answers with controlled validation failure/retry behavior when the consumer requests that mode. | `src/generation/structured_output.py` |

### Conversations and feedback

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-044 | Conversation history and context-window management | P1 | Not implemented | Persist turns and supply bounded relevant history without passing unlimited prior messages to the model. | `src/domain/conversations.py`; `src/infrastructure/mongodb/conversation_repository.py` |
| FR-045 | Thread ownership and lifecycle APIs | P1 | Not implemented | Only authorized tenant/users can create, read, list or modify their threads and any persisted graph state. | `src/services/chat_service.py`; `src/api/routes/chat.py` |
| FR-046 | Answer feedback capture | P1 | Not implemented | Record feedback against an authorized answer/trace without allowing cross-tenant correlation or modification. | `src/api/routes/feedback.py` |
| FR-047 | Conversation export and deletion | P2 | Not implemented | Export or delete authorized conversation records under the approved privacy/retention policy, including associated derived records where applicable. | `src/services/chat_service.py`; `src/infrastructure/mongodb/conversation_repository.py` |

### Enterprise tenant access

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-048 | Organization membership and invitation workflows | P1 | Partial | Local global accounts, transactional workspaces, multi-tenant membership and one-time email-bound invitations work. Production delivery and IdP provisioning remain. | `src/services/tenant_service.py`; `src/infrastructure/mongodb/tenant_repository.py` |
| FR-049 | Tenant roles and permission enforcement | P1 | Partial | Enforce an approved role/action matrix on tenant administration, document sharing and operational actions. | `src/services/access_service.py`; `src/domain/permissions.py` |
| FR-050 | Document ACLs and same-tenant sharing | P1 | Partial | Grant/revoke document access explicitly and propagate changes to retrieval, citations and caches. Current service policy is uploader-only. | `src/services/access_service.py`; `src/domain/permissions.py` |
| FR-051 | Tenant administration and suspension | P1 | Partial | Manage tenant profile/ownership and suspension through privileged APIs; suspended tenants cannot continue tenant-owned operations. | `src/api/routes/admin.py`; `src/services/access_service.py` |
| FR-052 | Durable audit trail | P0 | Partial | Record privileged, access-policy and sensitive lifecycle events with actor/tenant/correlation/time and an approved access/retention policy; ordinary logs are not the audit store. | `src/domain/events.py`; `src/observability` |

### Redis, caching and quotas

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-053 | Redis application adapter and lifecycle | P1 | Not implemented | Connect with bounded operations, verify readiness and define safe behavior during cache/rate-store outages. A running Redis container is not an adapter. | `src/infrastructure/redis/client.py` |
| FR-054 | Authorization-aware retrieval caching | P1 | Not implemented | Key by tenant, access-policy scope/version, index version, retrieval/model configuration and query; invalidate on access/index changes. | `src/infrastructure/redis/cache.py` |
| FR-055 | Optional answer caching | P2 | Not implemented | Enable only under an explicit policy with authorization, prompt/model/index version keys and evidence-safe invalidation. | `src/infrastructure/redis/cache.py` |
| FR-056 | Tenant-wide API/LLM quotas and rate limits | P0 | Partial | Enforce tenant request/token/storage or ingestion budgets according to an approved quota policy. Existing Mongo-backed local-auth limits do not cover RAG usage. | `src/infrastructure/redis/rate_limits.py`; `src/core/tenancy.py` |

### Observability and privacy

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-057 | Langfuse end-to-end tracing | P0 | Not implemented | Correlate ingestion, retrieval, graph and model spans to approved tenant/request/job identifiers without exporting secrets. | `src/observability/tracing.py` |
| FR-058 | Trace/content redaction and trace-retention policy | P0 | Partial | Redact sensitive document/prompt/identity content before trace export and enforce approved retention; current application log masking is not tracing redaction. | `src/observability/redaction.py` |
| FR-059 | Operational, latency, token and cost metrics | P0 | Not implemented | Measure job failures/queue depth, stage/query latency and model usage/cost using a defined operational metric contract. | `src/observability/metrics.py` |
| FR-060 | Operational dashboards and alert rules | P1 | Not implemented | Expose actionable views/alerts for backlog, failure rates, dependency health, latency and quota/cost anomalies. | `src/observability/metrics.py`; `deploy` |

### Evaluation and quality

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-061 | Reviewed golden datasets | P0 | Not implemented | Maintain versioned questions, expected evidence/answers and authorization cases; review trace-derived examples before dataset reuse. | `evals/datasets` |
| FR-062 | Ragas evaluation runners | P0 | Not implemented | Run a reproducible evaluation against a selected dataset, retrieval/index configuration and model/judge version. | `evals/runners` |
| FR-063 | Retrieval, answer and citation quality reports | P0 | Not implemented | Report recall/ranking, faithfulness, citation correctness, abstention, latency and cost with documented metric definitions. | `evals/runners` |
| FR-064 | Evaluation regression release gates | P0 | Not implemented | Compare to an approved baseline and block releases that violate approved quality/security thresholds; thresholds must be agreed, not invented. | `evals`; `CI configuration` |

### Deployment and operations

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-065 | Dependency readiness checks | P0 | Partial | Separate liveness from readiness and report required dependency failures without disclosing credentials; current /health is liveness only. | `src/api/routes/health.py` |
| FR-066 | API/worker container images and dependency lock | P0 | Partial | Build repeatable API and worker images from a locked dependency set with documented configuration and least-privilege execution; infrastructure Compose already exists. | `deploy/docker`; `pyproject.toml` |
| FR-067 | CI quality and security checks | P0 | Not implemented | Run applicable unit/integration/isolation checks, dependency/image checks and release artifacts without production credentials. | `CI configuration`; `tests` |
| FR-068 | Production deployment configuration | P2 | Not implemented | Provide the selected deployment manifests, secrets/network policy, rollout/rollback and resource/concurrency settings; Kubernetes is conditional on the deployment decision. | `deploy/k8s` |
| FR-069 | Backup, restore and disaster recovery | P1 | Not implemented | Restore required MongoDB/MinIO/index data consistently and demonstrate agreed recovery objectives in a rehearsal. | `scripts`; `deploy`; `docs` |
| FR-070 | Operator tooling and recovery runbooks | P0 | Not implemented | Provide controlled DLQ inspection/replay, failed-job investigation, reconciliation and maintenance procedures with authorization and safe defaults. | `scripts`; `src/workers/maintenance_worker.py`; `src/api/routes/admin.py` |

### Local-account enhancements

| ID | Business capability | Priority | Current status | Acceptance criteria | Implementation trace |
| --- | --- | --- | --- | --- | --- |
| FR-071 | Email verification | P1 | Not implemented | In local mode, verify ownership using expiring single-use challenges before public account capabilities according to the approved registration policy. | `src/services/auth_service.py`; `src/api/routes/auth.py` |
| FR-072 | Password reset and authenticated password change | P1 | Not implemented | Use expiring single-use reset challenges, prevent enumeration and apply an explicit session-invalidation policy on credential change. | `src/services/auth_service.py`; `src/api/routes/auth.py` |
| FR-073 | Multi-factor authentication | P2 | Not implemented | Implement an approved MFA/enrollment/recovery policy or delegate it to the external identity provider; scope requires a product decision. | `src/services/auth_service.py`; `src/core/security.py` |
| FR-074 | Signing-key rotation with overlap | P1 | Partial | Rotate local signing keys with an approved old-key verification overlap and emergency revocation procedure; current key replacement invalidates all local tokens. | `src/core/security.py` |
| FR-075 | Account session management and global logout | P1 | Partial | List/revoke authorized sessions and revoke all sessions for an account when requested; current logout revokes only the supplied refresh token's session. | `src/services/auth_service.py`; `src/infrastructure/mongodb/auth_repository.py` |

## 9. Business rules

1. Tenant/user identity comes only from verified authentication or validated stored
   job ownership. Tenant selection is never an agent decision.
2. Local signup cannot grant membership in an existing tenant. Owner-only access
   remains the baseline until an approved ACL/membership model replaces it.
3. Missing and unauthorized resources must not disclose another tenant's existence.
4. Private files and derived evidence are never served merely because their storage
   key, UUID, vector identifier or citation URL is known.
5. New/partial indexes are not searchable. Current metadata determines permitted
   version/status at the serving boundary, not stale cache/vector metadata alone.
6. Retryable deliveries are expected; workers persist durable state before ack and
   use idempotent writes. Retry counts and graph loops are bounded.
7. Retrieved content is untrusted data, not permission to change identity or invoke
   arbitrary tools. Prompt injection cannot alter authorization boundaries.
8. Original files, metadata, vectors and queue delivery do not share one transaction.
   Cross-store failures require explicit compensation/reconciliation rules.
9. Access revocation, replacement and deletion invalidate relevant cached results.
   Answer caches cannot be shared across authorization scopes.
10. A citation is valid only if its document/version/locator exists and the caller
    is currently authorized to see the supporting text.
11. Credentials, tokens and unrestricted private content must not enter ordinary
    logs, exported traces or public evaluation datasets.
12. Chat and embedding changes are independently configurable. Incompatible
    embedding dimensions/chunking policies require a new index and reindexing.

## 10. Nonfunctional requirements and acceptance gates

These cross-cutting requirements are not additional items in the 75-feature count.

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| NFR-01 | Tenant and authorization isolation | Adversarial API, repository, vector, cache, citation, conversation, worker and trace tests show no unauthorized source/identity disclosure |
| NFR-02 | Identity and credential safety | Invalid/expired/revoked local sessions fail closed; external mode follows the approved issuer contract; secrets never appear in logs/errors/artifacts |
| NFR-03 | File/request safety | Approved format/size limits, temporary-storage and concurrency limits, parsing resource isolation and an explicit malicious-file handling policy are verified |
| NFR-04 | Trace/data privacy | Approved redaction, export, access and retention policies are tested before private prompts/documents are traced |
| NFR-05 | Reliable asynchronous execution | Duplicate delivery, publisher interruption, worker crash, transient/permanent errors and partial writes leave recoverable observable state |
| NFR-06 | Quality and groundedness | A reviewed, versioned evaluation set meets approved retrieval, citation, faithfulness and abstention thresholds; model/judge/configuration are recorded |
| NFR-07 | Performance | Measure ingestion throughput and p50/p95 query/first-token latency on an approved workload; enforce agreed timeouts and budgets |
| NFR-08 | Scalability and cost | Demonstrate bounded pools, concurrency, queue backpressure, context size and tenant budgets at the agreed load |
| NFR-09 | Recoverability | Rehearsed restore and index rebuild meet business-approved RPO/RTO; credentials and encryption keys have an approved recovery policy |
| NFR-10 | Maintainability and reproducibility | Locked compatible dependencies, independent API/worker entry points, useful docs, meaningful tests and reproducible artifacts |
| NFR-11 | Operability | Readiness, safe error classification, correlation, metrics and runbooks distinguish auth/provider/dependency/job failures |
| NFR-12 | Deployment security | Authenticated stores, TLS where required, restricted network exposure and least-privilege service access are validated for the chosen deployment |

Performance/quality targets, dataset size, concurrency, storage scale, RPO/RTO and
retention durations were not supplied. They are **TBD business decisions**, not
measured results or assumed promises. The product/evaluation/platform owners must
approve numeric targets and reference workloads before the corresponding release
gate can be signed off. A local single-node Compose setup is not a production HA
or security architecture.

## 11. Data ownership and privacy

| Data | Authoritative owner | Required handling |
| --- | --- | --- |
| Identity/membership/ACL | Selected identity system plus MongoDB application policy | Verify claims/membership; enforce tenant and action scope |
| Originals/derived artifacts | MinIO, referenced by authoritative metadata | Private storage, scoped keys and authorized downloads/retention |
| Documents/versions/manifests/jobs/outbox | MongoDB | Tenant indexes, legal lifecycle transitions and durable recovery state |
| Embeddings/chunk text | ChromaDB | Tenant/ACL filters and active-version checks; derived, rebuildable index |
| Delivery/retry state | RabbitMQ plus MongoDB job authority | Identifier-only messages, confirmations, durable state before ack |
| Cached results/quotas | Redis | Expiration and scope/version-aware invalidation; documented failure behavior |
| Conversations/feedback/audit | MongoDB or approved audit destination | Ownership checks, retention/export/deletion rules and restricted access |
| Traces/evaluation examples | Langfuse and reviewed evaluation assets | Redaction, access/retention policy and explicit review before dataset reuse |

Legal basis, residency, encryption/key-management policy and retention exceptions
must be decided by the business/security owners. This document does not assert
compliance with an unnamed law or certification.

## 12. Proposed delivery sequence and dependencies

| Milestone | Outcome | Main dependency / gate |
| --- | --- | --- |
| M1 Reliable ingestion | Authorized stored PDF becomes a tracked, completed Chroma index | Outbox/queue/worker reliability; Docling/chunking; embedding adapter and manifest commit |
| M2 Cited QA | An authorized query returns a grounded answer or abstention | M1; chat adapter; vector authorization/context; basic bounded LangGraph; valid citations |
| M3 Controlled-pilot readiness | Core workflow has recovery, quotas, tracing, evaluation and repeatable operation | Remaining P0 items and all applicable NFR gates; approved reference workload/quality targets |
| M4 Enterprise/team completion | Membership, sharing, versions, conversations, caches and operational/account completion | Approved role/ACL, lifecycle, quota, retention and selected identity policies |
| M5 Approved extensions | Additional formats/connectors, hybrid/rerank, advanced agents, structured output or MFA | Explicit scope approval and measured benefit; production manifests only for the selected target |

No dates, costs or effort estimates are assigned. P1 ordering must change if a
public signup, multi-user tenant or production rollout is planned before a closed
pilot. P0 features do not waive security/privacy/backup requirements for a shared
production release. Dependencies can require implementing a subset of a later
feature earlier; an initial active index is required before full version replacement.

## 13. Release and user acceptance criteria

A controlled pilot can be accepted only when:

- The agreed P0 scope and all applicable NFR gates have reproducible evidence.
- An authorized PDF completes upload, job creation, processing, indexing and cited QA.
- Missing/insufficient evidence produces an approved abstention response.
- Tenant/user revocation and document deletion prevent further unauthorized source retrieval.
- Duplicate/replayed work and interrupted publication/processing do not create duplicate searchable content.
- Sensitive information is excluded from telemetry according to the approved policy.
- Quality and latency/cost reports reference agreed datasets, model/index/prompt versions and workloads.
- Operators can inspect failures, recover known partial states, replay safely and roll back a release.
- Business/product, security/privacy, quality and platform owners sign off their respective gates.

Before team/public/production use, also complete the P1 requirements needed for
that rollout: for example membership/ACLs for sharing, email verification or an
approved external-provider policy for public registration, and backup/restore for
production data. Optional P2 features are accepted only against their approved scope.

## 14. Risks and mitigations

| Risk | Business impact | Required mitigation / decision |
| --- | --- | --- |
| Cross-tenant or stale-ACL evidence | Private information disclosure | End-to-end authorization tests and authoritative serving checks |
| Ambiguous upload/index/publication outcome | Lost or orphaned work; invalid deletion | Durable intent, idempotency, compare-and-set transitions and reconciliation |
| Incomplete/incorrect parsing or citations | Misleading answers and reduced trust | Provenance-preserving fixtures, format/OCR policy, citation validation and abstention |
| Model/provider latency, failure or cost spikes | Unusable service or unexpected spend | Budgets, quotas, timeouts, bounded concurrency and approved provider policy |
| Traces containing private content | Unauthorized data export/retention | Redaction and explicit trace access/retention controls before export |
| Optional scope treated as committed | Delayed core delivery | Keep P2 approval explicit and use milestone exit gates |
| Local deployment mistaken for production | Availability/security gaps | Environment-specific deployment design and rehearsed recovery |
| Shared-tenant access designed late | Rework or overly broad permissions | Approve role/ACL/membership matrix before team-sharing implementation |

## 15. Open decisions and approvals

| Decision | Required owner | Needed before |
| --- | --- | --- |
| Chat/embedding provider, model, credentials, hosting/residency | Product + platform + security | Embeddings and QA implementation |
| Target users/tenant count, corpus size, formats/OCR and input limits | Product + data owner | Ingestion acceptance and capacity benchmark |
| Membership, role/action and document-sharing matrix | Product + security | Team/tenant administration and ACL delivery |
| Closed pilot versus public signup; local versus external identity | Product + security | Registration rollout and required account hardening |
| Evaluation corpus, metric definitions, judge and pass thresholds | Quality + product | Pilot/release-gate acceptance |
| Latency/throughput/cost targets and reference workload | Product + platform | Performance sign-off |
| Deletion, retention, audit, trace export/residency and file-safety policy | Data/security/privacy owner | Shared deployment and lifecycle rollout |
| Production host/deployment model, service authentication and network controls | Platform + security | Production artifacts/manifests |
| Backup scope and recovery objectives | Business + platform | Production data onboarding |
| P2 items to include or defer, budget and delivery schedule | Product sponsor | Any optional-extension commitment |

Approval status remains Draft until named owners accept the scope, success
thresholds and rollout decisions. No delivery dates or budgets are committed.

## 16. Repository references and maintenance

- [Feature status](../FEATURES.md)
- [Complete remaining-feature checklist](remaining-features.md)
- [Architecture and reliability rules](architecture.md)
- [Configuration](../configs/README.md)
- [External authentication](authentication.md) and [local authentication](local-auth.md)
- [Upload API](uploads.md), [storage](storage.md), [logging](logging.md)
- [Local infrastructure](../deploy/docker/README.md)

When a requirement is completed, record implementation and validation evidence,
update its status and the companion checklist, and recalculate counts. Scope
additions must receive an explicit new requirement ID; renaming/splitting features
must not silently change the reported baseline.

