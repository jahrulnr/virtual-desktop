import unittest

from desktop.control.domain import ControlLease, ValidationError
from desktop.control.input_controller import InputController


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def run(self, command):
        self.commands.append(command)


class InputControllerTests(unittest.TestCase):
    def setUp(self):
        self.lease = ControlLease()
        self.lease.claim_agent("agent-1")
        self.runner = RecordingRunner()
        self.controller = InputController(
            width=1440, height=900, runner=self.runner, lease=self.lease
        )

    def test_executes_validated_actions_without_a_shell(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "move", "x": 120, "y": 240},
                {"type": "click", "button": "left"},
                {"type": "text", "text": "hello; $(touch /tmp/nope)"},
                {"type": "key", "keys": ["CTRL", "L"]},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "mousemove", "120", "240"],
                ["xdotool", "click", "1"],
                [
                    "xdotool",
                    "type",
                    "--clearmodifiers",
                    "--delay",
                    "2",
                    "--",
                    "hello; $(touch /tmp/nope)",
                ],
                ["xdotool", "key", "--clearmodifiers", "CTRL+L"],
            ],
        )

    def test_rejects_coordinates_outside_the_desktop(self):
        with self.assertRaises(ValidationError):
            self.controller.apply("agent-1", [{"type": "move", "x": 1440, "y": 2}])

    def test_rejects_unknown_keys_before_running_any_action(self):
        with self.assertRaises(ValidationError):
            self.controller.apply(
                "agent-1",
                [
                    {"type": "click", "button": "left"},
                    {"type": "key", "keys": ["CTRL", "Not A Key!"]},
                ],
            )

        self.assertEqual(self.runner.commands, [])

    def test_rejects_more_than_fifty_actions(self):
        actions = [{"type": "click", "button": "left"}] * 51

        with self.assertRaises(ValidationError):
            self.controller.apply("agent-1", actions)

    def test_human_takeover_blocks_agent_input(self):
        self.lease.claim_human("browser-1")

        with self.assertRaises(Exception):
            self.controller.apply("agent-1", [{"type": "click", "button": "left"}])

        self.assertEqual(self.runner.commands, [])


if __name__ == "__main__":
    unittest.main()
