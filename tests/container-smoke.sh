#!/bin/sh
set -eu

relay_base=${RELAY_BASE_URL:-http://127.0.0.1:3000}
docker compose up -d --no-recreate

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

relay_process_attempt=0
until docker compose exec -T desktop ps -eo user,args \
  | rg -q '^desktop +/usr/lib/chromium/chromium'; do
  relay_process_attempt=$((relay_process_attempt + 1))
  if [ "$relay_process_attempt" -ge 20 ]; then
    echo "Chromium did not become ready" >&2
    exit 1
  fi
  sleep 1
done
relay_processes=$(docker compose exec -T desktop ps -eo user,args)
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

curl -fsSI "$relay_base/" | rg -qi '^Content-Security-Policy:'

echo "Container smoke checks passed"
