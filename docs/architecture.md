# Architecture and ownership

One Python package, separate API and worker processes. LangChain supplies model/retriever integrations, LangGraph owns the retrieval graph, and Docling owns document parsing. This page describes the full target design; API/authentication and upload/storage foundations are implemented. See [current feature status](../FEATURES.md) and the [BRD](BRD.md) for implemented boundaries and remaining scope.

## Ingestion

1. FastAPI authenticates the caller and derives tenant identity from verified claims.
2. Store original bytes in MinIO and metadata plus job/outbox records in MongoDB. Recover partial failures with reconciliation; the object upload and metadata writes are not one atomic operation.
3. An outbox publisher publishes a small job reference to RabbitMQ with publisher confirmation. Use a MongoDB transaction for job plus outbox creation when deployed with transaction support; otherwise use a single-document intent and reconciler.
4. Python workers validate the job, read bytes, parse with Docling, normalize, chunk, embed, write vectors and persist a chunk manifest. Messages carry identifiers, never document bytes or credentials.
5. Mark a version searchable only after all chunks are committed. Retrieval validates active versions against authoritative metadata. Acknowledge RabbitMQ delivery after durable state updates.
6. Replayed deliveries must be safe. Use deterministic version/chunk IDs and idempotent upserts. Bound retries and route poison jobs to a dead-letter queue; avoid immediate requeue loops.

Start with one consumer executing the ingestion pipeline per job. Split parsing and embedding into separate queues only when measured bottlenecks justify it.

## Retrieval and generation

FastAPI → chat service → LangGraph planner → authorized retrieval tool → relevance grading → optional query rewrite → context assembly → answer generation → citation and evidence verification.

Use explicit graph termination rules: maximum iterations, tool calls, token budget and wall-clock deadline. The agent never chooses a tenant or bypasses document permissions. Begin with vector retrieval; hybrid retrieval is an optional extension requiring an actual lexical index and rank fusion implementation.

## Data ownership

| System | Responsibility |
| --- | --- |
| MinIO | Original uploads and optional parsed artifacts |
| MongoDB | Tenants, ACLs, documents, versions, jobs, chunk manifests, conversations, feedback and outbox |
| ChromaDB | Embeddings, retrievable chunk text and filter metadata |
| Redis | Expiring caches, quotas and rate counters; not authoritative job state |
| RabbitMQ | Job delivery, retry queues and dead letters |
| Langfuse | Traces, prompt references, feedback and evaluation visibility |
| Ragas | Offline answer/retrieval evaluation |

## Required implementation rules

- Scope every repository query, vector filter, storage key and cache key to the verified tenant. Apply ACL filters before retrieval and recheck authorization before returning source text. Add cross-tenant integration tests.
- Cache keys include tenant, access-policy scope/version, index version, model/prompt configuration and normalized query. Do not use shared answer caches across authorization scopes.
- Keep chat models and embedding models independently configurable. Changing embedding model, dimension or chunking policy requires a new index version and reindexing.
- Preserve document/version/chunk IDs, page/section locators, source references, parser/chunker versions and embedding configuration for reproducible citations.
- Deletion first makes content unsearchable, then asynchronously removes vectors, objects, manifests and relevant caches. Reconcile failures and enforce retention policies.
- Treat retrieved text as untrusted input. Allowlist agent tools and validate tool arguments; retrieved instructions cannot grant access or request arbitrary external actions.
- Maintain one publisher retry policy and one worker retry policy with clear ownership. Use queue prefetch and separate concurrency limits for parsing, embeddings and model calls.
- Redact sensitive inputs before trace export; configure trace retention explicitly. Evaluate citations and evidence, not only answer fluency.
- Pin compatible dependencies after selecting and checking the target releases. No dependencies or deployment configurations are claimed to be verified by this scaffold.

## Test ownership

Unit: chunking, graph routing, budgets and cache-key construction.
Integration: storage adapters, acknowledgements/retries, duplicate jobs, outbox recovery and tenant/ACL isolation.
End-to-end: upload → searchable version → cited answer → version replacement → deletion.
Evals: curated questions, retrieval relevance/recall, faithfulness, citation correctness, latency and cost.
