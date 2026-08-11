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

## Observe

- `GET /api/v1/screenshot` — bearer token; returns `image/png`, 1440x900.
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
    {"type":"scroll", "delta":-3}
  ]
}
```

Coordinates are absolute framebuffer pixels. Buttons are `left`, `middle`, or
`right`; click count is 1–3; text is 1–4096 characters; a chord has 1–5 simple
xdotool key names; scroll is -10..10 excluding zero.

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
