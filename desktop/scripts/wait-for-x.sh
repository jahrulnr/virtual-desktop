#!/bin/sh
set -eu

relay_attempt=0
until xdpyinfo -display "${DISPLAY:-:0}" >/dev/null 2>&1; do
  relay_attempt=$((relay_attempt + 1))
  if [ "$relay_attempt" -ge 100 ]; then
    echo "X display did not become ready" >&2
    exit 1
  fi
  sleep 0.1
done
exec "$@"
