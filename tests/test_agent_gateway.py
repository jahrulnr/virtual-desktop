import unittest
from io import BytesIO

from desktop.control.agent_gateway import (
    MAX_UPSTREAM_BYTES,
    RoutePolicy,
    UpstreamLimitError,
    stream_limited,
)


class AgentGatewayPolicyTests(unittest.TestCase):
    def test_allows_only_browser_agent_routes(self):
        allowed = [
            ("GET", "/v1/models"),
            ("POST", "/v1/responses"),
            ("GET", "/coddy/sessions"),
            ("GET", "/coddy/sessions/sess_0123456789abcdef/messages"),
            ("GET", "/coddy/sessions/sess_0123456789abcdef/composer-stream"),
            ("POST", "/coddy/sessions/sess_0123456789abcdef/permission"),
            ("POST", "/coddy/sessions/sess_0123456789abcdef/cancel"),
            ("POST", "/coddy/sessions"),
        ]
        for method, path in allowed:
            with self.subTest(method=method, path=path):
                self.assertTrue(RoutePolicy.allowed(method, path))

    def test_rejects_config_workspace_and_malformed_session_routes(self):
        rejected = [
            ("GET", "/coddy/config"),
            ("PUT", "/coddy/config"),
            ("GET", "/coddy/workspace/files"),
            ("POST", "/v1/chat/completions"),
            ("GET", "/coddy/sessions/../../config"),
            ("POST", "/coddy/sessions/not-a-session/cancel"),
        ]
        for method, path in rejected:
            with self.subTest(method=method, path=path):
                self.assertFalse(RoutePolicy.allowed(method, path))

    def test_session_header_must_match_path_when_both_exist(self):
        path = "/coddy/sessions/sess_0123456789abcdef/messages"
        self.assertTrue(RoutePolicy.session_matches(path, "sess_0123456789abcdef"))
        self.assertFalse(RoutePolicy.session_matches(path, "sess_ffffffffffffffff"))
        self.assertFalse(RoutePolicy.session_matches(path, ""))
        self.assertTrue(RoutePolicy.session_matches("/v1/responses", "sess_0123456789abcdef"))
        self.assertFalse(RoutePolicy.session_matches("/v1/responses", ""))
        self.assertFalse(RoutePolicy.session_matches("/v1/models", "invalid"))

    def test_stream_uses_available_chunks_and_flushes_each_one(self):
        class ChunkedResponse:
            def __init__(self):
                self.chunks = [b"data: one\n\n", b"data: two\n\n", b""]

            def read1(self, amount):
                self.assert_amount = amount
                return self.chunks.pop(0)

        class FlushingBuffer(BytesIO):
            def __init__(self):
                super().__init__()
                self.flushes = 0

            def flush(self):
                self.flushes += 1

        upstream = ChunkedResponse()
        output = FlushingBuffer()

        stream_limited(upstream, output)

        self.assertEqual(output.getvalue(), b"data: one\n\ndata: two\n\n")
        self.assertEqual(output.flushes, 2)
        self.assertEqual(upstream.assert_amount, 16 * 1024)

    def test_stream_rejects_more_than_sixteen_mebibytes(self):
        class OversizedResponse:
            def __init__(self):
                self.sent = False

            def read1(self, _):
                if self.sent:
                    return b""
                self.sent = True
                return b"x" * (MAX_UPSTREAM_BYTES + 1)

        with self.assertRaises(UpstreamLimitError):
            stream_limited(OversizedResponse(), BytesIO())


if __name__ == "__main__":
    unittest.main()
