# Agent guide

Relay is a single-container Linux desktop for human–agent collaboration: noVNC
streaming, lease-based control handoff, bounded X11 input, AT-SPI grounding, and
Coddy with a Go MCP computer server.

## Layout

- `desktop/control/` — control API, leases, validated input (`xdotool`)
- `desktop/broker/` — guarded APT / `.deb` install approvals
- `computer-mcp/` — Go MCP `computer` + `ui_inspect` tools
- `web/` — browser shell (noVNC embed, Coddy panel, handoff UI)
- `agent/` — pinned Coddy config and `os-operator` skill
- `tests/` — Python unit tests, static invariants, container smoke

## Conventions

- Python 3 standard library in control services; no extra runtime deps there.
- Agent input is typed JSON actions, never shell strings.
- Human control always preempts agent control (HTTP 409 on conflict).
- Community defaults bind Compose to `127.0.0.1`; treat tokens as secrets when
  exposing beyond loopback.
- Duplicate skill copies: `agent/skills/` is the source; image seeds
  `desktop/home/.agents/skills/os-operator` at runtime.

## Validate changes

```bash
make test      # unit + Go + web tests
make static    # syntax, compose, skill, and layout invariants
make smoke     # live container framebuffer, input, and handoff (needs Docker)
```

Manual handoff checklist: `docs/TESTING.md`.

## Operating loop for agents

1. `GET /api/v1/accessibility` (or MCP `ui_inspect`) for structure.
2. Screenshot when canvas / Electron surfaces lack AT-SPI detail.
3. `claim` agent lease, small action batch, observe again.
4. `heartbeat` every ~8s during long turns; `release` when handing back.

Coordinates are always framebuffer pixels (default 1440×900), not browser scale.
