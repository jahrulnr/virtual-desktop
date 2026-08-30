#!/bin/sh
set -eu

relay_base=${RELAY_BASE_URL:-http://127.0.0.1:3000}
docker compose up -d --no-recreate

curl -fsS "$relay_base/start-page/index.html" | rg -q 'Ready for the next task\.'
docker compose exec -T desktop python3 -c '
import json
from pathlib import Path
prefs = json.loads(Path("/etc/chromium/master_preferences").read_text())
assert prefs["bookmark_bar"]["show_on_all_tabs"] is False
assert prefs["session"]["restore_on_startup"] == 4
assert prefs["session"]["startup_urls"] == ["http://127.0.0.1:8080/start-page/index.html"]
'

relay_attempt=0
until curl -fsS "$relay_base/api/v1/health" >/dev/null 2>&1; do
  relay_attempt=$((relay_attempt + 1))
  if [ "$relay_attempt" -ge 30 ]; then
    docker compose logs --no-color --tail=120 desktop >&2
    exit 1
  fi
  sleep 1
done

relay_token=$(docker compose exec -T desktop sh -c 'cat /run/ai-desktop/operator-token')
relay_human_token=$(docker compose exec -T desktop sh -c 'cat /run/ai-desktop/human-token')
relay_auth="Authorization: Bearer $relay_token"
relay_human_auth="X-Human-Control-Token: $relay_human_token"

relay_approval_status=$(curl -sS -o /tmp/relay-smoke-human-auth.json -w '%{http_code}' \
  -X POST -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"plan":{"kind":"apt","packages":["jq"]}}' \
  "$relay_base/api/v1/approvals")
[ "$relay_approval_status" = 403 ]

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"container-smoke"}' \
  "$relay_base/api/v1/control/agent/claim" >/dev/null

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"container-smoke","actions":[{"type":"move","x":400,"y":300}]}' \
  "$relay_base/api/v1/input" >/dev/null

relay_cursor=$(docker compose exec -T desktop sh -c 'DISPLAY=:0 xdotool getmouselocation --shell')
echo "$relay_cursor" | rg -q '^X=400$'
echo "$relay_cursor" | rg -q '^Y=300$'

curl -fsS -X POST \
  -H "$relay_human_auth" -H 'Content-Type: application/json' \
  -d '{"sessionId":"container-smoke-browser"}' \
  "$relay_base/api/v1/control/human/claim" >/dev/null

relay_status=$(curl -sS -o /tmp/relay-smoke-conflict.json -w '%{http_code}' \
  -X POST -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"container-smoke","actions":[{"type":"click"}]}' \
  "$relay_base/api/v1/input")
[ "$relay_status" = 409 ]

curl -fsS -X POST \
  -H "$relay_human_auth" -H 'Content-Type: application/json' \
  -d '{"sessionId":"container-smoke-browser"}' \
  "$relay_base/api/v1/control/human/release" >/dev/null

curl -fsS -H "$relay_auth" "$relay_base/api/v1/screenshot" -o /tmp/relay-smoke.png
file /tmp/relay-smoke.png | rg -q 'PNG image data, 1440 x 900'

relay_playwright_attempt=0
until relay_playwright_init=$(docker compose exec -T desktop curl -isS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"relay-smoke","version":"1"}}}' \
  http://localhost:8931/mcp) && echo "$relay_playwright_init" | rg -q 'serverInfo'; do
  relay_playwright_attempt=$((relay_playwright_attempt + 1))
  if [ "$relay_playwright_attempt" -ge 30 ]; then
    echo "Playwright MCP did not become ready" >&2
    exit 1
  fi
  sleep 1
done

relay_playwright_session=$(echo "$relay_playwright_init" | sed -n 's/^mcp-session-id: //Ip' | tr -d '\r')
[ -n "$relay_playwright_session" ]
relay_playwright_initial=$(docker compose exec -T desktop curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "MCP-Session-ID: $relay_playwright_session" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"browser_snapshot","arguments":{}}}' \
  http://localhost:8931/mcp)
echo "$relay_playwright_initial" | rg -q 'Page URL: http://127.0.0.1:8080/start-page/index.html'
echo "$relay_playwright_initial" | rg -q 'Ready for the next task\.'
relay_playwright_navigation=$(docker compose exec -T desktop curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "MCP-Session-ID: $relay_playwright_session" \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"browser_navigate","arguments":{"url":"http://127.0.0.1:8080/"}}}' \
  http://localhost:8931/mcp)
