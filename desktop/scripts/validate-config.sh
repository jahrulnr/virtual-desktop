#!/bin/sh
set -eu

if [ -n "${VNC_PASSWORD:-}" ] && [ "${#VNC_PASSWORD}" -lt 8 ]; then
  echo "configuration error: VNC_PASSWORD must have at least 8 characters" >&2
  exit 64
fi

if [ -n "${CONTROL_TOKEN:-}" ] && [ "${#CONTROL_TOKEN}" -lt 12 ]; then
  echo "configuration error: CONTROL_TOKEN must have at least 12 characters" >&2
  exit 64
fi
