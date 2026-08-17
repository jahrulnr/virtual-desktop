#!/bin/sh
# Temporary host runtime for environments without Docker.
# Starts an isolated Xvfb :99 desktop so it does not attach to an existing
# session such as Cloud Agent TigerVNC on :1. Coddy, the install broker, and
# Selkies are skipped.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
RUNTIME=${RELAY_NATIVE_RUNTIME:-/tmp/relay-native}
DISPLAY_NUM=${RELAY_NATIVE_DISPLAY:-99}
export DISPLAY=":${DISPLAY_NUM}"
export WIDTH=${WIDTH:-1440}
export HEIGHT=${HEIGHT:-900}
export RELAY_NATIVE=1
export RELAY_STREAMING=vnc
export RELAY_DESKTOP_USER=${RELAY_DESKTOP_USER:-$(id -un)}
export RELAY_DESKTOP_HOME=${RELAY_DESKTOP_HOME:-${HOME:-/tmp}}
export RELAY_RECORDING_DIR=${RELAY_RECORDING_DIR:-$RUNTIME/recordings}
export RELAY_TMUX_SOCKET_DIR=${RELAY_TMUX_SOCKET_DIR:-$RUNTIME/tmux}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-$RUNTIME/xdg}
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export VNC_PASSWORD=${VNC_PASSWORD:-testtest}
export CONTROL_TOKEN=${CONTROL_TOKEN:-test-control-token}
export CODDY_HTTP_TOKEN=${CODDY_HTTP_TOKEN:-test-coddy-http-token-change-me}

HTTP_PORT=${RELAY_HTTP_PORT:-8080}
CONTROL_PORT=${RELAY_CONTROL_PORT:-8000}
MCP_PORT=${RELAY_MCP_PORT:-8090}
VNC_PORT=${RELAY_VNC_PORT:-5900}
WEBSOCKIFY_PORT=${RELAY_WEBSOCKIFY_PORT:-6080}
LISTEN="127.0.0.1:${HTTP_PORT}"

LOG_DIR=$RUNTIME/logs
PID_DIR=$RUNTIME/pids
NOVNC_ROOT=${RELAY_NOVNC_ROOT:-}
WEB_ROOT=$ROOT/web

