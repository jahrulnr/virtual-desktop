#!/bin/sh
set -eu

python3 -m unittest discover -s tests -v
python3 -m compileall -q desktop
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
rg -q 'Content-Security-Policy' desktop/config/nginx.conf
rg -q 'X-Content-Type-Options' desktop/config/nginx.conf
rg -Uq 'location ~ \\.mjs\$ \{[^}]*default_type application/javascript;' desktop/config/nginx.conf
rg -q '^user=relayapi$' desktop/config/supervisord.conf
rg -q '^COPY desktop/home/ /opt/relay/home-template/$' Dockerfile
rg -q '/opt/relay/home-template' desktop/scripts/entrypoint.sh
rg -q 'class="control-pill take-control"' web/index.html
rg -q 'class="observer-shield"' web/index.html
rg -q 'aria-controls="control-drawer"' web/index.html
rg -q 'aria-controls="agent-drawer"' web/index.html
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
rg -q 'GET /api/v1/events' desktop/control/api.py
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
