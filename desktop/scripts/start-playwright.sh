#!/bin/sh
set -eu

/opt/relay/scripts/wait-for-x.sh /usr/bin/true
sleep 2
exec /usr/local/bin/node \
  /opt/playwright-mcp/node_modules/@playwright/mcp/cli.js \
  --config /etc/relay/playwright.json \
  --host 127.0.0.1 \
  --port 8931 \
  --shared-browser-context \
  --sandbox \
  --caps devtools
