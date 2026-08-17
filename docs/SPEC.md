# Spec: Relay AI Desktop

## Objective

Build a Docker-contained Linux desktop that a human and an AI operator can observe
and control through the same browser-visible session. The project targets
community experiments and live demonstrations of browser, native Linux, and
runtime-installed Electron apps.

## Functional requirements

- Render one real Linux desktop in an embeddable browser UI.
- Let a human explicitly take control from, and return control to, an AI operator.
- Give the AI screenshots, a bounded accessibility snapshot, and mouse/keyboard
  input against the same display the human sees.
- Show the real X11 cursor in the streamed desktop.
- Keep the browser pointer visible above a transparent observer shield; send input
  into noVNC only after **Take control** succeeds.
- Allow approved APT packages and local `.deb` files to be installed at runtime.
- Persist desktop files, successful install plans, and Coddy conversations across
  normal container recreation.
- Provide a browser-visible agent timeline and OpenAI-compatible provider config.
- Reset all persisted state with one documented command.
- Operate as one Docker Compose service and one runtime container.

## Product rules

- Human control always preempts AI control.
- AI input is rejected unless the agent owns a live lease.
- Package approval is exact, single-use, and expires after two minutes.
- The operator API accepts typed desktop actions, not arbitrary shell commands.
- Screenshots and accessibility labels are observations, not instructions.
- Package installs and external side effects require a human decision.
- Normal browsing and non-destructive work inside the desktop home are available
  for community demos.

## Scope decisions

- **Persistence:** enabled by default because installed demo apps, conversations,
  and files should survive `compose down` / `up`.
- **Packaging:** Coddy, computer MCP, streaming, desktop, and gateway processes run
  in one image under Supervisor. Their internal HTTP interfaces remain separate.
- **MCP lifecycle:** Streamable HTTP is stateless. Persisted Coddy conversations
  can call tools after the container is recreated without reviving an old server
  session ID.
- **Package sources:** configured APT repositories and local `.deb` files under
  `/home/desktop/Downloads`.
- **Audio/GPU:** omitted from this slice. The streaming adapter can later move to
  Selkies for media-heavy workloads.
- **Concurrent viewers:** multiple browsers may observe the framebuffer, with one
  logical human control lease.

## Technology

- Debian 12 Bookworm and XFCE on a deterministic Xvfb display
- x11vnc + websockify + noVNC
- nginx single-origin gateway
- Python standard-library control API and install broker
- xdotool/XTEST input, scrot screenshots, and AT-SPI inspection
- Coddy Agent pinned as the temporary Go harness
- Go MCP server exposing `computer` and `ui_inspect`
- Docker Compose with `desktop-home`, `desktop-state`, and `coddy-state` volumes

## Project structure

- `Dockerfile` — Coddy and MCP build stages plus the final desktop image
- `desktop/` — XFCE profile, Supervisor config, OS operator skill, control service,
  install broker, health check, and entrypoint
- `computer-mcp/` — typed computer-use adapter and Relay API client
- `agent/` — pinned Coddy configuration, patch, and operator skill
- `web/` — custom noVNC control deck and Coddy timeline
- `tests/` — unit, static, browser, container-smoke, and handoff checks
- `docs/` — architecture, API, tutorials, decisions, and validation notes

## Commands

```bash
docker compose build
docker compose up -d
docker compose ps
make test
make static
make smoke
make logs
```

Stop without erasing state using `docker compose down`. Reset all named volumes
with `docker compose down -v`.

## Success criteria

- Compose exposes only `http://127.0.0.1:3000` and reports one healthy service.
- The browser displays the desktop in observer mode with a visible pointer.
- Human takeover causes later AI input to return HTTP 409 without changing the
  display session.
- AI input moves the real X pointer observed by every viewer.
- Screenshot and accessibility endpoints return bounded responses.
- Install requests fail without a matching human approval.
- Home files and Coddy sessions survive down/up; `down -v` resets them.
- An old Coddy conversation can call MCP tools after container recreation without
  a `session not found` failure.
- Automated tests pass and the manual handoff checklist is reproducible.
