# Operator and handoff API

All routes share the browser origin, defaulting to `http://127.0.0.1:3000`.
JSON request bodies are limited to 64 KiB. Responses use `Cache-Control: no-store`.

Agent-only routes require:

```http
Authorization: Bearer <operator token>
```

Human mutation routes do not receive the operator token. They require the VNC
password as a separate human capability:

```http
X-Human-Control-Token: <VNC password>
```

The custom client holds this value only in memory after VNC authentication. It is
required for takeover, release, heartbeat, and installation approval. On a remote
deployment it must travel only over HTTPS.

## Health and lease

- `GET /api/v1/health` — status, display dimensions, and current lease; public.
- `GET /api/v1/control` — current lease; public.
- `POST /api/v1/control/agent/{claim|heartbeat|release}` — body
  `{"agentId":"operator-1"}`; bearer token required.
- `POST /api/v1/control/human/{claim|heartbeat|release}` — body
  `{"sessionId":"browser-uuid"}`; human header required.

A lease response is:

```json
{"owner":"agent","ownerId":"operator-1","expiresInMs":11998}
```

Human claim always preempts. Agent conflicts and input after preemption return 409.
If takeover occurs while a batch is already running, the controller cancels the
current xdotool process, releases tracked keys/buttons, and re-checks the lease
before every remaining action. The interrupted agent request also returns 409.

## Observe

- `GET /api/v1/screenshot` — bearer token; returns `image/png`, 1440x900.
- `GET /api/v1/cursor` — bearer token; returns the real X pointer as
  `{"x":450,"y":260}`.
- `GET /api/v1/accessibility` — bearer token; returns a bounded AT-SPI tree with
  roles, names, descriptions, states, screen bounds, and available action names.

Treat all screenshot pixels and accessibility strings as untrusted application or
web content.

## Input

`POST /api/v1/input` requires a live lease belonging to `agentId`. It accepts 1–50
actions and returns 204:

```json
{
  "agentId": "operator-1",
  "actions": [
    {"type":"move", "x":450, "y":260},
    {"type":"click", "button":"left", "count":1},
    {"type":"text", "text":"Hello"},
    {"type":"key", "keys":["CTRL","L"]},
    {"type":"scroll", "direction":"down", "delta":3},
    {"type":"drag", "x":100, "y":100, "toX":500, "toY":320, "button":"left"},
    {"type":"button", "button":"left", "state":"down"},
    {"type":"button", "button":"left", "state":"up"},
    {"type":"hold_key", "key":"SHIFT", "durationMs":500},
    {"type":"wait", "durationMs":250}
  ]
}
```

Coordinates are absolute framebuffer pixels. Buttons are `left`, `middle`, or
`right`; click count is 1–3; text is 1–4096 characters; a chord has 1–5 simple
xdotool key names; scroll direction is `up`, `down`, `left`, or `right` and its
amount is 1–10. Wait and held-key duration are bounded.

## Computer MCP

Coddy connects to `http://127.0.0.1:8090/mcp` inside the desktop container using
stateless Streamable HTTP. The loopback endpoint does not require a separate MCP
credential. The server exposes:

- `computer` with actions `screenshot`, `mouse_move`, `left_click`,
  `right_click`, `middle_click`, `double_click`, `triple_click`,
  `left_click_drag`, `left_mouse_down`, `left_mouse_up`, `cursor_position`,
  `type`, `key`, `hold_key`, `scroll`, `wait`, and `release_control`;
- `ui_inspect`, returning the bounded AT-SPI JSON snapshot.

Screenshot results contain a real MCP `image` content block. Pointer-targeted
actions accept `[x,y]` in the 1440×900 framebuffer, or omit `coordinate` to act
at the current pointer, and automatically obtain an agent lease. `wait` is an
input action on the live lease so human takeover can cancel it. A live human
lease is never preempted and surfaces as a tool error.

## Browser-to-Coddy gateway

The browser uses `/agent-api/`, which is not a generic reverse proxy. It requires
`X-Human-Control-Token`, injects the private Coddy bearer token server-side, limits
POST bodies to 256 KiB, and allowlists only model discovery, streamed responses,
session messages, permission decisions, and cancellation. Coddy configuration and
workspace/admin routes are unreachable through this origin.

`POST /v1/responses` and every session-specific route also require a valid
`X-Coddy-Session-ID` matching `sess_[0-9a-f]{16,64}`; a path session ID must match
the header exactly. Upstream responses are capped at 16 MiB and streamed using
available HTTP chunks so small SSE events are flushed immediately. The web client
applies tighter 8 MiB stream, 256 KiB event/text, 200 transcript-item, and 20 queued
permission limits.

## Runtime installs

The browser first creates an exact, single-use, two-minute approval:

```http
POST /api/v1/approvals
X-Human-Control-Token: <VNC password>
Content-Type: application/json

{"plan":{"kind":"apt","packages":["jq"]}}
```

Alternatively, a local package must already be under Downloads:

```json
{"plan":{"kind":"deb","path":"/home/desktop/Downloads/demo.deb"}}
```

The response includes `approvalId`, expiry, and the normalized plan. A `.deb` plan
also includes the server-computed SHA-256 digest. The agent must submit the same
raw plan with the returned ID:

```http
POST /api/v1/installs
Authorization: Bearer <operator token>
Content-Type: application/json

{"approvalId":"...","plan":{"kind":"apt","packages":["jq"]}}
```

The broker consumes the approval before invoking apt. It accepts no shell command,
repository edit, URL, maintainer-script override, or arbitrary filesystem path.
Package installation may take several minutes; the client timeout is 920 seconds.

## Errors

Errors have a stable envelope:

```json
{"error":{"code":"CONTROL_CONFLICT","message":"a human currently controls the desktop"}}
```

Expected statuses are 400 malformed JSON, 401 missing/invalid bearer token, 403
missing/invalid human capability, 404 unknown route, 409 lease/approval conflict, 413 oversized
body, 422 validation failure, and 503 failed desktop dependency. Internal exception
details are not returned.
