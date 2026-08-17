#!/bin/sh
set -eu

/opt/relay/scripts/wait-for-x.sh true

if ! command -v python3 >/dev/null; then
  echo "Selkies requires Python" >&2
  exit 1
fi

if ! python3 -c "import selkies" 2>/dev/null; then
  echo "Selkies package is not installed; set RELAY_STREAMING=vnc or build with INSTALL_SELKIES=true" >&2
  exit 1
fi

PORT="${SELKIES_PORT:-8082}"
MODE="${SELKIES_MODE:-websockets}"

exec python3 -m selkies \
  --addr 127.0.0.1 \
  --port "$PORT" \
  --mode "$MODE"
