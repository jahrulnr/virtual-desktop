#!/bin/sh
set -eu
if [ "${RELAY_STREAMING:-vnc}" != "vnc" ]; then
  exit 0
fi
exec "$@"