usage() {
  echo "usage: $0 {start|stop|status|smoke}" >&2
  exit 64
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

running_pid() {
  name=$1
  pidfile=$PID_DIR/$name.pid
  if [ -f "$pidfile" ]; then
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

write_pid() {
  echo "$2" > "$PID_DIR/$1.pid"
}

start_bg() {
  name=$1
  shift
  if running_pid "$name" >/dev/null; then
    return 0
  fi
  mkdir -p "$LOG_DIR" "$PID_DIR"
  (
    exec "$@"
  ) >"$LOG_DIR/$name.log" 2>&1 &
  write_pid "$name" $!
}

kill_tree() {
  pid=$1
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
}

wait_http() {
  url=$1
  attempt=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 40 ]; then
      echo "timed out waiting for $url" >&2
      return 1
    fi
    sleep 0.25
  done
}

install_packages() {
  missing=
  need_cmd Xvfb || missing="$missing xvfb"
  need_cmd x11vnc || missing="$missing x11vnc"
  need_cmd nginx || missing="$missing nginx"
  need_cmd scrot || missing="$missing scrot"
  need_cmd xdpyinfo || missing="$missing x11-utils"
  need_cmd xdotool || missing="$missing xdotool"
  need_cmd ffmpeg || missing="$missing ffmpeg"
  need_cmd tmux || missing="$missing tmux"
  if [ -n "$missing" ]; then
    echo "installing native runtime packages:$missing"
    sudo apt-get update -qq
    # shellcheck disable=SC2086
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $missing
  fi
}

detect_novnc() {
  if [ -n "$NOVNC_ROOT" ] && [ -f "$NOVNC_ROOT/core/rfb.js" ]; then
    return 0
  fi
  for candidate in \
    /usr/share/novnc \
    /usr/local/novnc/noVNC-1.2.0 \
    /usr/local/novnc; do
    if [ -f "$candidate/core/rfb.js" ]; then
      NOVNC_ROOT=$candidate
      return 0
    fi
  done
  echo "noVNC core/rfb.js not found; install novnc or set RELAY_NOVNC_ROOT" >&2
  return 1
}

render_nginx() {
  detect_novnc
  sed \
    -e "s|@@PID_FILE@@|$RUNTIME/nginx.pid|g" \
    -e "s|@@LOG_DIR@@|$LOG_DIR|g" \
    -e "s|@@LISTEN@@|$LISTEN|g" \
    -e "s|@@CONTROL_PORT@@|$CONTROL_PORT|g" \
    -e "s|@@WEBSOCKIFY_PORT@@|$WEBSOCKIFY_PORT|g" \
    -e "s|@@NOVNC_ROOT@@|$NOVNC_ROOT|g" \
    -e "s|@@WEB_ROOT@@|$WEB_ROOT|g" \
    "$ROOT/desktop/config/nginx-native.conf" > "$RUNTIME/nginx.conf"
}

cmd_stop() {
  if [ -d "$PID_DIR" ]; then
    for name in nginx computer-mcp control-api websockify x11vnc xfwm4 xvfb dbus; do
      if pid=$(running_pid "$name"); then
        kill_tree "$pid"
      fi
    done
  fi
  pkill -f "Xvfb :${DISPLAY_NUM} " 2>/dev/null || true
  pkill -f "x11vnc .* -display :${DISPLAY_NUM} " 2>/dev/null || true
  pkill -f "python3 -m desktop.control.api" 2>/dev/null || true
  pkill -f "$RUNTIME/bin/relay-computer-mcp" 2>/dev/null || true
  pkill -f "nginx -c $RUNTIME/nginx.conf" 2>/dev/null || true
  pkill -f "websockify 127.0.0.1:${WEBSOCKIFY_PORT} " 2>/dev/null || true
  pkill -f "xfwm4 --display :${DISPLAY_NUM} " 2>/dev/null || true
  sleep 0.3
  rm -f "$PID_DIR"/*.pid "$RUNTIME/nginx.pid" 2>/dev/null || true
}

cmd_status() {
  for name in dbus xvfb xfwm4 x11vnc websockify control-api computer-mcp nginx; do
    if pid=$(running_pid "$name"); then
      printf '%-14s running pid %s\n' "$name" "$pid"
    else
      printf '%-14s stopped\n' "$name"
    fi
  done
}

cmd_start() {
  install_packages
  mkdir -p \
    "$RUNTIME" "$LOG_DIR" "$PID_DIR" "$XDG_RUNTIME_DIR" \
    "$RELAY_RECORDING_DIR" "$RELAY_TMUX_SOCKET_DIR" \
    "$RELAY_DESKTOP_HOME/Downloads" "$RUNTIME/run" \
    "$LOG_DIR/nginx-body" "$LOG_DIR/nginx-proxy" \
    "$LOG_DIR/nginx-fastcgi" "$LOG_DIR/nginx-uwsgi" "$LOG_DIR/nginx-scgi"
  chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true

  printf '%s\n' "$CONTROL_TOKEN" > "$RUNTIME/run/operator-token"
  printf '%s\n' "$VNC_PASSWORD" > "$RUNTIME/run/human-token"
  chmod 600 "$RUNTIME/run/operator-token" "$RUNTIME/run/human-token"
  x11vnc -storepasswd "$VNC_PASSWORD" "$RUNTIME/run/vnc.pass" >/dev/null

  if ! running_pid dbus >/dev/null; then
    start_bg dbus dbus-daemon --session --nofork --address="unix:path=$XDG_RUNTIME_DIR/bus"
  fi
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

  if ! running_pid xvfb >/dev/null; then
    start_bg xvfb Xvfb "$DISPLAY" -screen 0 "${WIDTH}x${HEIGHT}x24" -dpi 96 -nolisten tcp -ac +extension RANDR
  fi
  "$ROOT/desktop/scripts/wait-for-x.sh" true

  if need_cmd xfwm4 && ! running_pid xfwm4 >/dev/null; then
    start_bg xfwm4 xfwm4 --display "$DISPLAY" --compositor=off
  fi

  if ! running_pid x11vnc >/dev/null; then
    start_bg x11vnc x11vnc \
      -display "$DISPLAY" \
      -rfbauth "$RUNTIME/run/vnc.pass" \
      -rfbport "$VNC_PORT" \
      -localhost -forever -shared -repeat -wait 10 -defer 10 \
      -nocursorshape -cursor most
  fi

  websockify_bin=websockify
  if python3 -c "import websockify" >/dev/null 2>&1; then
    websockify_bin="python3 -m websockify"
  fi
  if ! running_pid websockify >/dev/null; then
    # shellcheck disable=SC2086
    start_bg websockify $websockify_bin "127.0.0.1:${WEBSOCKIFY_PORT}" "127.0.0.1:${VNC_PORT}"
  fi

  if ! running_pid control-api >/dev/null; then
    start_bg control-api env \
      DISPLAY="$DISPLAY" \
      WIDTH="$WIDTH" \
      HEIGHT="$HEIGHT" \
      RELAY_NATIVE=1 \
      RELAY_STREAMING=vnc \
      RELAY_DESKTOP_USER="$RELAY_DESKTOP_USER" \
      RELAY_DESKTOP_HOME="$RELAY_DESKTOP_HOME" \
      RELAY_RECORDING_DIR="$RELAY_RECORDING_DIR" \
      RELAY_TMUX_SOCKET_DIR="$RELAY_TMUX_SOCKET_DIR" \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      PYTHONPATH="$ROOT" \
      python3 -m desktop.control.api \
        --host 127.0.0.1 \
        --port "$CONTROL_PORT" \
        --width "$WIDTH" \
        --height "$HEIGHT" \
        --token-file "$RUNTIME/run/operator-token" \
        --human-token-file "$RUNTIME/run/human-token" \
        --broker-socket "$RUNTIME/run/installer.sock" \
        --accessibility-socket "$RUNTIME/run/a11y.sock"
  fi

  mcp_bin=$RUNTIME/bin/relay-computer-mcp
  mkdir -p "$RUNTIME/bin"
  if [ ! -x "$mcp_bin" ]; then
    echo "building computer-mcp"
    (cd "$ROOT/computer-mcp" && go build -o "$mcp_bin" ./cmd/server)
  fi
  if ! running_pid computer-mcp >/dev/null; then
    start_bg computer-mcp env \
      RELAY_BASE_URL="http://127.0.0.1:${CONTROL_PORT}" \
      RELAY_OPERATOR_TOKEN="$CONTROL_TOKEN" \
      RELAY_AGENT_ID=native-agent \
      LISTEN_ADDR="127.0.0.1:${MCP_PORT}" \
      "$mcp_bin"
  fi

  render_nginx
  if ! running_pid nginx >/dev/null; then
    start_bg nginx nginx -c "$RUNTIME/nginx.conf" -p "$RUNTIME"
  fi

  wait_http "http://127.0.0.1:${HTTP_PORT}/api/v1/health"
  wait_http "http://127.0.0.1:${MCP_PORT}/healthz"
  echo "Relay native runtime is up on http://127.0.0.1:${HTTP_PORT} (DISPLAY=$DISPLAY)"
  echo "VNC password: $VNC_PASSWORD"
}

cmd_smoke() {
  cmd_start
  RELAY_BASE_URL="http://127.0.0.1:${HTTP_PORT}" \
  RELAY_TOKEN="$CONTROL_TOKEN" \
  RELAY_HUMAN_TOKEN="$VNC_PASSWORD" \
  RELAY_DISPLAY="$DISPLAY" \
    "$ROOT/tests/native-smoke.sh"
}

case ${1:-} in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  smoke) cmd_smoke ;;
  *) usage ;;
esac
