import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from desktop.control.api import ControlApplication, ControlHTTPServer
from desktop.control.domain import ControlLease
from desktop.control.recording import RecordingConflictError, RecordingState
from desktop.control.tmux_bridge import TerminalValidationError


class FakeInput:
    def __init__(self):
        self.calls = []
        self.preemptions = 0
        self.pointer_observer = None

    def set_pointer_observer(self, observer):
        self.pointer_observer = observer

    def apply(self, owner_id, actions):
        self.calls.append((owner_id, actions))
        if self.pointer_observer is None:
            return
        for action in actions:
            if action.get("type") == "move":
                self.pointer_observer(action["x"], action["y"])
            elif action.get("type") in {"click", "scroll", "button"}:
                self.pointer_observer(None, None)
            elif action.get("type") == "drag":
                self.pointer_observer(action["toX"], action["toY"])

    def preempt(self):
        self.preemptions += 1


class FakeBroker:
    def request(self, document):
        if document["action"] == "approve":
            return {"approvalId": "approval-1", "expiresInSeconds": 120}
        return {"status": "installed"}


class FakeScreenshot:
    def capture(self):
        return b"\x89PNG\r\n\x1a\n"


class FakeAccessibility:
    def snapshot(self):
        return {"role": "desktop frame", "name": "Relay desktop", "children": []}


class FakeCursor:
    def position(self):
        return {"x": 321, "y": 123, "screen": 0, "window": 456}


class FakeRecorder:
    def __init__(self):
        self.active = False
        self.camera_states = []

    def state(self) -> RecordingState:
        return RecordingState(active=self.active)

    def start(self) -> RecordingState:
        if self.active:
            raise RecordingConflictError("a recording is already active")
        self.active = True
        return self.state()

    def stop(self, *, save: bool) -> dict[str, object]:
        if not self.active:
            raise RecordingConflictError("no recording is active")
        self.active = False
        if save:
            return {
                "status": "saved",
                "path": "/home/desktop/Downloads/recordings/relay-test.mp4",
                "sizeBytes": 128,
                "durationMs": 1000,
            }
        return {"status": "discarded"}

    def track_camera(self, state):
        if self.active:
            self.camera_states.append(state)


class FakeDownloadRecorder(FakeRecorder):
    """Recorder stub that serves files from a temporary directory."""

    def __init__(self, directory):
        super().__init__()
        self.output_dir = directory


class FakeTerminals:
    def list_sessions(self):
        return [{"name": "demo", "createdAt": 0, "lastActivityAt": 0}]

    def create(self, name, *, cwd=None):
        if name == "bad name!":
            raise TerminalValidationError("session name must be 1-32 alphanumeric, dash, or underscore")
        return {"name": name, "cwd": cwd or "/home/desktop"}

    def capture(self, name):
        return {"name": name, "output": "hello\n", "truncated": False}

    def send(self, name, text, *, enter=True):
        return {"name": name, "bytesSent": len(text.encode("utf-8")), "enter": enter}

    def destroy(self, name):
        return {"name": name, "status": "destroyed"}


class ControlAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lease = ControlLease()
        cls.input = FakeInput()
        cls.recorder = FakeRecorder()
        cls.terminals = FakeTerminals()
        app = ControlApplication(
            token="test-operator-token",
            human_token="test-human-control-token",
            lease=cls.lease,
            input_controller=cls.input,
            broker=FakeBroker(),
            screenshotter=FakeScreenshot(),
            accessibility=FakeAccessibility(),
            cursor=FakeCursor(),
            width=1440,
            height=900,
            recorder=cls.recorder,
            terminals=cls.terminals,
        )
        cls.server = ControlHTTPServer(("127.0.0.1", 0), app)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, *, token=None, human=False):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if human:
            headers["X-Human-Control-Token"] = "test-human-control-token"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request)
            payload = response.read()
            return response.status, response.headers, json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read())

    def setUp(self):
        self.server.application.showcase.follow(720, 450)

    def tearDown(self):
        state = self.lease.state()
        if state["owner"] != "none":
            self.lease.release(str(state["owner"]), str(state["ownerId"]))
        self.recorder.active = False

    def test_health_and_state_contract(self):
        status, headers, body = self.request("GET", "/api/v1/health")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["display"], {"width": 1440, "height": 900})
        self.assertEqual(body["showcase"], {
            "zoom": 2.0,
            "pivot": {"x": 720, "y": 450},
            "display": {"width": 1440, "height": 900},
        })
        self.assertIn("uptimeMs", body)
        self.assertIn("recording", body)
        self.assertEqual(body["recording"]["active"], False)
        self.assertIn("streaming", body)
        self.assertIn(body["streaming"]["backend"], {"vnc", "selkies"})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_metrics_endpoint_exposes_prometheus_counters(self):
        self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "metrics-agent"},
            token="test-operator-token",
        )
        request = urllib.request.Request(self.base + "/metrics")
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
        self.assertIn("relay_lease_transitions_total", body)
        self.assertIn("relay_info", body)

    def test_recording_routes_accept_human_or_bearer_token(self):
        started, _, body = self.request(
            "POST", "/api/v1/recording/start", {}, human=True
        )
        self.assertEqual(started, 200)
        self.assertTrue(body["active"])
        self.assertEqual(self.recorder.camera_states[-1], {
            "zoom": 2.0,
            "pivot": {"x": 720, "y": 450},
            "display": {"width": 1440, "height": 900},
        })

        saved, _, body = self.request("POST", "/api/v1/recording/stop", {}, human=True)
        self.assertEqual(saved, 200)
        self.assertEqual(body["status"], "saved")

        conflict, _, body = self.request("POST", "/api/v1/recording/stop", {}, human=True)
        self.assertEqual(conflict, 409)
        self.assertEqual(body["error"]["code"], "CONTROL_CONFLICT")

    def test_terminal_routes_require_bearer_token(self):
        rejected, _, body = self.request("GET", "/api/v1/terminals")
        self.assertEqual(rejected, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")

        accepted, _, body = self.request(
            "GET", "/api/v1/terminals", token="test-operator-token"
        )
        self.assertEqual(accepted, 200)
        self.assertEqual(body["sessions"][0]["name"], "demo")

        created, _, body = self.request(
            "POST",
            "/api/v1/terminals",
            {"name": "agent-shell", "cwd": "/home/desktop"},
            token="test-operator-token",
        )
        self.assertEqual(created, 201)
        self.assertEqual(body["name"], "agent-shell")

    def test_events_stream_returns_server_sent_events(self):
        self.server.application.events.emit("test.stream", "Stream check", {"ok": True})
        host, port = self.server.server_address
        sock = socket.create_connection((host, port), timeout=2)
        try:
            sock.sendall(
                f"GET /api/v1/events/stream HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
            )
            sock.settimeout(2)
            chunks = bytearray()
            while len(chunks) < 8192:
                try:
                    piece = sock.recv(4096)
                except socket.timeout:
                    break
                if not piece:
                    break
                chunks.extend(piece)
                if b"test.stream" in chunks:
                    break
        finally:
            sock.close()
        body = chunks.decode("utf-8", errors="ignore")
        self.assertIn("data:", body)
        self.assertIn("test.stream", body)
        self.assertIn("Stream check", body)

    def test_events_endpoint_returns_recent_activity(self):
        self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "agent-events"},
            token="test-operator-token",
        )
        status, _, body = self.request("GET", "/api/v1/events")
        self.assertEqual(status, 200)
        self.assertTrue(body["events"])
        self.assertEqual(body["events"][-1]["kind"], "control.claimed")

    def test_agent_routes_require_bearer_token(self):
        status, _, body = self.request(
            "POST", "/api/v1/control/agent/claim", {"agentId": "agent-1"}
        )

        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")

    def test_wrong_length_operator_token_is_unauthorized_not_server_error(self):
        status, _, body = self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "agent-1"},
            token="short",
        )

        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")

    def test_human_claim_requires_capability_and_preempts_agent(self):
        before = self.input.preemptions
        self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "agent-1"},
            token="test-operator-token",
        )

        rejected, _, _ = self.request(
            "POST", "/api/v1/control/human/claim", {"sessionId": "browser-1"}
        )
        accepted, _, body = self.request(
            "POST",
            "/api/v1/control/human/claim",
            {"sessionId": "browser-1"},
            human=True,
        )

        self.assertEqual(rejected, 403)
        self.assertEqual(accepted, 200)
        self.assertEqual(body["owner"], "human")
        self.assertEqual(self.input.preemptions, before + 1)

    def test_operator_token_cannot_authorize_human_approval(self):
        rejected, _, body = self.request(
            "POST",
            "/api/v1/approvals",
            {"plan": {"kind": "apt", "packages": ["jq"]}},
            token="test-operator-token",
        )
        accepted, _, _ = self.request(
            "POST",
            "/api/v1/approvals",
            {"plan": {"kind": "apt", "packages": ["jq"]}},
            human=True,
        )

        self.assertEqual(rejected, 403)
        self.assertEqual(body["error"]["code"], "HUMAN_AUTH_REQUIRED")
        self.assertEqual(accepted, 201)

    def test_agent_input_is_forwarded_only_with_lease(self):
        self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "agent-7"},
            token="test-operator-token",
        )
        status, _, body = self.request(
            "POST",
            "/api/v1/input",
            {"agentId": "agent-7", "actions": [{"type": "click"}]},
            token="test-operator-token",
        )

        self.assertEqual(status, 204)
        self.assertIsNone(body)
        self.assertEqual(self.input.calls[-1][0], "agent-7")

    def test_screenshot_is_png_and_accessibility_is_json(self):
        request = urllib.request.Request(
            self.base + "/api/v1/screenshot",
            headers={"Authorization": "Bearer test-operator-token"},
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(response.read().startswith(b"\x89PNG"))

        status, _, body = self.request(
            "GET", "/api/v1/accessibility", token="test-operator-token"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["role"], "desktop frame")

    def test_cursor_position_requires_operator_token(self):
        rejected, _, body = self.request("GET", "/api/v1/cursor")
        accepted, _, position = self.request(
            "GET", "/api/v1/cursor", token="test-operator-token"
        )

        self.assertEqual(rejected, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(accepted, 200)
        self.assertEqual(position, {"x": 321, "y": 123, "screen": 0, "window": 456})

    def test_showcase_camera_follows_pointer_implicitly_without_an_agent_tool(self):
        self.request(
            "POST",
            "/api/v1/control/agent/claim",
            {"agentId": "agent-camera"},
            token="test-operator-token",
        )

        accepted, _, body = self.request(
            "POST",
            "/api/v1/input",
            {
                "agentId": "agent-camera",
                "actions": [{"type": "move", "x": 900, "y": 420}],
            },
            token="test-operator-token",
        )

        self.assertEqual(accepted, 204)
        self.assertIsNone(body)

        status, _, health = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["showcase"]["zoom"], 2.0)
        self.assertEqual(health["showcase"]["pivot"], {"x": 900, "y": 420})
        self.assertEqual(
            self.server.application.events.list()[-1]["kind"],
            "showcase.camera",
        )

        removed, _, removed_body = self.request(
            "POST",
            "/api/v1/showcase/zoom",
            {"agentId": "agent-camera", "direction": "in"},
            token="test-operator-token",
        )
        self.assertEqual(removed, 404)
        self.assertEqual(removed_body["error"]["code"], "NOT_FOUND")


class RecordingDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.recordings = Path(cls.directory.name)
        cls.media = cls.recordings / "relay-20260829-074638.mp4"
        cls.media.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        cls.lease = ControlLease()
        app = ControlApplication(
            token="test-operator-token",
            human_token="test-human-control-token",
            lease=cls.lease,
            input_controller=FakeInput(),
            broker=FakeBroker(),
            screenshotter=FakeScreenshot(),
            accessibility=FakeAccessibility(),
            cursor=FakeCursor(),
            width=1440,
            height=900,
            recorder=FakeDownloadRecorder(cls.recordings),
            terminals=FakeTerminals(),
        )
        cls.server = ControlHTTPServer(("127.0.0.1", 0), app)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def request(self, method, path, body=None, *, token=None, human=False):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if human:
            headers["X-Human-Control-Token"] = "test-human-control-token"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request)
            payload = response.read()
            return response.status, response.headers, payload
        except urllib.error.HTTPError as error:
            payload = error.read()
            try:
                return error.code, error.headers, json.loads(payload)
            except json.JSONDecodeError:
                return error.code, error.headers, payload

    def test_download_serves_recording_with_operator_token(self):
        request = urllib.request.Request(
            self.base + "/api/v1/recordings/relay-20260829-074638.mp4",
            headers={"Authorization": "Bearer test-operator-token"},
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "video/mp4")
            self.assertEqual(
                response.headers["Content-Disposition"],
                'attachment; filename="relay-20260829-074638.mp4"',
            )
            body = response.read()
        self.assertEqual(body, self.media.read_bytes())

    def test_download_accepts_human_capability(self):
        request = urllib.request.Request(
            self.base + "/api/v1/recordings/relay-20260829-074638.mp4",
            headers={"X-Human-Control-Token": "test-human-control-token"},
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.read())

    def test_download_requires_authentication(self):
        status, _, body = self.request("GET", "/api/v1/recordings/relay-20260829-074638.mp4")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")

    def test_download_rejects_invalid_names(self):
        for bad in (
            "relay-test.mp4",
            "../../etc/passwd",
            "relay-20260829-074638.mp4%00",
            "relay.mp4",
            "xrelay-20260829-074638.mp4",
        ):
            status, _, body = self.request(
                "GET", f"/api/v1/recordings/{bad}", token="test-operator-token"
            )
            self.assertEqual(status, 422, msg=bad)
            self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")

    def test_download_returns_404_for_missing_recording(self):
        status, _, body = self.request(
            "GET",
            "/api/v1/recordings/relay-19990101-000000.mp4",
            token="test-operator-token",
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
