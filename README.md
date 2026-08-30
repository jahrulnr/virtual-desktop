# Relay AI Desktop + Coddy Agent

One Linux desktop, shared by a human and an AI operator, packaged as one
ready-to-run Docker container with Coddy and an OpenAI-compatible model gateway.

![Relay AI Desktop in observer mode, with a real Linux cursor and Take control button](docs/assets/relay-desktop.png)

Relay packages a complete XFCE desktop into one Docker container and streams it
to the browser. An AI can inspect and operate that same 1440×900 session through
a bounded API; a human can take over instantly, work with the real keyboard and
pointer, then hand the session back without reconnecting or losing application
state.

It is built for live demos of web, Linux, and Electron applications where the
audience needs to see what the agent sees—and step in when judgment matters.

## What works today

- A real Debian 12 + XFCE desktop rendered by Xvfb and streamed through noVNC.
- Shared viewing with explicit AI/human control leases and immediate human
  preemption.
- A real OS cursor baked into the stream, including while the browser is in
  observer mode.
- Human-like AI pointer motion with friction-style acceleration/deceleration and
  interruptible, character-paced text entry.
- Hybrid agent grounding: bounded AT-SPI accessibility snapshots plus PNG
  screenshots for visual or canvas-based interfaces.
- Validated XTEST mouse and keyboard input; no arbitrary shell endpoint.
- Chromium, Terminal, and Files included, with guarded APT or local `.deb`
  installation for runtime apps such as Electron packages.
- Headed Playwright MCP controlling the same visible Chromium profile, with
  browser DOM, console, and network debugging available to Coddy.
- A calm local `index.html` start page in Chromium, with the empty bookmarks bar
  hidden so the browser opens ready for work.
- A quiet stage with only centered **Take control**; the lease, tools, and
  activity live in a sidebar, while an automatic 200% showcase camera follows
  every successful AI pointer action without adding another agent tool.
- Persistent home, a shared `~/workspace` the human can browse, approved-install
  state, and Coddy conversations across normal container recreation.
