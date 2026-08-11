# Testing and validation

## Automated checks

Run from the repository root:

```bash
make test
make static
docker compose up -d --build
make smoke
```

The default local VNC password is `testtest`; the matching operator fixture is
`test-control-token`. They are intentionally predictable and valid only while the
published port remains bound to loopback.

Unit tests cover lease expiration/preemption, validated input translation, API
authentication/error contracts, bounded accessibility serialization, exact package
approvals, expiry/single-use behavior, path confinement, and `.deb` replacement.
Static checks compile Python, parse Compose, syntax-check shell, require loopback
binding and security headers, reject dangerous host integration, and forbid
`--no-sandbox`. The live smoke test checks health, actual X pointer movement, human
preemption and 409 rejection, a 1440x900 screenshot, AT-SPI output, and response
security headers.

To inspect the final desktop image:

```bash
docker compose ps
docker compose exec -T desktop ps -eo user,pid,args
docker compose logs --no-color --tail=100 desktop
```

Chromium should run as `desktop`, have renderer/zygote children, and must not contain
`--no-sandbox`.

## Manual two-controller handoff

1. Start Relay and open `http://127.0.0.1:3000` in a browser. Enter the configured
   VNC password (`testtest` in the loopback-only Compose default). Leave the UI in
   observer mode.
2. In a terminal, read the local operator token and run the claim/input example in
   the README. Confirm the real cursor moves in the browser and the operator chip
   says **AI is operating**.
3. Start an agent heartbeat every five seconds:

   ```bash
   while true; do
     curl -fsS -X POST http://127.0.0.1:3000/api/v1/control/agent/heartbeat \
       -H "Authorization: Bearer $RELAY_TOKEN" \
       -H 'Content-Type: application/json' \
       -d '{"agentId":"demo-agent"}' >/dev/null || break
     sleep 5
   done
   ```

4. Click **Take control**. Confirm **Release control** appears, then type and move the
   mouse inside the desktop. The AI heartbeat/input must receive 409 and the browser
   remains on the same windows/session.
5. Click **Release control**. Have the agent claim again and move the pointer.
   Confirm the browser becomes view-only and immediately observes the agent's move.
6. Optional multi-viewer check: open a second browser/private window. Both should
   see the same desktop and real cursor; a takeover in either window makes the other
   observer-only on its next status refresh.

Pass means no reconnect/session replacement occurs, only one controller produces
input at a time through the provided clients, human preemption is immediate, and
the cursor is visually continuous across both directions of handoff.

## Persistence test

Create a harmless approved install (for example `jq`) through the UI and operator
API, verify it is present, then recreate the container without deleting volumes:

```bash
docker compose up -d --force-recreate
docker compose exec -T desktop jq --version
```

The approved install manifest is replayed at startup. Then verify the reset path:

```bash
docker compose down -v
docker compose up -d --build
```

The home profile, files, and install manifest should be absent after reset.
