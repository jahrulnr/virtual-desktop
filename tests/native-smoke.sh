#!/bin/sh
# Live checks for the Docker-less native runtime (Xvfb :99).
# Skips Coddy, AT-SPI, Chromium, the install broker, and Selkies.
set -eu

relay_base=${RELAY_BASE_URL:-http://127.0.0.1:8080}
relay_token=${RELAY_TOKEN:-test-control-token}
relay_human=${RELAY_HUMAN_TOKEN:-testtest}
relay_display=${RELAY_DISPLAY:-:99}
relay_auth="Authorization: Bearer $relay_token"
relay_human_auth="X-Human-Control-Token: $relay_human"

curl -fsS "$relay_base/api/v1/health" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="ok"; assert data["display"]=={"width":1440,"height":900}; assert "recording" in data'
curl -fsS "$relay_base/metrics" | rg -q 'relay_info'

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"native-smoke"}' \
  "$relay_base/api/v1/control/agent/claim" >/dev/null

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"native-smoke","actions":[{"type":"move","x":400,"y":300}]}' \
  "$relay_base/api/v1/input" >/dev/null

relay_cursor=$(DISPLAY=$relay_display xdotool getmouselocation --shell)
echo "$relay_cursor" | rg -q '^X=400$'
echo "$relay_cursor" | rg -q '^Y=300$'

curl -fsS -X POST \
  -H "$relay_human_auth" -H 'Content-Type: application/json' \
  -d '{"sessionId":"native-smoke-browser"}' \
  "$relay_base/api/v1/control/human/claim" >/dev/null

relay_status=$(curl -sS -o /tmp/relay-native-conflict.json -w '%{http_code}' \
  -X POST -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"native-smoke","actions":[{"type":"click"}]}' \
  "$relay_base/api/v1/input")
[ "$relay_status" = 409 ]

curl -fsS -X POST \
  -H "$relay_human_auth" -H 'Content-Type: application/json' \
  -d '{"sessionId":"native-smoke-browser"}' \
  "$relay_base/api/v1/control/human/release" >/dev/null

curl -fsS -H "$relay_auth" "$relay_base/api/v1/screenshot" -o /tmp/relay-native-smoke.png
python3 -c '
from pathlib import Path
data = Path("/tmp/relay-native-smoke.png").read_bytes()
assert data.startswith(b"\x89PNG"), data[:16]
assert b"IHDR" in data[:24]
width = int.from_bytes(data[16:20], "big")
height = int.from_bytes(data[20:24], "big")
assert (width, height) == (1440, 900), (width, height)
'

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"native-smoke"}' \
  "$relay_base/api/v1/control/agent/claim" >/dev/null

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/recording/start" >/dev/null
sleep 1
curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"agentId":"native-smoke","actions":[{"type":"move","x":1100,"y":700}]}' \
  "$relay_base/api/v1/input" >/dev/null
sleep 1
relay_recording_result=$(curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/recording/stop")
relay_recording_path=$(printf '%s' "$relay_recording_result" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert data["status"]=="saved"; assert data["sizeBytes"]>0; print(data["path"])')
ffprobe -v error \
  -show_entries stream=width,height \
  -of csv=p=0:s=x \
  "$relay_recording_path" | rg -q '^1440x900$'
relay_recording_directory=$(dirname "$relay_recording_path")
relay_recording_stem=$(basename "$relay_recording_path" .mp4)
relay_raw_path="$relay_recording_directory/.$relay_recording_stem.source.mp4"
if [ -e "$relay_raw_path" ]; then
  echo "raw framebuffer capture was published after showcase rendering" >&2
  exit 1
fi

curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/terminals/native-smoke/destroy" >/dev/null || true
curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{"name":"native-smoke"}' \
  "$relay_base/api/v1/terminals" >/dev/null
curl -fsS -H "$relay_auth" "$relay_base/api/v1/terminals" \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); assert any(item["name"]=="native-smoke" for item in data["sessions"])'
curl -fsS -X POST \
  -H "$relay_auth" -H 'Content-Type: application/json' \
  -d '{}' \
  "$relay_base/api/v1/terminals/native-smoke/destroy" >/dev/null

curl -fsS http://127.0.0.1:8090/healthz | rg -q '"status":"ok"'
curl -fsSI "$relay_base/" | rg -qi '^Content-Security-Policy:'

echo "Native smoke checks passed"
