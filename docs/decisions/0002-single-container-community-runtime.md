# ADR 0002: Run the community desktop as one container

- Status: accepted
- Date: 2026-08-12
- Supersedes: [ADR 0001](0001-coddy-go-mcp-sidecar.md) for process deployment

## Context

The original Coddy integration used three Compose services: desktop, computer MCP,
and Coddy. That layout made component lifecycles independent, but it also made a
local community demo harder to understand and restart. Persisted Coddy
conversations could retain an expired stateful MCP transport session after the MCP
container was recreated, producing `404 session not found`.

Relay is currently a community reference implementation, not a hosted multi-tenant
service. A contributor should be able to build, inspect, restart, and debug the
whole desktop with one Compose service.

## Decision

Build Coddy and the Go computer MCP as stages in the root Dockerfile, then copy
both binaries into the desktop image. Supervisor runs them beside Xvfb, XFCE,
x11vnc, the control API, gateway, and nginx.

Keep component interfaces intact inside the image. Coddy reaches MCP over
`127.0.0.1:8090`; MCP reaches the Relay API over `127.0.0.1:8080`. Configure the
MCP Streamable HTTP handler as stateless so a persisted conversation does not
depend on server memory from a previous container.

Retain the three named volumes for desktop files, approved-install state, and
Coddy conversations. One runtime container does not require one persistence
domain.

## Consequences

- `docker compose up`, `ps`, `logs`, health checks, and recreation operate one
  service.
- The browser, agent harness, and computer tools restart together.
- Coddy and MCP remain replaceable modules with a tested HTTP contract.
- Existing named volumes continue to work without migration.
- Contributors can split the processes later if the project grows beyond a local
  community runtime.
