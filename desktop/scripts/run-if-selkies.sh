#!/bin/sh
set -eu
if [ "${RELAY_STREAMING:-vnc}" != "selkies" ]; then
  exit 0
fi
exec "$@"
