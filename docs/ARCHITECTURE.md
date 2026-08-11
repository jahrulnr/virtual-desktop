# Architecture

## Requirements and decisions

Relay supplies one real Linux desktop that an AI operator and a human viewer see
and control without switching sessions. The browser client must be embeddable,
human takeover must be immediate, agent input must be machine-addressable, the
cursor must feel native, and runtime-installed GUI/Electron applications and user
files must survive an ordinary container recreation.

The brief leaves identity, tenancy, Internet exposure, GPU/audio, and retention
policy unspecified. This implementation therefore chooses a local, single-user
demo boundary: one container/session, CPU graphics, no audio, unrestricted normal
outbound browsing, and a port published only on `127.0.0.1`. Production identity,
per-tenant scheduling, TLS, egress policy, secret injection, and retention are
explicit follow-up work rather than silent assumptions.

## Process layout

```text
browser / host AI client
        |
        | HTTP + WebSocket on 127.0.0.1:3000
        v
      nginx :8080
       |        |             |
       |        |             +--> static control deck + noVNC modules
       |        +--> control API :8000 (dedicated UID 1001)
       |                  |        |        |
       |                  |        |        +--> UID-1000 adapter --> AT-SPI tree
       |                  |        +--> scrot framebuffer capture
       |                  +--> xdotool/XTEST after agent lease validation
       |                           |
       +--> websockify :6080       v
                  |           Xvfb :0 + XFCE + desktop applications
                  v                ^
             x11vnc :5900 ---------+

control API -- private Unix socket --> exact-plan install broker (root) --> apt/dpkg
desktop apps (UID 1000) --> /home/desktop named volume
install broker (root)   --> /var/lib/relay named volume
```

Supervisor keeps the container's deliberately small process set together. Xvfb
provides a deterministic 1440x900 X11 screen; XFCE provides familiar
window management; Chromium is the included browser and launches with its own SUID
sandbox enabled. Nginx is the only published service and keeps the control API,
WebSocket stream, web client, and noVNC modules on one origin.

## Display and streaming choice

The scoped build uses X11 + x11vnc + websockify + the noVNC JavaScript client.
x11vnc exports the same X server used by applications and accepts multiple shared
viewers. noVNC exposes `viewOnly` at runtime, so every browser starts as an observer
and only the browser holding the human lease sends VNC input. AI input reaches the
same X server through XTEST. This makes takeover a policy change, not a second
desktop or a reconnect.

This choice favors reach and operational simplicity for demos:

| Option | Strength | Cost / reason not selected for v1 |
| --- | --- | --- |
| x11vnc + noVNC | Mature browser support, one port, shared clients, simple embedding and debugging | More latency/bandwidth than video codecs; no audio |
| KasmVNC | Better compression, modern browser-focused VNC features, mature container-desktop base | Larger and more opinionated integration than this scoped reference needs |
| Selkies WebRTC | Low latency, audio, video/GPU-friendly codecs | ICE/TURN, NAT traversal, signaling, and more moving parts for a loopback demo |

The stream boundary is replaceable: Selkies is the recommended next step for
high-motion/video or WAN use, while the lease and agent APIs remain unchanged.

## Input, grounding, and cursor

Agent input is a typed, bounded JSON action batch. The unprivileged API validates
screen coordinates, key names, text lengths, click counts, scroll deltas, batch
size, and the live lease before constructing `xdotool` argument arrays. It never
passes operator values through a shell. xdotool uses the XTEST extension, so the
window system and applications receive ordinary pointer and keyboard events.

Grounding is hybrid:

1. Query `/api/v1/accessibility` first for roles, names, bounds, states, and actions.
2. Use `/api/v1/screenshot` for canvas, image-only, inaccessible, or Electron UI
   that does not expose enough AT-SPI semantics.
3. Confirm consequential state changes visually or through accessibility state.

This is more reliable and token-efficient than pure screenshots, while retaining
coverage where Linux accessibility bridges are incomplete. Chromium is started
with renderer accessibility forced on. The snapshot is capped at 1,000 nodes to
bound work and response size.

The cursor is the real X cursor. x11vnc is configured to draw it into the streamed
framebuffer (`-nocursorshape -cursor most`) rather than asking each client to render
a synthetic cursor. Agent moves, human moves, and recordings of the VNC stream
therefore agree on one pointer position. (The separate scrot API image omits the
cursor.) That small amount of extra encoded pixel damage is
worth the stronger “real OS access” illusion and avoids a duplicate/teleporting
client overlay during handoff.

## Arbitration and handoff

There is one lease with owner `none`, `agent`, or `human`. Agent leases last 12
seconds, human leases 30 seconds, and active clients heartbeat. A human claim
always preempts an agent. An agent cannot preempt a human or another agent. Once
preempted, the old agent's next input returns HTTP 409. noVNC input is also toggled
to view-only in the human client, so UI state matches server-side enforcement.

The VNC password also acts as the human-control capability. It remains only in the
host browser's memory and accompanies takeover, release, heartbeat, and approval
requests. The operator bearer token cannot mint a human approval. The API runs as
a separate `relayapi` UID; only that UID can read either API capability or connect
to the root broker socket. Desktop applications run as UID 1000 and cannot do so.

This is still cooperative arbitration for one trusted browser origin, not a hostile
multi-user security boundary. A production service needs authenticated viewer
identities and server-side authorization on the WebSocket path as well.

## Persistence

Persistence is the useful default for repeatable demos:

- `desktop-home` stores `/home/desktop`, including Downloads, browser profile,
  files, and user-local application state.
- `desktop-state` stores a root-owned manifest of successfully installed APT or
  `.deb` plans. Entrypoint replay restores them into a newly created container.
- A `.deb` plan contains its resolved path and SHA-256 digest. Replay stops if the
  source file is gone or changed.
- `docker compose down` preserves both volumes; `docker compose down -v` is the
  explicit full reset.

## Reference implementations

Research informed the boundaries rather than being copied wholesale:

- [LinuxServer Webtop](https://github.com/linuxserver/docker-webtop) validates the
  containerized-desktop pattern and currently uses Selkies. Relay reuses the
  supervised single-container shape, but not its broad runtime flags or UI.
- [Selkies](https://github.com/selkies-project/selkies) is the preferred future
  streaming upgrade for WebRTC/audio/GPU sessions.
- [KasmVNC](https://github.com/kasmtech/KasmVNC) demonstrates browser-oriented VNC
  hardening and multi-client operation; Relay uses distro noVNC/x11vnc for a
  smaller source-visible implementation.
- [Anthropic's computer-use demo](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo)
  validates Xvfb, x11vnc, noVNC, scrot, and xdotool as an agent desktop stack.
  Relay adds explicit leases, human preemption, a bounded API, accessibility
  grounding, and a confirmation broker.
- [Cua](https://github.com/trycua/cua) informed the hybrid screenshot/accessibility/
  action abstraction; Relay keeps its own narrow, auditable protocol.

The relevant upstream mechanisms are documented in the
[noVNC RFB API](https://github.com/novnc/noVNC/blob/master/docs/API.md) and
[x11vnc project](https://github.com/LibVNC/x11vnc).
