FROM golang:1.25-bookworm AS build

ARG CODDY_REF=2ba0ec9cc531e31954c2565b2984d92d4bc890d3
RUN git clone --filter=blob:none https://github.com/coddy-project/coddy-agent.git /src/coddy \
    && git -C /src/coddy checkout --detach "$CODDY_REF"
COPY agent/patches/0001-preserve-mcp-image-results.patch /tmp/coddy.patch
RUN git -C /src/coddy apply --check /tmp/coddy.patch \
    && git -C /src/coddy apply /tmp/coddy.patch
WORKDIR /src/coddy
RUN CGO_ENABLED=0 go test ./internal/mcp ./internal/agent ./internal/llm \
    && CGO_ENABLED=0 go build -trimpath -tags=http -ldflags="-s -w" -o /out/coddy ./cmd/coddy

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /var/lib/coddy --shell /bin/sh coddy \
    && install -d -m 0700 -o coddy -g coddy /var/lib/coddy \
    && install -d -m 0750 -o coddy -g coddy /workspace /opt/relay-agent/skills/os-operator \
    && install -d -m 0755 /usr/share/licenses/coddy
COPY --from=build /out/coddy /usr/local/bin/coddy
COPY --from=build /src/coddy/LICENSE /usr/share/licenses/coddy/LICENSE
COPY --chown=coddy:coddy agent/config.yaml /etc/coddy/config.yaml
COPY --chown=coddy:coddy agent/skills/os-operator/SKILL.md /opt/relay-agent/skills/os-operator/SKILL.md
USER 10001:10001
WORKDIR /workspace
EXPOSE 12345
ENTRYPOINT ["/usr/local/bin/coddy"]
CMD ["http", "-H", "0.0.0.0", "-P", "12345", "--config", "/etc/coddy/config.yaml", "--home", "/var/lib/coddy"]