- An in-container `os-operator` skill and `relayctl.py` client for AI agents.
- A pinned [Coddy Agent](https://github.com/coddy-project/coddy-agent) Go binary,
  persistent conversations, and a first-party Go MCP computer server.
- A tablet/desktop Coddy flight-recorder panel with task streaming, tool
  activity, stop controls, and explicit permission decisions.

## Quick start

You need Docker Engine with Compose, an OpenAI-compatible API key, and roughly
3 GB of image space.

```bash
git clone https://github.com/jahrulnr/virtual-desktop.git
cd virtual-desktop
cp .env.example .env
# Edit OPENAI_API_KEY and, when needed, OPENAI_BASE_URL / OPENAI_MODEL.
docker compose up -d --build
```

Open <http://127.0.0.1:3000>, enter the local VNC password `testtest`, and click
**Open desktop**. The browser begins in observer mode; click **Take control** only
when you want keyboard and pointer events to enter the desktop.

Open the **C** button to give Coddy an outcome. Clicking **Run task** explicitly
releases your human lease, then Coddy observes and operates the same desktop. The
human can still preempt it at any moment with **Take control**.

OpenRouter is one supported example:

```dotenv
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-replace-me
OPENAI_MODEL=openai/gpt-4o
```

Any gateway that implements the OpenAI chat-completions contract can be used. A
multimodal model is strongly recommended because inaccessible canvas and Electron
surfaces require screenshots.

The included VNC, control, and Coddy credentials are predictable local fixtures.
The port is bound to loopback. Override them in `.env` when you want your own
values:

```bash
VNC_PASSWORD='replace-with-at-least-8-characters' \
CONTROL_TOKEN='replace-with-at-least-32-random-characters' \
CODDY_HTTP_TOKEN='replace-with-at-least-32-random-characters' \
docker compose up -d --build
```

Relay rejects a VNC password shorter than 8 characters and an operator token
shorter than 12. Neither value is printed in the container logs.

## Control handoff

Every viewer sees the same framebuffer, windows, and OS cursor. The control model
changes who may send input, not which desktop they are connected to.

1. The browser opens view-only behind a transparent input shield. Its ordinary
   browser cursor remains visible and cannot accidentally reach noVNC.
2. An AI claims a short lease and sends bounded input through the control API.
3. Clicking the centered **Take control** button (or pressing `Alt+Shift+C`)
   preempts that AI lease, stops an in-flight Coddy turn, removes the shield,
   and lets noVNC capture the human pointer, keyboard, and clipboard. Lease
   details and the rest of the session chrome stay in the sidebar.
4. Clicking **Release** or pressing `Alt+Shift+C` again returns the browser to
   observer mode. The AI can claim a fresh lease and continue from the exact same
   screen.

Human claims always win. A preempted agent receives HTTP 409 on its next heartbeat
or input request, so a well-behaved operator stops immediately.

## Operating the desktop with Coddy or another AI

Coddy reaches the desktop through an internal Streamable HTTP MCP server. Its
`computer` tool exposes screenshot, smooth pointer movement, clicks and drag,
mouse down/up, cursor position, typing, key chords, hold-key, four-direction
scroll, wait, and release-control. The runtime automatically moves its activity-driven 200%
showcase camera after successful pointer actions, so the AI does not select or
manage a separate presentation tool. Camera retargets ease for 240 ms from the
currently visible position and are baked into saved 30 fps recordings. Click and
scroll may omit coordinates to act at the current pointer. Pointer paths use a friction-like ease-in/ease-out curve;
text is sent as small blocking deltas, preferring word boundaries, with a 50 ms
per-character delay. MCP clicks and key chords leave a short blocking settle
pause so window and page transitions remain legible. `wait` holds the agent lease
so a human takeover can cancel it. `ui_inspect` returns a bounded AT-SPI tree.

For browser work, Coddy also has a `playwright` MCP server on container loopback.
Use it for DOM locators, browser console/network inspection, and browser-level
debugging; use `computer` for the shared OS surface. Playwright launches the
headed Chromium window visible in the same framebuffer and keeps its profile in
the persistent desktop home volume.

Coddy handles model, session, and tool orchestration while the small Go MCP
process owns the stable computer-use contract. Both run in the desktop container,
so there is one lifecycle to operate while the code boundary remains replaceable.

The same MCP server also publishes a second, bearer-token listener at
`127.0.0.1:8091` so agents outside the container (an editor assistant, another
orchestrator, NusaShell) can operate the desktop with the same tools. Set
`MCP_AUTH_TOKEN` in `.env`; the external listener refuses to start without a
token of at least 16 characters. The token-free internal listener keeps the
pinned Coddy configuration unchanged. See [the API reference](docs/API.md).

The image installs the agent skill at
`/home/desktop/.agents/skills/os-operator`. Its helper wraps lease management,
screenshots, accessibility, input, and approved installs:

```bash
docker compose exec -T desktop sh -lc '
  export RELAY_OPERATOR_TOKEN="$(cat /run/ai-desktop/operator-token)"
  cd /home/desktop/.agents/skills/os-operator
  python3 scripts/relayctl.py status
  python3 scripts/relayctl.py accessibility
  python3 scripts/relayctl.py claim --agent-id demo
  python3 scripts/relayctl.py input --agent-id demo --actions '\''[
    {"type":"move","x":420,"y":260},
    {"type":"click","button":"left"}
  ]'\''
  python3 scripts/relayctl.py release --agent-id demo
'
```

The intended operating loop is accessibility-first, vision as fallback, then a
small action batch followed by observation. Coordinates always refer to the
1440×900 framebuffer, not the browser-scaled canvas. The observer and saved MP4
apply the automatic camera around the current AI pointer without changing that
coordinate contract. The full wire contract is in [the API reference](docs/API.md).

## Installing desktop and Electron apps

The agent cannot approve its own package installation. A human opens the desktop
controls, approves an exact APT package list or a `.deb` already located under
`/home/desktop/Downloads`, then gives the short-lived approval ID to the operator.
The approval is single-use, expires after two minutes, and—for local packages—is
bound to the file's SHA-256 digest.

Successful install plans are recorded in a root-owned volume and replayed when a
fresh container is created. This makes demo machines convenient without turning
the control API into a root shell.

## Persistence and reset

`docker compose down` preserves the desktop home directory, browser profile,
Downloads, the shared `workspace` folder, user-local applications, approved-install
manifest, and Coddy session history. Bring the same session back with
`docker compose up -d`.

To deliberately erase all named volumes:

```bash
docker compose down -v
docker compose up -d --build
```

## Architecture at a glance

```text
browser ── noVNC/WebSocket ──┐
browser ── task/SSE ────────┼── one desktop container
                             ├── Xvfb :0 + XFCE + apps
                             ├── noVNC + bounded control API
                             ├── Go computer MCP
                             ├── headed Playwright MCP + Chromium
                             └── Coddy + persistent sessions
```

Nginx exposes one loopback origin. x11vnc, the Go MCP process, Coddy, and the AI
input adapter all run under Supervisor and talk to the same X11 session. A
server-side lease arbitrates control. Read [the architecture](docs/ARCHITECTURE.md)
for the tradeoffs against KasmVNC and WebRTC/Selkies.

## Validate a change

```bash
make test       # unit and API behavior
make static     # syntax, Compose, skill, and container invariants
make smoke      # live framebuffer, AT-SPI, input, and handoff checks
```

The manual two-controller walkthrough is in [docs/TESTING.md](docs/TESTING.md).

## Documentation

- [Architecture and design decisions](docs/ARCHITECTURE.md)
- [Operator and handoff API](docs/API.md)
- [Running Coddy with OpenAI-compatible providers](docs/CODDY.md)
- [Testing and manual control handoff](docs/TESTING.md)
- [Implementation specification](docs/SPEC.md)
- [Contributing](CONTRIBUTING.md)

## Project scope

Relay is a community desktop for local experiments and demos. Compose publishes
only to `127.0.0.1`; read the source and adapt the defaults before using it in a
different environment.

This project is released under the [MIT License](LICENSE).
