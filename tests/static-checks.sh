#!/bin/sh
set -eu

python3 -m unittest discover -s tests -v
python3 -m compileall -q desktop
if command -v docker >/dev/null 2>&1; then
  docker compose config -q
  docker compose config --format json | python3 -c '
import json
import sys

config = json.load(sys.stdin)
assert set(config["services"]) == {"desktop"}, "community build must use one container"
environment = config["services"]["desktop"]["environment"]
assert len(environment["VNC_PASSWORD"]) >= 8, "default VNC_PASSWORD must be at least 8 characters"
assert len(environment["CONTROL_TOKEN"]) >= 12, "default CONTROL_TOKEN must be at least 12 characters"
assert len(environment["CODDY_HTTP_TOKEN"]) >= 16
'
else
  python3 -c '
import pathlib
import re
text = pathlib.Path("compose.yaml").read_text()
assert "127.0.0.1:3000:8080" in text
assert re.search(r"VNC_PASSWORD:.*testtest", text)
assert re.search(r"CONTROL_TOKEN:.*test-control-token", text)
assert "CODDY_HTTP_TOKEN" in text
print("compose.yaml fixtures checked without docker")
'
fi
VNC_PASSWORD=test CONTROL_TOKEN=test-control-token CODDY_HTTP_TOKEN=test-coddy-http-token-change-me \
  desktop/scripts/validate-config.sh >/dev/null 2>&1 && {
    echo "short VNC_PASSWORD unexpectedly passed validation" >&2
    exit 1
  }
VNC_PASSWORD=testtest CONTROL_TOKEN=test CODDY_HTTP_TOKEN=test-coddy-http-token-change-me \
  desktop/scripts/validate-config.sh >/dev/null 2>&1 && {
    echo "short CONTROL_TOKEN unexpectedly passed validation" >&2
    exit 1
  }
VNC_PASSWORD=testtest CONTROL_TOKEN=test-control-token CODDY_HTTP_TOKEN=test-coddy-http-token-change-me \
  desktop/scripts/validate-config.sh

