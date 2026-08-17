import unittest
from unittest.mock import patch

from desktop.control.tmux_bridge import TerminalValidationError, TmuxBridge


class TmuxBridgeTests(unittest.TestCase):
    def test_create_rejects_invalid_names(self):
        bridge = TmuxBridge()
        with self.assertRaises(TerminalValidationError):
            bridge.create("bad name!")

    @patch.object(TmuxBridge, "_run")
    def test_send_requires_bounded_text(self, run_mock):
        bridge = TmuxBridge()
        with self.assertRaises(TerminalValidationError):
            bridge.send("agent-1", "")
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