echo "$relay_playwright_navigation" | rg -q 'Page URL: http://127.0.0.1:8080/'

relay_process_attempt=0
until docker compose exec -T desktop ps -eo user,args \
  | rg -q '^desktop +/usr/local/bin/node /opt/playwright-mcp/node_modules/@playwright/mcp/cli.js'; do
  relay_process_attempt=$((relay_process_attempt + 1))
  if [ "$relay_process_attempt" -ge 20 ]; then
    echo "Playwright browser did not become ready" >&2
    exit 1
  fi
  sleep 1
done
relay_processes=$(docker compose exec -T desktop ps -eo user,args)
echo "$relay_processes" | rg -q '^desktop +/usr/local/bin/node /opt/playwright-mcp/node_modules/@playwright/mcp/cli.js'
echo "$relay_processes" | rg -q '^desktop +/usr/lib/chromium/chromium'
echo "$relay_processes" | rg -q '^desktop +/usr/bin/xfce4-session'
echo "$relay_processes" | rg -q '^desktop +xfce4-panel'
echo "$relay_processes" | rg -q '^relayapi +/usr/bin/python3 -m control.api'
echo "$relay_processes" | rg -q '^relayapi +/usr/local/bin/relay-computer-mcp'
echo "$relay_processes" | rg -q '^coddy +/usr/local/bin/coddy http '
if echo "$relay_processes" | rg -q -- '--no-sandbox'; then
  echo "Chromium is running without its application sandbox" >&2
  exit 1
fi

relay_runtime_permissions=$(docker compose exec -T desktop stat -c '%U:%G %a %n' \
  /run/ai-desktop/operator-token /run/ai-desktop/human-token /run/ai-desktop/installer.sock)
echo "$relay_runtime_permissions" | rg -q '^relayapi:relayapi 600 /run/ai-desktop/operator-token$'
echo "$relay_runtime_permissions" | rg -q '^relayapi:relayapi 600 /run/ai-desktop/human-token$'
echo "$relay_runtime_permissions" | rg -q '^root:relayapi 660 /run/ai-desktop/installer.sock$'
docker compose exec -T --user desktop desktop sh -c \
  'test ! -r /run/ai-desktop/operator-token && test ! -r /run/ai-desktop/human-token && test ! -w /run/ai-desktop/installer.sock'
docker compose exec -T --user desktop desktop sh -c \
  'test -r /home/desktop/.agents/skills/os-operator/SKILL.md && \
   test -x /home/desktop/.agents/skills/os-operator/scripts/relayctl.py'

curl -fsS -H "$relay_auth" "$relay_base/api/v1/accessibility" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["role"] == "desktop frame"'

curl -fsS "$relay_base/metrics" | rg -q 'relay_info'
curl -fsS "$relay_base/api/v1/health" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert "recording" in data and "streaming" in data; assert data["showcase"]["zoom"] == 2.0; assert data["showcase"]["pivot"] == {"x": 400, "y": 300}'

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"container-smoke"}' \
  "$relay_base/api/v1/control/agent/claim" >/dev/null
curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/recording/start" >/dev/null
sleep 1
curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"container-smoke","actions":[{"type":"move","x":1100,"y":700}]}' \
  "$relay_base/api/v1/input" >/dev/null
sleep 1
relay_recording_result=$(curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/recording/stop")
relay_recording_path=$(printf '%s' "$relay_recording_result" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="saved"; assert data["sizeBytes"]>0; print(data["path"])')
docker compose exec -T desktop ffprobe -v error \
  -show_entries stream=width,height \
  -of csv=p=0:s=x \
  "$relay_recording_path" | rg -q '^1440x900$'
relay_recording_directory=$(dirname "$relay_recording_path")
relay_recording_stem=$(basename "$relay_recording_path" .mp4)
relay_raw_path="$relay_recording_directory/.$relay_recording_stem.source.mp4"
if docker compose exec -T desktop test -e "$relay_raw_path"; then
  echo "raw framebuffer capture was published after showcase rendering" >&2
  exit 1
fi

curl -fsSI "$relay_base/" | rg -qi '^Content-Security-Policy:'

echo "Container smoke checks passed"
