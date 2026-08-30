# Architecture

Relay gives a human and an AI operator one shared Linux desktop. The browser is
embeddable, takeover does not create a second session, and applications installed
for a demo survive an ordinary container recreation.

The implementation assumes a community project used locally by one person or a
small demo group. Identity, fleet scheduling, GPU acceleration, audio, and WAN
streaming are outside this build. Compose publishes the UI on `127.0.0.1:3000`.

## One-container process layout

```text
browser -- HTTP/WebSocket --> nginx :8080
                                  |-- web client + noVNC
                                  |-- allowlisted Coddy gateway :8001
                                  |-- control API :8000
                                  `-- websockify -> x11vnc
                                                       |
                                                Xvfb :0 + XFCE
                                                       |
                                   Playwright MCP :8931
                                                        |
                                        Chromium, Files, Terminal,
                                        and runtime-installed apps

Coddy :12345 -- stateless MCP --> computer-mcp :8090 --> control API
external agent -- bearer-token MCP --> computer-mcp :8091 --> control API
```

Supervisor starts and watches every process in one image. Docker therefore has
one health check, one log stream, and one lifecycle command. The internal code is
still separated by purpose: Coddy owns conversations and the ReAct loop; the Go
MCP server owns computer-use tools; the control API owns leases and validated X11
input; nginx is the only host-facing process.

The MCP server listens only on `127.0.0.1` and uses stateless Streamable HTTP.
Coddy may reconnect or reuse a persisted conversation after `compose down` / `up`
without carrying an expired transport session ID. This directly avoids the stale
`session not found` failure that motivated the single-container rebuild.

The headed Playwright MCP server is a separate loopback service in the same
container. It launches the system Chromium executable with the persistent
desktop profile and debug capabilities, so browser DOM/console/network
observations and the noVNC framebuffer refer to one visible browser. Its init
page opens the local `index.html` start page, and startup profile preparation
hides the empty bookmarks bar without deleting saved bookmarks. It is not an
externally published debug port.

For agents outside the container, the same process opens an optional second
listener on `0.0.0.0:8091` behind a constant-time bearer-token check. It exposes
the identical tool surface; only the transport entry point differs. The token
boundary keeps the desktop reachable to external orchestrators without giving
unauthenticated host processes control of the session.

## Display and streaming

Relay uses X11 + Xvfb + x11vnc + websockify + noVNC. Applications, AI input, and
human input all meet at the same X server. noVNC can switch `viewOnly` at runtime,
so takeover changes who may send input without reconnecting the viewer.

| Option | Good fit | Why Relay does or does not use it |
| --- | --- | --- |
| x11vnc + noVNC | Local demos, browser embeds, shared viewers | Selected: easy to inspect and operate, with acceptable desktop latency |
| KasmVNC | A richer browser-first VNC stack | Useful, but larger and more opinionated than this source-visible reference needs |
| Selkies WebRTC | WAN, video, audio, or GPU-heavy sessions | Better media latency, but adds signaling and ICE/TURN work |

Selkies is the natural future streaming swap for high-motion workloads. The lease,
input, grounding, and Coddy contracts do not depend on VNC.

## Input, grounding, and cursor

The AI sends typed JSON actions. The control API checks screen coordinates, key
names, text length, scroll distance, action count, and the current lease before it
constructs `xdotool` argument arrays. XTEST then delivers normal pointer and
keyboard events to the desktop.

The Go MCP surface intentionally stays small:

- `computer` provides screenshot, smooth move, click variants, drag, mouse
  down/up, cursor position, typing, key chords, held keys, scroll, wait, and
  release-control;
- `ui_inspect` returns a bounded AT-SPI accessibility snapshot.

Showcase framing deliberately is not an MCP tool. The control runtime observes
successful pointer actions and moves an activity-driven 200% presentation camera around the
same coordinates, keeping camera decisions out of the model's tool-selection loop.

Grounding is hybrid. The operator should inspect AT-SPI first, use Playwright
snapshots for browser DOM/debug data, and use screenshots for canvas, images, or
incomplete Electron accessibility. Long pointer moves use a capped, blocking
quintic smootherstep path with a short wait between points inside the Go service,
so the model chooses an endpoint rather than generating animation frames. Text
is delivered as separate bounded deltas that prefer word boundaries, and the
controller types each character with a 50 ms delay. Discrete MCP clicks and key
chords add a short blocking settle pause; every X11 move waits for
acknowledgement before the next point.

Relay uses the real X cursor. x11vnc draws it into the streamed framebuffer, so AI
moves, human moves, and screen recordings agree on one pointer. In observer mode,
the web client adds a transparent shield above noVNC: the browser pointer remains
visible, but input cannot enter the desktop until the centered **Take control**
action succeeds. The lease card, activity, tools, and Coddy task state are static
sidebar content rather than floating overlays on the framebuffer. Connection and
showcase camera state remain available to the service/API without redundant
status badges in the user-facing shell. After each successful AI pointer action,
the control API publishes a `showcase.camera` event and the web observer smoothly
changes the transform origin to that framebuffer position with an interruptible
240 ms ease-out. Retargeting starts from the currently rendered position. Screen
recording samples the same curve on the 30 fps timeline and applies it during
mandatory FFmpeg post-processing, so the saved MP4 contains the framing while AI
coordinates remain unchanged. Human takeover switches to 1:1 without a
transition before noVNC input is exposed; release eases back to the showcase
view. Reduced-motion clients follow the same targets without animation.

## Control handoff

One lease has owner `none`, `agent`, or `human`. Agent leases last 12 seconds and
human leases last 30 seconds while active clients heartbeat. A human claim always
preempts the agent. The interrupted tool receives HTTP 409, any held input is
released, and both sides keep viewing the same applications and framebuffer.

In observer mode the stage keeps only the centered **Take control** action visible;
the sidebar contains the lease card and the rest of the session chrome. **Release**
lives in that sidebar and is shown only for the human lease. `Alt+Shift+C` toggles
the lease. Taking control also cancels an in-flight Coddy turn so the model does not
keep spending tokens against HTTP 409. Host and guest clipboards are synchronized
while the human lease is live.

## Persistence

Three named volumes keep useful community-demo state while the runtime remains one
container:

- `desktop-home` stores files, Downloads, browser data, user-local apps, and the
  shared agent workspace at `/home/desktop/workspace` (also `/workspace`);
- `desktop-state` stores successful approved-install plans for replay;
- `coddy-state` stores conversations and transcripts.

`docker compose down` preserves all three. `docker compose down -v` is the explicit
full reset. A local `.deb` replay also verifies its path and SHA-256 digest before
installation.

## Reference implementations

Research informed the shape rather than being copied wholesale:

- [LinuxServer Webtop](https://github.com/linuxserver/docker-webtop) demonstrates
  the supervised container-desktop pattern; current releases use Selkies.
- [Selkies](https://github.com/selkies-project/selkies) is the candidate streaming
  upgrade for WebRTC, audio, and GPU sessions.
- [KasmVNC](https://github.com/kasmtech/KasmVNC) demonstrates a browser-oriented
  VNC stack and shared viewing.
- [Anthropic's computer-use demo](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo)
  validates the Xvfb, x11vnc, noVNC, scrot, and xdotool combination. Relay adds
  explicit leases, human preemption, accessibility grounding, and persistence.
- [Cua](https://github.com/trycua/cua) informed the hybrid screenshot,
  accessibility, and action abstraction.
- [Agent-Go](https://github.com/forkbikash/agent-go) was evaluated as the temporary
  harness. Its small coding-agent core is approachable, but it would leave the
  browser session layer to this project.
- [Coddy Agent](https://github.com/coddy-project/coddy-agent) was selected because
  its Go harness already provides OpenAI-compatible providers, HTTP/SSE sessions,
  skills, permissions, and MCP. Relay pins one commit and carries one narrow image
  content patch.

The underlying client mechanisms are documented by the
[noVNC RFB API](https://github.com/novnc/noVNC/blob/master/docs/API.md) and the
[x11vnc project](https://github.com/LibVNC/x11vnc).
