# Remaining feature backlog

Status date: 2026-10-28 (Asia/Calcutta).

**75 tracked features remain: 58 not implemented and 17 partially implemented.**
They are grouped into 14 areas. This is a count of the explicitly defined functional
deliverables below, not a count of files, tasks, tests, or a percentage of project completion.
It includes conditional extensions; it does not mean 75 features are all mandatory for the first release.

The [BRD](BRD.md) defines business scope, acceptance criteria, priorities,
release gates, assumptions, and open decisions for the same IDs.

## Priority summary

| Priority | Features | Meaning |
| --- | ---: | --- |
| P0 | 37 | Core RAG and controlled-pilot release requirements |
| P1 | 26 | Enterprise completion and operational/account hardening |
| P2 | 12 | Optional or decision-dependent extensions |

Priorities are proposed planning decisions, not approved commitments. P0 is a
controlled-pilot target; P1 is required where its enterprise/public-registration
use case is enabled. P2 requires explicit scope approval. A public/production
release must also satisfy the BRD's nonfunctional and release gates.

## Area summary

| Area | Remaining | Of which partial |
| --- | ---: | ---: |
| Document ingestion | 8 | 0 |
| Queue and worker reliability | 7 | 0 |
| Document lifecycle | 9 | 5 |
| Models and provider controls | 3 | 0 |
| Retrieval | 6 | 1 |
| LangGraph orchestration | 5 | 0 |
| Answers and chat API | 5 | 0 |
| Conversations and feedback | 4 | 0 |
| Enterprise tenant access | 5 | 5 |
| Redis, caching and quotas | 4 | 1 |
| Observability and privacy | 4 | 1 |
| Evaluation and quality | 4 | 0 |
| Deployment and operations | 6 | 2 |
| Local-account enhancements | 5 | 2 |
| **Total** | **75** | **17** |

## Already implemented foundations (excluded from the count)

- Validated configuration and JSON logging with scoped tenant/user/request context.
- External issuer/JWKS verification and an explicitly enabled local auth mode.
- Local signup, login, session logout, rotating refresh tokens, password hashing,
  immediate local-session validation, and auth-specific Mongo-backed limits.
- Global local accounts, transactional workspace/OWNER creation, active memberships,
  development invitations, workspace selection, and built-in Swagger testing.
- Immutable JWT-derived tenant/user context and uploader-only document access.
- Validated/bounded PDF upload, MinIO storage and resource lifecycle.
- MongoDB metadata, lifecycle primitives, required indexes, and pool lifecycle.
- PDF metadata lookup and bounded initial listing; compensation for upload failures.
- Local Compose infrastructure and a public liveness endpoint.
- Unit/integration test suites for implemented foundations; these do not evaluate RAG quality.

Container availability and environment fields do not constitute implemented service
integrations. Log masking is not Langfuse redaction. Auth limits are not general
tenant RAG quotas. A repository soft-delete helper is not end-to-end deletion.

## Complete remaining-feature checklist

### Document ingestion (8)

- [ ] **FR-001** Asynchronous ingestion submission and job tracking — P0; not implemented.
- [ ] **FR-002** Docling PDF parsing and OCR policy — P0; not implemented.
- [ ] **FR-003** Additional document formats — P2; not implemented.
- [ ] **FR-004** Content normalization and source provenance — P0; not implemented.
- [ ] **FR-005** Structure-aware chunking — P0; not implemented.
- [ ] **FR-006** Embedding execution and batching — P0; not implemented.
- [ ] **FR-007** Chroma indexing and chunk manifests — P0; not implemented.
- [ ] **FR-008** Approved web-source ingestion — P2; not implemented.

### Queue and worker reliability (7)

- [ ] **FR-009** Transactional job/outbox intent and dispatch — P0; not implemented.
- [ ] **FR-010** RabbitMQ connection, topology and confirmed publishing — P0; not implemented.
- [ ] **FR-011** Ingestion worker consumption and acknowledgements — P0; not implemented.
- [ ] **FR-012** Bounded retries and dead-letter handling — P0; not implemented.
- [ ] **FR-013** Idempotent ingestion and deterministic writes — P0; not implemented.
- [ ] **FR-014** Durable stage checkpoints and resume — P1; not implemented.
- [ ] **FR-015** Job cancellation — P1; not implemented.

### Document lifecycle (9)

- [ ] **FR-016** Upload request idempotency — P1; not implemented.
- [ ] **FR-017** Tenant-scoped content deduplication — P1; not implemented.
- [ ] **FR-018** Document version history and safe replacement — P1; partial.
- [ ] **FR-019** Reindexing and index-policy migration — P1; not implemented.
- [ ] **FR-020** Authorized deletion and cross-store cleanup — P0; partial.
- [ ] **FR-021** Automatic stale-upload and orphan reconciliation — P0; partial.
- [ ] **FR-022** Document retention and purge schedules — P1; not implemented.
- [ ] **FR-023** Authorized original-document download API — P1; partial.
- [ ] **FR-024** Cursor pagination for document metadata — P1; partial.

### Models and provider controls (3)

- [ ] **FR-025** LangChain chat-model adapters and factory — P0; not implemented.
- [ ] **FR-026** Independent embedding-model adapters — P0; not implemented.
- [ ] **FR-027** Provider timeouts, retry policy and concurrency controls — P0; not implemented.

