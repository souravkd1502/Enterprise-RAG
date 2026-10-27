# Enterprise RAG scaffold

Folder and module skeleton for FastAPI, Python workers, RabbitMQ, LangChain, LangGraph, Docling, ChromaDB, MinIO, MongoDB, Redis, Langfuse and Ragas.

Runtime configuration, logging, JWT tenant authentication, PDF uploads to MinIO, and tenant-scoped MongoDB document metadata are implemented. See [configuration setup](configs/README.md), [tenant-aware logging](docs/logging.md), [authentication](docs/authentication.md), [document storage](docs/storage.md), and [upload API usage](docs/uploads.md). [Local Compose infrastructure](deploy/docker/README.md) provides MongoDB, ChromaDB, MinIO, Redis, and RabbitMQ. The API serves `/health` and authenticated document upload/metadata routes. RAG ingestion, retrieval, other storage clients, and workers remain placeholders. No dependency lock or API/worker container images are included.

See FEATURES.md for the feature roadmap and docs/architecture.md for flows, persistence ownership and reliability rules.

The [remaining-feature checklist](docs/remaining-features.md) tracks 75 unfinished
deliverables, including partial and optional scope. The [BRD](docs/BRD.md) defines
business requirements, priorities, acceptance criteria and release decisions.

[Local authentication](docs/local-auth.md) adds signup, login, rotating refresh
tokens, session logout, global accounts, OWNER/MEMBER workspace memberships and
one-time development invitations. Enable it with `AUTH_MODE=local` and a private
signing-key file. Follow the [Swagger walkthrough](docs/local-auth.md#complete-swagger-walkthrough)
at **http://localhost:8000/docs**. External JWT mode requires provisioned MongoDB
tenant memberships.

Start FastAPI and the lightweight Node.js frontend together from a POSIX shell
(Linux, macOS or Git Bash on Windows):

```sh
sh run.sh
# Optional development reload:
sh run.sh --reload
```

The script uses `.venv` and Node.js 22+, and starts from the project root so FastAPI
loads `.env`. Open the frontend at http://localhost:3000 or Swagger at
http://localhost:8000/docs. Ctrl+C stops both. Stop any existing API instance before
starting the combined launcher. Start local infrastructure first; see the
[setup guide](docs/local-auth.md#start-locally).

The [frontend guide](frontend/README.md) covers signup, tenant creation, workspace
selection and logout. The UI uses plain HTML/CSS/JavaScript with no npm dependencies.

## Folder structure

```text
enterprise-rag/
├── frontend/                    # Lightweight Node.js account/workspace UI
├── configs/
│   └── README.md
├── deploy/
│   ├── docker/
│   │   ├── .dockerignore
│   │   ├── .env.example
│   │   ├── compose.yaml
│   │   ├── Minio.Dockerfile
│   │   ├── mongodb-init.js
│   │   └── README.md
│   └── k8s/
│       └── README.md
├── docs/
│   ├── BRD.md
│   ├── architecture.md
│   ├── authentication.md
│   ├── logging.md
│   ├── local-auth.md
│   ├── remaining-features.md
│   ├── storage.md
│   └── uploads.md
├── evals/
│   ├── datasets/
│   │   └── .gitkeep
│   ├── runners/
│   │   └── .gitkeep
│   └── README.md
├── prompts/
│   └── README.md
├── scripts/
│   └── README.md
├── src/
│   ├── agents/
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── generate.py
│   │   │   ├── grade.py
│   │   │   ├── plan.py
│   │   │   ├── retrieve.py
│   │   │   ├── rewrite.py
│   │   │   └── verify.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── fetch_document.py
│   │   │   └── search_documents.py
│   │   ├── __init__.py
│   │   ├── budgets.py
│   │   ├── graph.py
│   │   ├── routing.py
│   │   └── state.py
│   ├── api/
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── admin.py
│   │   │   ├── chat.py
│   │   │   ├── documents.py
│   │   │   ├── feedback.py
│   │   │   ├── health.py
│   │   │   └── jobs.py
│   │   ├── __init__.py
│   │   ├── dependencies.py
│   │   ├── main.py
│   │   └── middleware.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   ├── security.py
│   │   └── tenancy.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── conversations.py
│   │   ├── documents.py
│   │   ├── events.py
│   │   ├── jobs.py
│   │   └── permissions.py
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── answer_service.py
│   │   ├── streaming.py
│   │   └── structured_output.py
│   ├── infrastructure/
│   │   ├── chromadb/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── collections.py
│   │   │   └── vector_store.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── chat_models.py
│   │   │   ├── embedding_models.py
│   │   │   └── factory.py
│   │   ├── minio/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   └── object_store.py
│   │   ├── mongodb/
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── conversation_repository.py
│   │   │   ├── document_repository.py
│   │   │   ├── indexes.py
│   │   │   ├── job_repository.py
│   │   │   └── outbox_repository.py
│   │   ├── rabbitmq/
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── consumer.py
│   │   │   ├── publisher.py
│   │   │   └── topology.py
│   │   ├── redis/
│   │   │   ├── __init__.py
│   │   │   ├── cache.py
│   │   │   ├── client.py
│   │   │   └── rate_limits.py
│   │   └── __init__.py
│   ├── ingestion/
│   │   ├── connectors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── upload.py
│   │   │   └── web.py
│   │   ├── indexing/
│   │   │   ├── __init__.py
│   │   │   ├── cleanup.py
│   │   │   ├── index_writer.py
│   │   │   └── version_activation.py
│   │   ├── parsing/
│   │   │   ├── __init__.py
│   │   │   ├── docling_parser.py
│   │   │   └── normalization.py
│   │   ├── processing/
│   │   │   ├── __init__.py
│   │   │   ├── chunking.py
│   │   │   ├── embeddings.py
│   │   │   └── metadata.py
│   │   ├── __init__.py
│   │   ├── checkpoints.py
│   │   ├── idempotency.py
│   │   └── pipeline.py
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   ├── redaction.py
│   │   └── tracing.py
│   ├── retrieval/
│   │   ├── strategies/
│   │   │   ├── __init__.py
│   │   │   ├── hybrid.py
│   │   │   ├── lexical.py
│   │   │   └── vector.py
│   │   ├── __init__.py
│   │   ├── citations.py
│   │   ├── context_builder.py
│   │   ├── filters.py
│   │   ├── pipeline.py
│   │   └── reranking.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── chat.py
│   │   ├── documents.py
│   │   ├── jobs.py
│   │   └── queue_messages.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── access_service.py
│   │   ├── chat_service.py
│   │   ├── deletion_service.py
│   │   ├── document_service.py
│   │   └── ingestion_service.py
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── handlers.py
│   │   ├── ingestion_worker.py
│   │   ├── maintenance_worker.py
│   │   └── retry_policy.py
│   └── __init__.py
├── tests/
│   ├── e2e/
│   │   └── .gitkeep
│   ├── fixtures/
│   │   └── .gitkeep
│   ├── integration/
│   │   └── .gitkeep
│   └── unit/
│       └── .gitkeep
├── .env.example
├── .gitignore
├── FEATURES.md
└── pyproject.toml
```
