#!/bin/sh
set -eu

curl --fail --silent http://127.0.0.1:8080/api/v1/health >/dev/null
curl --fail --silent http://127.0.0.1:8090/healthz >/dev/null
curl --fail --silent \
  -H "Authorization: Bearer ${CODDY_HTTP_TOKEN}" \
  http://127.0.0.1:12345/v1/models >/dev/null
