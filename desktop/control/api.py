#!/usr/bin/env python3
"""Single-origin HTTP contract for human handoff and AI desktop control."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .auth import secrets_match
from .domain import ConflictError, ControlLease, ValidationError
from .events import EventLog
from .input_controller import InputController, SubprocessRunner
from .metrics import MetricsRegistry
from .recording import RecordingConflictError, RecordingError, ScreenRecorder
from .tmux_bridge import TerminalError, TerminalValidationError, TmuxBridge


class Broker(Protocol):
    def request(self, document: dict[str, object]) -> dict[str, object]: ...


class ScreenshotSource(Protocol):
    def capture(self) -> bytes: ...


class AccessibilitySource(Protocol):
    def snapshot(self) -> dict[str, object]: ...


class CursorSource(Protocol):
    def position(self) -> dict[str, int]: ...


class BrokerClient:
    def __init__(self, path: str) -> None:
        self.path = path

    def request(self, document: dict[str, object]) -> dict[str, object]:
        payload = json.dumps(document).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(920)
            client.connect(self.path)
            client.sendall(payload)
            response = bytearray()
            while not response.endswith(b"\n") and len(response) <= 65536:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response.extend(chunk)
        if len(response) > 65536:
            raise RuntimeError("install broker response is too large")
        document = json.loads(response)
        if not document.get("ok"):
            error = document.get("error", {})
            message = error.get("message", "install broker rejected the request")
            if error.get("code") == "ApprovalError":
                raise ConflictError(message)
            raise ValidationError(message)
        return document["data"]


class ScrotScreenshot:
    def capture(self) -> bytes:
        descriptor, raw_path = tempfile.mkstemp(prefix="relay-shot-", suffix=".png")
        os.close(descriptor)
        path = Path(raw_path)
        try:
            subprocess.run(["scrot", "--overwrite", str(path)], check=True, timeout=15)
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)


class SocketAccessibility:
    def __init__(self, path: str) -> None:
        self.path = path

    def snapshot(self) -> dict[str, object]:
        request = json.dumps({"maxNodes": 1000}).encode("utf-8") + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(15)
            client.connect(self.path)
            client.sendall(request)
            response = bytearray()
            while not response.endswith(b"\n") and len(response) <= 2 * 1024 * 1024:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response.extend(chunk)
        if len(response) > 2 * 1024 * 1024:
            raise RuntimeError("accessibility response is too large")
        document = json.loads(response)
        if not document.get("ok"):
            raise RuntimeError("accessibility adapter failed")
        return document["data"]


class XdotoolCursor:
    FIELDS = {"X": "x", "Y": "y", "SCREEN": "screen", "WINDOW": "window"}

    def position(self) -> dict[str, int]:
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        values: dict[str, int] = {}
        for line in result.stdout.splitlines():
            name, separator, raw_value = line.partition("=")
            if separator and name in self.FIELDS:
                values[self.FIELDS[name]] = int(raw_value)
        if set(values) != set(self.FIELDS.values()):
            raise RuntimeError("xdotool returned an incomplete cursor position")
        return values


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    file_path: str | None = None
    file_name: str | None = None


def json_response(status: int, value: object) -> Response:
    return Response(status, json.dumps(value, separators=(",", ":")).encode("utf-8"))


RECORDING_NAME = re.compile(r"^relay-\d{8}-\d{6}\.mp4$")


def file_response(path: Path) -> Response:
    """Serve a recording file as a streamed download response."""
    return Response(
        status=200,
        content_type="video/mp4",
        file_path=str(path),
        file_name=path.name,
    )


class ControlApplication:
    def __init__(
        self,
        *,
        token: str,
        human_token: str,
        lease: ControlLease,
        input_controller: InputController,
        broker: Broker,
        screenshotter: ScreenshotSource,
        accessibility: AccessibilitySource,
        cursor: CursorSource,
        width: int,
        height: int,
        events: EventLog | None = None,
        metrics: MetricsRegistry | None = None,
        recorder: ScreenRecorder | None = None,
        terminals: TmuxBridge | None = None,
    ) -> None:
        if len(token) < 12:
            raise ValueError("operator token must have at least 12 characters")
        if len(human_token) < 8:
            raise ValueError("human control token must have at least 8 characters")
        self.token = token
        self.human_token = human_token
        self.lease = lease
        self.input = input_controller
        self.broker = broker
        self.screenshotter = screenshotter
        self.accessibility = accessibility
        self.cursor = cursor
        self.width = width
        self.height = height
        self.events = events or EventLog()
        self.metrics = metrics or MetricsRegistry()
        self.recorder = recorder or ScreenRecorder(width=width, height=height)
        self.terminals = terminals or TmuxBridge()

    def _emit(self, kind: str, title: str, detail: dict[str, object] | None = None) -> None:
        self.events.emit(kind, title, detail)

    def handle(
        self, method: str, path: str, headers: object, body: object | None
    ) -> Response:
        try:
            return self._dispatch(method, urlsplit(path).path, headers, body)
        except ValidationError as error:
            return self._error(422, "VALIDATION_ERROR", str(error))
        except ConflictError as error:
            self.metrics.inc("relay_control_conflicts_total")
            return self._error(409, "CONTROL_CONFLICT", str(error))
        except RecordingConflictError as error:
            self.metrics.inc("relay_control_conflicts_total")
            return self._error(409, "CONTROL_CONFLICT", str(error))
        except (RecordingError, TerminalError) as error:
            return self._error(503, "DEPENDENCY_UNAVAILABLE", str(error))
        except TerminalValidationError as error:
            return self._error(422, "VALIDATION_ERROR", str(error))
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as error:
            print(f"control-api: dependency failure: {error}", flush=True)
            return self._error(503, "DEPENDENCY_UNAVAILABLE", "desktop dependency failed")
        except Exception:
            traceback.print_exc()
            return self._error(500, "INTERNAL_ERROR", "control service failed")

    def _dispatch(
        self, method: str, path: str, headers: object, body: object | None
    ) -> Response:
        if method == "GET" and path == "/api/v1/health":
            streaming_backend = os.environ.get("RELAY_STREAMING", "vnc")
            return json_response(
                200,
                {
                    "status": "ok",
                    "uptimeMs": self.events.uptime_ms(),
                    "display": {"width": self.width, "height": self.height},
                    "control": self.lease.state(),
                    "recording": self.recorder.state().as_dict(),
                    "streaming": {
                        "backend": streaming_backend,
                        "selkiesPath": "/selkies/" if streaming_backend == "selkies" else None,
                    },
                },
            )
        if method == "GET" and path == "/metrics":
            return Response(200, self.metrics.prometheus().encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8")
        if method == "GET" and path == "/api/v1/events":
            return json_response(200, {"events": self.events.list(50)})
        if method == "GET" and path == "/api/v1/control":
            return json_response(200, self.lease.state())
        if method == "GET" and path == "/api/v1/screenshot":
            if not self._authorized(headers):
                return self._unauthorized()
            return Response(200, self.screenshotter.capture(), "image/png")
        if method == "GET" and path == "/api/v1/accessibility":
            if not self._authorized(headers):
                return self._unauthorized()
            return json_response(200, self.accessibility.snapshot())
        if method == "GET" and path == "/api/v1/cursor":
            if not self._authorized(headers):
                return self._unauthorized()
            return json_response(200, self.cursor.position())

        if method == "GET" and path == "/api/v1/recording":
            if not self._authorized(headers):
                return self._unauthorized()
            return json_response(200, self.recorder.state().as_dict())

        if method == "GET" and path.startswith("/api/v1/recordings/") and not path.endswith("/"):
            if not self._operator_request(headers):
                return self._unauthorized()
            name = path[len("/api/v1/recordings/"):]
            if not RECORDING_NAME.fullmatch(name):
                return self._error(422, "VALIDATION_ERROR", "recording name must match relay-YYYYMMDD-HHMMSS.mp4")
            directory = Path(getattr(self.recorder, "output_dir", None) or self.recorder.OUTPUT_DIR)
            target = (directory / name).resolve()
            if target.parent != directory.resolve() or not target.is_file():
                return self._error(404, "NOT_FOUND", "recording not found")
            return file_response(target)

        if method == "GET" and path == "/api/v1/terminals":
            if not self._authorized(headers):
                return self._unauthorized()
            return json_response(200, {"sessions": self.terminals.list_sessions()})

        if method == "GET" and path.startswith("/api/v1/terminals/") and path.endswith("/capture"):
            if not self._authorized(headers):
                return self._unauthorized()
            name = path.split("/")[4]
            return json_response(200, self.terminals.capture(name))

        if method != "POST":
            return self._error(404, "NOT_FOUND", "route not found")
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")

        if path.startswith("/api/v1/control/human/"):
            if not self._human_request(headers):
                return self._error(403, "HUMAN_AUTH_REQUIRED", "valid human capability required")
            return json_response(200, self._human_control(path.rsplit("/", 1)[-1], body))

        if path == "/api/v1/approvals":
            if not self._human_request(headers):
                return self._error(403, "HUMAN_AUTH_REQUIRED", "valid human capability required")
            return json_response(
                201, self.broker.request({"action": "approve", "plan": body.get("plan")})
            )

        if path == "/api/v1/recording/start":
            if not self._operator_request(headers):
                return self._unauthorized()
            state = self.recorder.start()
            self.metrics.inc("relay_recording_actions_total")
            self._emit("recording.started", "Screen recording started", state.as_dict())
            return json_response(200, state.as_dict())
        if path == "/api/v1/recording/stop":
            if not self._operator_request(headers):
                return self._unauthorized()
            result = self.recorder.stop(save=True)
            self.metrics.inc("relay_recording_actions_total")
            self._emit("recording.saved", "Screen recording saved", result)
            return json_response(200, result)
        if path == "/api/v1/recording/discard":
            if not self._operator_request(headers):
                return self._unauthorized()
            result = self.recorder.stop(save=False)
            self.metrics.inc("relay_recording_actions_total")
            self._emit("recording.discarded", "Screen recording discarded", result)
            return json_response(200, result)

        if not self._authorized(headers):
            return self._unauthorized()

        if path.startswith("/api/v1/control/agent/"):
            return json_response(200, self._agent_control(path.rsplit("/", 1)[-1], body))
        if path == "/api/v1/input":
            agent_id = self._identifier(body.get("agentId"), "agentId")
            self.input.apply(agent_id, body.get("actions"))
            self.metrics.inc("relay_input_batches_total")
            return Response(204)
        if path == "/api/v1/terminals":
            name = self._identifier(body.get("name"), "name")
            cwd = body.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise ValidationError("cwd must be a string")
            result = self.terminals.create(
                name,
                cwd=cwd if isinstance(cwd, str) else None,
            )
            self.metrics.inc("relay_terminal_commands_total")
            self._emit("terminal.created", f"Terminal session {name} created", result)
            return json_response(201, result)
        if path.startswith("/api/v1/terminals/") and path.endswith("/input"):
            name = path.split("/")[4]
            text = body.get("text")
            if not isinstance(text, str):
                raise ValidationError("text is required")
            enter = body.get("enter", True)
            if not isinstance(enter, bool):
                raise ValidationError("enter must be a boolean")
            result = self.terminals.send(name, text, enter=enter)
            self.metrics.inc("relay_terminal_commands_total")
            return json_response(200, result)
        if path.startswith("/api/v1/terminals/") and path.endswith("/destroy"):
            name = path.split("/")[4]
            result = self.terminals.destroy(name)
            self.metrics.inc("relay_terminal_commands_total")
            self._emit("terminal.destroyed", f"Terminal session {name} destroyed", result)
            return json_response(200, result)
        if path == "/api/v1/installs":
            result = self.broker.request(
                {
                    "action": "install",
                    "approvalId": body.get("approvalId"),
                    "plan": body.get("plan"),
                }
            )
            return json_response(200, result)
        return self._error(404, "NOT_FOUND", "route not found")

    def _human_control(self, action: str, body: dict[object, object]) -> dict[str, object]:
        owner_id = self._identifier(body.get("sessionId"), "sessionId")
        if action == "claim":
            previous = self.lease.state()
            state = self.lease.claim_human(owner_id)
            self.input.preempt()
            if previous.get("owner") == "agent":
                self._emit(
                    "control.preempted",
                    "Human preempted the agent",
                    {"previousOwnerId": previous.get("ownerId")},
                )
            self._emit("control.claimed", "Human claimed control", {"ownerId": owner_id})
            self.metrics.inc("relay_lease_transitions_total")
            return state
        if action == "heartbeat":
            return self.lease.heartbeat("human", owner_id)
        if action == "release":
            state = self.lease.release("human", owner_id)
            self._emit("control.released", "Human released control", {"ownerId": owner_id})
            self.metrics.inc("relay_lease_transitions_total")
            return state
        raise ValidationError("unsupported human control action")

    def _agent_control(self, action: str, body: dict[object, object]) -> dict[str, object]:
        owner_id = self._identifier(body.get("agentId"), "agentId")
        if action == "claim":
            state = self.lease.claim_agent(owner_id)
            self._emit("control.claimed", "Agent claimed control", {"ownerId": owner_id})
            self.metrics.inc("relay_lease_transitions_total")
            return state
        if action == "heartbeat":
            return self.lease.heartbeat("agent", owner_id)
        if action == "release":
            state = self.lease.release("agent", owner_id)
            self.input.preempt()
            self._emit("control.released", "Agent released control", {"ownerId": owner_id})
            self.metrics.inc("relay_lease_transitions_total")
            return state
        raise ValidationError("unsupported agent control action")

    @staticmethod
    def _identifier(value: object, name: str) -> str:
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise ValidationError(f"{name} must contain 1 to 128 characters")
        return value

    def _authorized(self, headers: object) -> bool:
        supplied = headers.get("Authorization", "")  # type: ignore[attr-defined]
        return secrets_match(supplied, f"Bearer {self.token}")

    def _human_request(self, headers: object) -> bool:
        supplied = headers.get("X-Human-Control-Token", "")  # type: ignore[attr-defined]
        return secrets_match(supplied, self.human_token)

    def _operator_request(self, headers: object) -> bool:
        return self._authorized(headers) or self._human_request(headers)

    @staticmethod
    def _error(status: int, code: str, message: str) -> Response:
        return json_response(status, {"error": {"code": code, "message": message}})

    def _unauthorized(self) -> Response:
        return self._error(401, "UNAUTHORIZED", "valid operator bearer token required")


class ControlRequestHandler(BaseHTTPRequestHandler):
    server_version = "RelayControl/1"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/v1/events/stream":
            self._stream_events()
            return
        self._serve("GET")

    def _stream_events(self) -> None:
        application = self.server.application  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event in application.events.subscribe():
                payload = json.dumps(event, separators=(",", ":"))
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:
        self._serve("POST")

    def _serve(self, method: str) -> None:
        body: object | None = None
        if method == "POST":
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                self._write(ControlApplication._error(400, "BAD_REQUEST", "invalid content length"))
                return
            if not 0 < length <= 65536:
                self._write(ControlApplication._error(413, "PAYLOAD_TOO_LARGE", "body limit is 64 KiB"))
                return
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._write(ControlApplication._error(400, "BAD_JSON", "body must be valid JSON"))
                return
        response = self.server.application.handle(  # type: ignore[attr-defined]
            method, self.path, self.headers, body
        )
        self._write(response)

    def _write(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        if response.file_path is not None and response.file_name:
            size = os.path.getsize(response.file_path)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{response.file_name}"')
            self.send_header("Accept-Ranges", "none")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with open(response.file_path, "rb") as media:
                while chunk := media.read(64 * 1024):
                    self.wfile.write(chunk)
            return
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def log_message(self, message: str, *args: object) -> None:
        print(f"control-api: {message % args}", flush=True)


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: ControlApplication) -> None:
        self.application = application
        super().__init__(address, ControlRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--width", type=int, default=int(os.environ.get("WIDTH", "1440")))
    parser.add_argument("--height", type=int, default=int(os.environ.get("HEIGHT", "900")))
    parser.add_argument("--token-file", default="/run/ai-desktop/operator-token")
    parser.add_argument("--human-token-file", default="/run/ai-desktop/human-token")
    parser.add_argument("--broker-socket", default="/run/ai-desktop/installer.sock")
    parser.add_argument("--accessibility-socket", default="/run/relay-access/a11y.sock")
    args = parser.parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    human_token = Path(args.human_token_file).read_text(encoding="utf-8").strip()
    events = EventLog()
    metrics = MetricsRegistry()
    terminals = TmuxBridge()
    terminals.ensure_server()
    lease = ControlLease()
    input_controller = InputController(
        width=args.width,
        height=args.height,
        runner=SubprocessRunner(),
        lease=lease,
    )
    app = ControlApplication(
        token=token,
        human_token=human_token,
        lease=lease,
        input_controller=input_controller,
        broker=BrokerClient(args.broker_socket),
        screenshotter=ScrotScreenshot(),
        accessibility=SocketAccessibility(args.accessibility_socket),
        cursor=XdotoolCursor(),
        width=args.width,
        height=args.height,
        events=events,
        metrics=metrics,
        terminals=terminals,
    )
    ControlHTTPServer((args.host, args.port), app).serve_forever()


if __name__ == "__main__":
    main()
