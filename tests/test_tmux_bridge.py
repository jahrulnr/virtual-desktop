import unittest
from unittest.mock import patch

from desktop.control.tmux_bridge import TerminalValidationError, TmuxBridge


class TmuxBridgeTests(unittest.TestCase):
    def test_create_rejects_invalid_names(self):
        bridge = TmuxBridge()
        with self.assertRaises(TerminalValidationError):
            bridge.create("bad name!")

    @patch.object(TmuxBridge, "_run")
    def test_list_sessions_parses_pipe_delimited_tmux_output(self, run_mock):
        run_mock.return_value.stdout = "native-smoke|1786961606|1786961606\n"
        run_mock.return_value.returncode = 0
        sessions = TmuxBridge().list_sessions()
        self.assertEqual(sessions[0]["name"], "native-smoke")
        self.assertEqual(sessions[0]["createdAt"], 1786961606)

    @patch.object(TmuxBridge, "_run")
    def test_send_requires_bounded_text(self, run_mock):
        bridge = TmuxBridge()
        with self.assertRaises(TerminalValidationError):
            bridge.send("agent-1", "")
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