### Retrieval (6)

- [ ] **FR-028** Chroma vector retrieval — P0; not implemented.
- [ ] **FR-029** Retrieval authorization and active-version enforcement — P0; partial.
- [ ] **FR-030** Lexical search index and retrieval — P2; not implemented.
- [ ] **FR-031** Hybrid rank fusion — P2; not implemented.
- [ ] **FR-032** Reranking — P2; not implemented.
- [ ] **FR-033** Context assembly and evidence budgeting — P0; not implemented.

### LangGraph orchestration (5)

- [ ] **FR-034** Basic LangGraph state and execution flow — P0; not implemented.
- [ ] **FR-035** Planning and allowlisted agent tools — P2; not implemented.
- [ ] **FR-036** Relevance grading and conditional query rewriting — P2; not implemented.
- [ ] **FR-037** Answer evidence verification and repair policy — P1; not implemented.
- [ ] **FR-038** Graph execution budgets and termination — P0; not implemented.

### Answers and chat API (5)

- [ ] **FR-039** Grounded question-answer API — P0; not implemented.
- [ ] **FR-040** Source/page citations and locator validation — P0; not implemented.
- [ ] **FR-041** Insufficient-evidence abstention — P0; not implemented.
- [ ] **FR-042** Streaming answers and disconnect handling — P1; not implemented.
- [ ] **FR-043** Validated structured-answer mode — P2; not implemented.

### Conversations and feedback (4)

- [ ] **FR-044** Conversation history and context-window management — P1; not implemented.
- [ ] **FR-045** Thread ownership and lifecycle APIs — P1; not implemented.
- [ ] **FR-046** Answer feedback capture — P1; not implemented.
- [ ] **FR-047** Conversation export and deletion — P2; not implemented.

### Enterprise tenant access (5)

- [ ] **FR-048** Organization membership and invitation workflows — P1; partial. Local multi-workspace accounts, single-use email-bound invitations and acceptance work; production delivery/IdP provisioning remain.
- [ ] **FR-049** Tenant roles and permission enforcement — P1; partial. OWNER/MEMBER onboarding and request membership checks work; broader document/admin role actions remain.
- [ ] **FR-050** Document ACLs and same-tenant sharing — P1; partial.
- [ ] **FR-051** Tenant administration and suspension — P1; partial. Workspace creation and active-status enforcement work; settings/suspension/ownership APIs remain.
- [ ] **FR-052** Durable audit trail — P0; partial. MongoDB records account/session/workspace/invitation actions; broader event coverage, correlation, access and retention policy remain.

### Redis, caching and quotas (4)

- [ ] **FR-053** Redis application adapter and lifecycle — P1; not implemented.
- [ ] **FR-054** Authorization-aware retrieval caching — P1; not implemented.
- [ ] **FR-055** Optional answer caching — P2; not implemented.
- [ ] **FR-056** Tenant-wide API/LLM quotas and rate limits — P0; partial.

### Observability and privacy (4)

- [ ] **FR-057** Langfuse end-to-end tracing — P0; not implemented.
- [ ] **FR-058** Trace/content redaction and trace-retention policy — P0; partial.
- [ ] **FR-059** Operational, latency, token and cost metrics — P0; not implemented.
- [ ] **FR-060** Operational dashboards and alert rules — P1; not implemented.

### Evaluation and quality (4)

- [ ] **FR-061** Reviewed golden datasets — P0; not implemented.
- [ ] **FR-062** Ragas evaluation runners — P0; not implemented.
- [ ] **FR-063** Retrieval, answer and citation quality reports — P0; not implemented.
- [ ] **FR-064** Evaluation regression release gates — P0; not implemented.

### Deployment and operations (6)

- [ ] **FR-065** Dependency readiness checks — P0; partial.
- [ ] **FR-066** API/worker container images and dependency lock — P0; partial.
- [ ] **FR-067** CI quality and security checks — P0; not implemented.
- [ ] **FR-068** Production deployment configuration — P2; not implemented.
- [ ] **FR-069** Backup, restore and disaster recovery — P1; not implemented.
- [ ] **FR-070** Operator tooling and recovery runbooks — P0; not implemented.

### Local-account enhancements (5)

- [ ] **FR-071** Email verification — P1; not implemented.
- [ ] **FR-072** Password reset and authenticated password change — P1; not implemented.
- [ ] **FR-073** Multi-factor authentication — P2; not implemented.
- [ ] **FR-074** Signing-key rotation with overlap — P1; partial.
- [ ] **FR-075** Account session management and global logout — P1; partial.

## Recommended implementation order

1. Reliable ingestion: job/outbox, RabbitMQ publishing/consumption, idempotency,
   retries, Docling parsing, normalization/chunking, embeddings and Chroma indexing.
2. A bounded basic LangGraph query flow with authorized retrieval, cited answers
   and insufficient-evidence abstention.
3. Deletion/reconciliation, quotas, tracing/redaction, evaluation, readiness,
   repeatable release artifacts and pilot operational controls.
4. Team/tenant membership and ACLs, lifecycle/versioning, conversations, caching
   and local-account/public-registration completion according to rollout scope.
5. Approved P2 extensions such as hybrid search, advanced agent loops and MFA.

No implementation work was performed to create this inventory. Review the IDs when
scope changes; update counts and BRD priorities together.

