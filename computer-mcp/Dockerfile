FROM golang:1.25-bookworm AS build

WORKDIR /src
COPY computer-mcp/go.mod computer-mcp/go.sum ./
RUN go mod download
COPY computer-mcp/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/relay-computer-mcp ./cmd/server

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin relaymcp
COPY --from=build /out/relay-computer-mcp /usr/local/bin/relay-computer-mcp
USER 10001:10001
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/relay-computer-mcp"]
