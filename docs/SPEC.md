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
- Make AI pointer travel blocking and visibly paced, with an acknowledged X11
  move at each interpolated point so long moves do not teleport between frames.
- Send AI text through bounded, interruptible deltas that prefer word boundaries
  and a 50 ms per-character xdotool delay so text entry looks like typing rather
  than a paste. Leave a short settle pause after discrete MCP clicks and key
  chords so visible state changes remain legible.
- Keep the browser pointer visible above a transparent observer shield; send input
  into noVNC only after **Take control** succeeds. The take-control action lives
  in the chrome so the framebuffer stays fully visible while monitoring.
- Keep the stage visually quiet: only the centered **Take control** action may
  sit over it. Put the lease card, handoff details, tools, activity, and Coddy
  task state in the static sidebar. Keep connection and showcase zoom state out
  of the user-facing chrome. An activity-driven 200% showcase camera must automatically
  follow successful AI pointer actions without adding an agent or human zoom
  control, and it must not change framebuffer coordinates. Retargeting must be
  interruptible and ease from the currently visible camera position; the saved
  30 fps recording must contain the same movement. Human takeover must restore
  1:1 framing before input becomes available.
- Launch the visible browser through a headed Playwright MCP server with a
  persistent profile and debug-capable browser tools, rather than starting a
  separate Chromium process directly.
- Share clipboard text between the browser and the desktop while a human lease is
  active.
- Allow approved APT packages and local `.deb` files to be installed at runtime.
- Persist desktop files, a shared `~/workspace`, successful install plans, and
  Coddy conversations across normal container recreation.
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
- **Browser automation:** Playwright owns the headed Chromium process and exposes
  its MCP endpoint only on the container loopback interface. The framebuffer
  remains the shared source of truth; Playwright is an additional DOM/debug
  surface, not a second browser session. A small local `index.html` is the
  initial page, and the empty bookmarks bar is hidden in the browser profile.

## Technology

- Debian 12 Bookworm and XFCE on a deterministic Xvfb display
- x11vnc + websockify + noVNC
- Headed Playwright MCP with the system Chromium executable
- nginx single-origin gateway
- Python standard-library control API and install broker
- xdotool/XTEST input, scrot screenshots, and AT-SPI inspection
- Coddy Agent pinned as the temporary Go harness
- Go MCP server exposing `computer` and `ui_inspect`
- Control runtime embedding an automatic pointer-following showcase camera
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
- Long AI pointer moves visibly traverse the framebuffer and finish only after
  the blocking input batch is complete; human takeover cancels the batch.
- AI text appears in short typing deltas and is interruptible by human takeover.
- The stage contains no floating session overlays beyond centered **Take control**.
  Successful AI pointer actions automatically move the 200% observer and recording
  camera without changing the 1440×900 input coordinate contract or requiring a
  separate tool, badge, or control.
- Playwright MCP is healthy on container loopback, controls the same visible
  browser profile, and exposes browser inspection/debug tools to Coddy.
- Human takeover causes later AI input to return HTTP 409 without changing the
  display session.
- AI input moves the real X pointer observed by every viewer.
- Screenshot and accessibility endpoints return bounded responses.
- Install requests fail without a matching human approval.
- Home files and Coddy sessions survive down/up; `down -v` resets them.
- An old Coddy conversation can call MCP tools after container recreation without
  a `session not found` failure.
- Automated tests pass and the manual handoff checklist is reproducible.