for relay_script in desktop/scripts/*.sh tests/*.sh; do
  sh -n "$relay_script"
done

if rg -n -- '--privileged|pid: host|network_mode: host|/var/run/docker.sock|cap_add:' compose.yaml; then
  echo "unsafe container privilege or host integration found" >&2
  exit 1
fi

rg -q '127.0.0.1:3000:8080' compose.yaml
rg -q '127.0.0.1:8091:8091' compose.yaml
rg -q 'RELAY_MCP_EXTERNAL_LISTEN: "0.0.0.0:8091"' compose.yaml
rg -q 'MCP_AUTH_TOKEN' compose.yaml .env.example
rg -q 'NewExternalHTTPHandler' computer-mcp/internal/mcpserver/server.go
rg -q 'RELAY_MCP_EXTERNAL_LISTEN requires RELAY_MCP_TOKEN' computer-mcp/cmd/server/main.go
rg -q 'RELAY_MCP_EXTERNAL_LISTEN requires RELAY_MCP_TOKEN' desktop/scripts/validate-config.sh
rg -q 'Content-Security-Policy' desktop/config/nginx.conf
rg -q 'X-Content-Type-Options' desktop/config/nginx.conf
rg -Uq 'location ~ \\.mjs\$ \{[^}]*default_type application/javascript;' desktop/config/nginx.conf
rg -q '^user=relayapi$' desktop/config/supervisord.conf
rg -q '^COPY desktop/home/ /opt/relay/home-template/$' Dockerfile
rg -q '/opt/relay/home-template' desktop/scripts/entrypoint.sh
rg -q 'class="control-pill take-control"' web/index.html
rg -q 'class="observer-shield"' web/index.html
rg -qF 'Control+Enter Meta+Enter' web/index.html
rg -q 'navigator.clipboard' web/app.js
rg -q '/home/desktop/workspace' desktop/scripts/entrypoint.sh Dockerfile
rg -q 'relay-tmux' desktop/scripts/entrypoint.sh
rg -q 'Downloads/recordings' desktop/scripts/entrypoint.sh
rg -q 'chown desktop:relayaccess /home/desktop/Downloads/recordings' desktop/scripts/entrypoint.sh
rg -q 'chmod 2770 /home/desktop/Downloads/recordings' desktop/scripts/entrypoint.sh
rg -q 'chgrp relayaccess /home/desktop/Downloads' desktop/scripts/entrypoint.sh
rg -q '0751' desktop/scripts/entrypoint.sh
rg -q '^directory=/home/desktop/workspace$' desktop/config/supervisord.conf
rg -q 'aria-controls="control-drawer"' web/index.html
rg -q 'aria-controls="agent-drawer"' web/index.html
rg -q 'data-agent-open' web/index.html web/app.js web/styles.css
rg -q 'X-Human-Control-Token' desktop/control/agent_gateway.py
rg -q 'relay__computer' agent/skills/os-operator/SKILL.md
rg -q '2ba0ec9cc531e31954c2565b2984d92d4bc890d3' compose.yaml Dockerfile
rg -q '^\[program:computer-mcp\]$' desktop/config/supervisord.conf
rg -q '^\[program:coddy\]$' desktop/config/supervisord.conf
rg -q 'body\[data-owner="human-self"\].*release-control' web/styles.css
rg -q 'body\[data-owner="human-self"\].*observer-shield.*display: none' web/styles.css
rg -Uq '\.observer-shield \{[^}]*cursor: default;' web/styles.css
rg -q 'document.body.dataset.owner' web/app.js
rg -q 'id="mode-banner"' web/index.html
rg -q 'id="shortcuts-dialog"' web/index.html
rg -q 'id="new-agent-session"' web/index.html
rg -q 'id="session-meta"' web/index.html
rg -q 'runtime_status' computer-mcp/internal/mcpserver/server.go
rg -q 'path == "/api/v1/events"' desktop/control/api.py
rg -q 'events/stream' desktop/control/api.py
rg -q 'path == "/metrics"' desktop/control/api.py
rg -q '/api/v1/recording' desktop/control/api.py
rg -q 'api/v1/recordings/' desktop/control/api.py
rg -q 'RECORDING_NAME' desktop/control/api.py
rg -q 'video/mp4' desktop/control/api.py
rg -q '/api/v1/terminals' desktop/control/api.py
rg -q 'record_screen' computer-mcp/internal/mcpserver/server.go
rg -q 'Name:        "terminal"' computer-mcp/internal/mcpserver/server.go
rg -q 'RELAY_STREAMING' compose.yaml
rg -q 'location = /metrics' desktop/config/nginx.conf
rg -q 'location /selkies/' desktop/config/nginx.conf
rg -q 'id="start-recording"' web/index.html
rg -q 'id="activity-log"' web/index.html
rg -q 'EventSource\("/api/v1/events/stream"\)' web/app.js
rg -qF -- '--addr 127.0.0.1' desktop/scripts/start-selkies.sh
rg -q 'connectSelkies' web/app.js
rg -q 'RELAY_NATIVE_DISPLAY:-99' desktop/scripts/run-native.sh
rg -q 'native-smoke' Makefile
if rg -n 'TODO|\[TODO' desktop/home/.agents/skills/os-operator; then
  echo "unfinished OS operator skill scaffold found" >&2
  exit 1
fi
if rg -n 'Openbox|Tint2|control-rail|console-shell' web README.md docs; then
  echo "stale legacy desktop or web-shell references found" >&2
  exit 1
fi
rg -q -- '--no-sandbox' desktop/scripts/start-desktop.sh && {
  echo "Chromium sandbox must not be disabled" >&2
  exit 1
}

if command -v node >/dev/null 2>&1; then
  node --check web/app.js
  node --check web/agent-view.mjs
  node --test tests/web-agent-view.test.mjs
fi

echo "Static checks passed"
