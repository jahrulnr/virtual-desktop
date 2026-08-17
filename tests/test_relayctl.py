import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "desktop/home/.agents/skills/os-operator/scripts/relayctl.py"
)
SPEC = importlib.util.spec_from_file_location("relayctl", SCRIPT)
relayctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(relayctl)


class FakeResponse:
    def __init__(self, body=b"{}", content_type="application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RecordingOpener:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


class RelayClientTests(unittest.TestCase):
    def test_agent_claim_uses_bearer_capability_and_json_body(self):
        opener = RecordingOpener(FakeResponse(b'{"owner":"agent"}'))
        client = relayctl.RelayClient(
            base_url="http://127.0.0.1:3000",
            token="operator-test-token",
            opener=opener,
        )

        response = client.agent_control("claim", "demo-agent")

        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:3000/api/v1/control/agent/claim")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer operator-test-token")
        self.assertEqual(json.loads(request.data), {"agentId": "demo-agent"})
        self.assertEqual(timeout, 20)
        self.assertEqual(response["owner"], "agent")

    def test_input_rejects_non_array_actions_before_network(self):
        opener = RecordingOpener()
        client = relayctl.RelayClient(
            base_url="http://127.0.0.1:3000",
            token="operator-test-token",
            opener=opener,
        )

        with self.assertRaises(ValueError):
            client.input("demo-agent", {"type": "click"})

        self.assertEqual(opener.requests, [])

    def test_screenshot_returns_png_bytes(self):
        opener = RecordingOpener(FakeResponse(b"\x89PNG\r\n\x1a\n", "image/png"))
        client = relayctl.RelayClient(
            base_url="http://127.0.0.1:3000",
            token="operator-test-token",
            opener=opener,
        )

        self.assertEqual(client.screenshot(), b"\x89PNG\r\n\x1a\n")

    def test_cursor_uses_operator_capability(self):
        opener = RecordingOpener(FakeResponse(b'{"x":412,"y":265}'))
        client = relayctl.RelayClient(
            base_url="http://127.0.0.1:3000",
            token="operator-test-token",
            opener=opener,
        )

        self.assertEqual(client.cursor(), {"x": 412, "y": 265})
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:3000/api/v1/cursor")
        self.assertEqual(request.headers["Authorization"], "Bearer operator-test-token")

    def test_install_uses_the_long_broker_timeout(self):
        opener = RecordingOpener(FakeResponse(b'{"status":"installed"}'))
        client = relayctl.RelayClient(
            base_url="http://127.0.0.1:3000",
            token="operator-test-token",
            opener=opener,
        )

        client.install("approval-1", {"kind": "apt", "packages": ["jq"]})

        _, timeout = opener.requests[0]
        self.assertEqual(timeout, 920)


if __name__ == "__main__":
    unittest.main()
