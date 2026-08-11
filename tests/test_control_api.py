import json
import threading
import unittest
import urllib.error
import urllib.request

from desktop.control.api import ControlApplication, ControlHTTPServer
from desktop.control.domain import ControlLease


class FakeInput:
    def __init__(self):
        self.calls = []
        self.preemptions = 0

    def apply(self, owner_id, actions):
        self.calls.append((owner_id, actions))

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


class ControlAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lease = ControlLease()
        cls.input = FakeInput()
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

    def tearDown(self):
        state = self.lease.state()
        if state["owner"] != "none":
            self.lease.release(str(state["owner"]), str(state["ownerId"]))

    def test_health_and_state_contract(self):
        status, headers, body = self.request("GET", "/api/v1/health")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["display"], {"width": 1440, "height": 900})
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_agent_routes_require_bearer_token(self):
        status, _, body = self.request(
            "POST", "/api/v1/control/agent/claim", {"agentId": "agent-1"}
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


if __name__ == "__main__":
    unittest.main()
