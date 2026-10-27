# Local development infrastructure

`compose.yaml` runs MongoDB, ChromaDB, MinIO, Redis, and RabbitMQ with named
volumes. It does not run the Python API or workers. Use Docker Desktop with Linux
containers. Start the API from the repository root after infrastructure is ready.

## Start and stop

From the repository root:

```powershell
Copy-Item deploy/docker/.env.example deploy/docker/.env
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yaml config --quiet
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yaml up -d --build --wait
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yaml ps
```

The first start downloads images and builds MinIO from its pinned upstream source
release, which can take several minutes and requires network access to GitHub,
Go module proxies, Docker Hub, and Debian package repositories. The Docker build
context excludes local configuration and secrets. Building from source avoids
depending on the unavailable public upstream MinIO images or an unreviewed mirror.
MinIO runs as UID/GID 10001 and its source license is retained in the image.

MongoDB's healthcheck initializes a single-node replica set only if none exists,
then waits for primary election. It does not overwrite an existing replica set.
MinIO, RabbitMQ, and Redis have healthchecks. Chroma currently has no container
healthcheck: `--wait` confirms that it is running, not that its HTTP API is ready.
Check its heartbeat separately:

```powershell
Invoke-RestMethod http://localhost:8001/api/v2/heartbeat
```

Stop the project's containers without removing their data:

```powershell
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yaml stop
```

Use `down` instead of `stop` when you also want to remove project containers and
the network. Avoid `down --volumes` unless you intend to erase local service data.
Container logs rotate at 10 MB with three files per service.

## Application settings

The deployment `.env` is separate from the root application `.env` because their
schemas differ. Copy the root `.env.example` only if you have not already created
your application `.env`, then set the following values. Credentials below match
the public development examples; adjust both files together if you change them.

| Application variable | Value for a Python process on the host |
| --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017/?replicaSet=rs0&directConnection=true` |
| `MONGODB_DATABASE` | `enterprise_rag` |
| `CHROMA_HOST` | `localhost` |
| `CHROMA_PORT` | `8001` |
| `CHROMA_SSL` | `false` |
| `MINIO_ENDPOINT` | `localhost:9000` |
| `MINIO_SECURE` | `false` |
| `MINIO_ACCESS_KEY` | `rag-local` |
| `MINIO_SECRET_KEY` | `local-minio-password` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `RABBITMQ_URL` | `amqp://rag-local:local-rabbitmq-password@localhost:5672/` |

JWT issuer/audience/JWKS and chat/embedding model settings must still be supplied.
The API is intended to use host port 8000; Chroma uses 8001 to avoid that conflict.
MinIO's console is at `http://localhost:9001`; RabbitMQ management is at
`http://localhost:15672`. The API creates its private document bucket at startup.
RabbitMQ queues and Chroma collections are not created yet.

The MongoDB member advertises `mongodb:27017` within the Compose network. Host
clients use `directConnection=true` to avoid resolving that container-only name.
The database is still a replica set and supports local transactions. Future
containerized applications should use `mongodb://mongodb:27017/?replicaSet=rs0`
and service names for the other hosts. Do not carry the host connection workaround
into a multi-node production deployment.

## Development boundary

All published ports bind to `127.0.0.1`. MongoDB, Redis, and Chroma have no service
authentication in this local configuration; MinIO uses its development root
credentials and RabbitMQ uses a development account. Processes on the host and
containers on the project network can reach these stores directly. This setup
is for a trusted local machine and must not be exposed as a shared deployment.

JWT enforcement belongs to the API, not these database ports. Production needs
service authentication, TLS, least-privilege credentials, network isolation,
backups, and separately reviewed replication/availability settings. A single-node
replica set enables transactions but provides no high availability. Dependency
image tags are versioned; no digest lock or image vulnerability scan is claimed.

Changing RabbitMQ bootstrap credentials does not update accounts already stored
in its volume. Manage existing accounts explicitly; do not delete volumes as a
credential-rotation mechanism.

## Live MongoDB verification

After MongoDB is healthy, run from the repository root:

```powershell
$env:TEST_MONGODB_URI = 'mongodb://localhost:27017/?replicaSet=rs0&directConnection=true'
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p 'test_*.py' -v
Remove-Item Env:TEST_MONGODB_URI
```

Tests create and remove only uniquely named `rag_test_<uuid>` databases. They
verify cross-tenant isolation, soft deletion, unique indexes, compare-and-set
updates, and transaction support. Never point this test variable at production.

References: [MongoDB test replica sets](https://www.mongodb.com/docs/manual/tutorial/deploy-replica-set-for-testing/),
[Chroma Docker deployment](https://docs.trychroma.com/deployment/docker), and
[the pinned MinIO source release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).
