# ADR 0001: Pin Coddy and isolate computer use behind a Go MCP sidecar

- Status: superseded by [ADR 0002](0002-single-container-community-runtime.md)
- Date: 2026-08-11

## Context

Relay needs a temporary community agent harness while NusaShell Go remains a
prototype. The harness must accept OpenAI-compatible providers, persist sessions,
serve a browser client, load skills, and call a multimodal computer-use tool.

`forkbikash/agent-go` was considered first. It is small and understandable, but is
currently an Anthropic-first coding CLI with an early browser/session story. Taking
it to a reliable desktop operator would make Relay responsible for most of the
harness layer.

## Decision

Build Coddy Agent from exact commit
`2ba0ec9cc531e31954c2565b2984d92d4bc890d3` and run it as an unprivileged internal
sidecar. Carry one checked patch that preserves MCP image results in model context.

Expose Relay computer use through a separate Go service using the official Go MCP
SDK and Streamable HTTP. Keep the contract to one `computer` action tool plus
`ui_inspect`. Give Coddy the provider credential but not the Relay operator token;
give the MCP service the Relay token but not the provider credential.

## Consequences

- Relay can replace Coddy with NusaShell or another MCP client without changing
  display/input APIs.
- Computer actions are testable without an LLM and remain simpler for weaker models.
- The pinned build and small patch limit upstream drift, but each Coddy upgrade must
  re-run patch applicability and upstream tests.
- Coddy's built-in command tool remains available in its empty container workspace
  under `ask` permission. A production deployment still needs a provider credential
  broker or a harness build that disables unused built-ins.
