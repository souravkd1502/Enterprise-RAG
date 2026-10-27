# Build the upstream source release because the public MinIO image is unavailable.
FROM golang:1.26.9-bookworm AS build
WORKDIR /build
RUN git clone --depth 1 --branch RELEASE.2025-10-15T17-29-55Z https://github.com/minio/minio.git .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /data \
    && chown 10001:10001 /data
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /build/LICENSE /usr/share/doc/minio/LICENSE
USER 10001:10001
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
