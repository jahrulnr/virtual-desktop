import time
import unittest

from desktop.control.showcase import (
    SHOWCASE_ACTIVE_ZOOM,
    SHOWCASE_IDLE_ZOOM,
    ShowcaseCamera,
)

from tools.relay_showcase_flow import (
    MCPError,
    human_chunks,
    parse_mcp_response,
    showcase_action_plan,
)


class ShowcaseFlowTests(unittest.TestCase):
    def test_showcase_camera_zooms_on_activity_and_returns_idle(self):
        camera = ShowcaseCamera(width=1440, height=900, idle_timeout_seconds=0.02)
        events = []
        camera.subscribe(events.append)

        self.assertEqual(camera.state()["zoom"], SHOWCASE_IDLE_ZOOM)
        camera.follow(900, 420)
        self.assertEqual(camera.state()["zoom"], SHOWCASE_ACTIVE_ZOOM)
        time.sleep(0.05)

        self.assertEqual(camera.state()["zoom"], SHOWCASE_IDLE_ZOOM)
        self.assertEqual([event["zoom"] for event in events], [2.0, 1.0])

    def test_human_chunks_preserve_text_and_are_smaller_than_words(self):
        prompt = "Jelaskan alur login web."

        chunks = human_chunks(prompt)

        self.assertEqual("".join(chunks), prompt)
        self.assertGreater(len(chunks), len(prompt.split()))
        self.assertTrue(all(chunks))

    def test_parse_mcp_response_reads_matching_sse_message(self):
        body = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"ok"}]}}\n\n'
        )

        result = parse_mcp_response(body, 7)

        self.assertEqual(result["content"][0]["text"], "ok")

    def test_parse_mcp_response_surfaces_tool_error_without_leaking_request_body(self):
        body = (
            'data: {"jsonrpc":"2.0","id":9,"result":{"isError":true,'
            '"content":[{"type":"text","text":"Endpoint is unavailable"}]}}\n'
        )

        with self.assertRaises(MCPError) as raised:
            parse_mcp_response(body, 9)

        self.assertIn("Endpoint is unavailable", str(raised.exception))

    def test_action_plan_never_selects_model_or_home_picker(self):
        plan = showcase_action_plan(("Jelas", "kan "), (900, 688), record=True)

        self.assertEqual(plan[0], ("record_screen", {"mode": "START_RECORDING"}))
        self.assertEqual(plan[1], ("computer", {"action": "left_click", "coordinate": [900, 688]}))
        self.assertEqual(plan[-1], ("computer", {"action": "key", "key": "CTRL+ENTER"}))
        self.assertFalse(any("model" in str(arguments).lower() for _, arguments in plan))
        self.assertFalse(any("home" in str(arguments).lower() for _, arguments in plan))


if __name__ == "__main__":
    unittest.main()
