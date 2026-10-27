# Feature status and roadmap

Status date: 2026-10-28 (Asia/Calcutta).

API, authentication, tenant-context, PDF upload/storage, metadata, logging and
local-infrastructure foundations are implemented. The RAG processing and
question-answer workflow is not implemented yet.

**75 tracked functional features remain: 58 not implemented and 17 partial.**
Proposed priorities are **37 P0**, **26 P1**, and **12 P2**. P2 items are optional
or decision-dependent; this is not a count of mandatory first-release features,
an effort estimate or a completion percentage.

See the [complete remaining-feature checklist](docs/remaining-features.md) and
[Business Requirements Document](docs/BRD.md) for all requirement IDs, acceptance
criteria, current-state evidence, dependencies and release gates. These planning
priorities are drafts, not approved delivery commitments.

The original target-area table below describes the intended complete product;
individual areas now contain both implemented foundations and unfinished work.

| Area | Planned features | Main modules |
| --- | --- | --- |
| Document ingestion | Upload PDF, DOCX and other agreed formats; asynchronous jobs; Docling parsing; page and section metadata; structure-aware chunking | api/routes/documents, ingestion |
| Reliable workers | RabbitMQ consumers, explicit acknowledgements, bounded retries, dead-letter routing, idempotent writes, stage checkpoints, cancellation | workers, ingestion/checkpoints, infrastructure/rabbitmq |
| Document lifecycle | Content hashes, deduplication within a tenant, versions, reindexing, active-version filtering, deletion and reconciliation | services/document_service, ingestion/indexing |
| Agentic retrieval | LangGraph planning, query rewriting, retrieval, relevance grading, bounded retries, answer generation and groundedness checking | agents, retrieval |
| Search | Chroma vector retrieval; optional MongoDB-backed lexical retrieval with a suitable configured index; fusion and reranking | retrieval/strategies |
| Answers | Source and page citations, evidence-backed responses, abstention when evidence is insufficient, streaming | generation, retrieval/citations |
| Enterprise access | Tenant isolation, identity-provider integration, roles, document ACLs and audit records | core/security, core/tenancy, services/access_service |
| Conversations | Chat history, thread ownership, feedback and context limits | services/chat_service, infrastructure/mongodb |
| Flexible models | LangChain model adapters; separate chat and embedding configuration; provider credentials outside source control | infrastructure/llm |
| Cache and quotas | Redis retrieval caching, optional answer caching, request quotas and rate limits | infrastructure/redis |
| Observability | Langfuse tracing, token and latency tracking, feedback correlation, redaction; operational queue and job metrics | observability |
| Evaluation | Ragas evaluation, retrieval recall and ranking metrics, curated golden questions, regression comparisons | evals |
| Operations | Health/readiness, job status, DLQ replay, reconciliation, retention and backups | api/routes, workers/maintenance_worker, scripts |

Next delivery: durable job/outbox submission and RabbitMQ workers, then Docling parsing, chunking, embeddings and Chroma indexing. Follow with authorized cited QA through a bounded LangGraph flow, tracing and a reviewed evaluation set.

Next: version-safe reindexing, robust retries/deletion, document ACLs, hybrid search, bounded agentic retrieval and operational tooling. Validate authentication and tenant boundaries before any shared deployment.
