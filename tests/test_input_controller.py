import unittest

from desktop.control.domain import ConflictError, ControlLease, ValidationError
from desktop.control.input_controller import InputController


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class RecordingRunner:
    def __init__(self):
        self.commands = []
        self.cancel_calls = 0

    def run(self, command, cancelled=None):
        if cancelled is not None and cancelled():
            raise ConflictError("cancelled")
        self.commands.append(command)

    def cancel_current(self):
        self.cancel_calls += 1


class InputControllerTests(unittest.TestCase):
    def setUp(self):
        self.lease = ControlLease()
        self.lease.claim_agent("agent-1")
        self.runner = RecordingRunner()
        self.controller = InputController(
            width=1440, height=900, runner=self.runner, lease=self.lease
        )

    def test_reports_successful_pointer_activity_to_the_showcase_camera(self):
        activities = []
        self.controller.set_pointer_observer(
            lambda x, y: activities.append((x, y))
        )

        self.controller.apply(
            "agent-1",
            [
                {"type": "move", "x": 120, "y": 240},
                {"type": "click", "button": "left"},
                {"type": "text", "text": "not pointer activity"},
                {"type": "scroll", "direction": "down", "delta": -2},
                {"type": "drag", "x": 40, "y": 50, "toX": 400, "toY": 500},
                {"type": "wait", "durationMs": 50},
            ],
        )

        self.assertEqual(
            activities,
            [(120, 240), (None, None), (None, None), (400, 500)],
        )

    def test_camera_failure_does_not_turn_a_completed_click_into_a_retryable_error(self):
        def broken_camera(_x, _y):
            raise RuntimeError("camera unavailable")

        self.controller.set_pointer_observer(broken_camera)

        self.controller.apply(
            "agent-1",
            [{"type": "click", "button": "left"}],
        )

        self.assertEqual(self.runner.commands, [["xdotool", "click", "1"]])

    def test_executes_validated_actions_without_a_shell(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "move", "x": 120, "y": 240},
                {"type": "click", "button": "left"},
                {"type": "text", "text": "hello; $(touch /tmp/nope)"},
                {"type": "key", "keys": ["ctrl", "L"]},
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
                    "100",
                    "--",
                    "hello; $(touch /tmp/nope)",
                ],
                ["xdotool", "key", "--clearmodifiers", "ctrl+L"],
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
                    {"type": "key", "keys": ["ctrl", "Not_A_Key_XYZ"]},
                ],
            )

        self.assertEqual(self.runner.commands, [])

    def test_rejects_invalid_keysym_names_despite_xdotool_silence(self):
        # xdotool exits 0 for unknown key names; the controller must not
        # trust that and reject invalid names up front.
        for bad in ("enterx", "Hyper_L", "NonExistentKey", "pg upp"):
            with self.assertRaises(ValidationError):
                self.controller.apply(
                    "agent-1",
                    [{"type": "key", "keys": [bad]}],
                )
        with self.assertRaises(ValidationError):
            self.controller.apply(
                "agent-1",
                [{"type": "hold_key", "key": "fake_key", "durationMs": 250}],
            )
        self.assertEqual(self.runner.commands, [])

    def test_accepts_common_natural_key_names(self):
        # The very names an LLM is most likely to send must all work:
        # "Enter" resolves through the alias table to the Return keysym.
        self.controller.apply(
            "agent-1",
            [
                {"type": "key", "keys": ["Enter"]},
                {"type": "key", "keys": ["Tab"]},
                {"type": "key", "keys": ["Escape"]},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "key", "--clearmodifiers", "Return"],
                ["xdotool", "key", "--clearmodifiers", "Tab"],
                ["xdotool", "key", "--clearmodifiers", "Escape"],
            ],
        )

    def test_resolves_llm_friendly_key_aliases_to_canonical_keysyms(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "key", "keys": ["enter"]},
                {"type": "key", "keys": ["esc"]},
                {"type": "key", "keys": ["ctrl", "L"]},
                {"type": "key", "keys": ["pgup"]},
                {"type": "key", "keys": ["shift", "insert"]},
                {"type": "hold_key", "key": "backspace", "durationMs": 100},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "key", "--clearmodifiers", "Return"],
                ["xdotool", "key", "--clearmodifiers", "Escape"],
                ["xdotool", "key", "--clearmodifiers", "ctrl+L"],
                ["xdotool", "key", "--clearmodifiers", "Prior"],
                ["xdotool", "key", "--clearmodifiers", "shift+Insert"],
                ["xdotool", "keydown", "BackSpace", "sleep", "0.100", "keyup", "BackSpace"],
            ],
        )

    def test_accepts_canonical_keysyms_case_insensitively(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "key", "keys": ["Return"]},
                {"type": "key", "keys": ["return"]},
                {"type": "key", "keys": ["KP_Enter"]},
                {"type": "key", "keys": ["f5"]},
                {"type": "key", "keys": ["caps_lock"]},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "key", "--clearmodifiers", "Return"],
                ["xdotool", "key", "--clearmodifiers", "Return"],
                ["xdotool", "key", "--clearmodifiers", "KP_Enter"],
                ["xdotool", "key", "--clearmodifiers", "F5"],
                ["xdotool", "key", "--clearmodifiers", "Caps_Lock"],
            ],
        )

    def test_rejects_more_than_fifty_actions(self):
        actions = [{"type": "click", "button": "left"}] * 51

        with self.assertRaises(ValidationError):
            self.controller.apply("agent-1", actions)

    def test_supports_drag_button_hold_key_and_wait_without_a_shell(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "drag", "x": 40, "y": 50, "toX": 400, "toY": 500},
                {"type": "button", "button": "left", "state": "down"},
                {"type": "button", "button": "left", "state": "up"},
                {"type": "hold_key", "key": "alt", "durationMs": 250},
                {"type": "wait", "durationMs": 125},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                [
                    "xdotool",
                    "mousemove",
                    "40",
                    "50",
                    "mousedown",
                    "1",
                    "mousemove",
                    "400",
                    "500",
                    "mouseup",
                    "1",
                ],
                ["xdotool", "mousedown", "1"],
                ["xdotool", "mouseup", "1"],
                ["xdotool", "keydown", "alt", "sleep", "0.250", "keyup", "alt"],
                ["xdotool", "sleep", "0.125"],
            ],
        )

    def test_validates_entire_extended_batch_before_executing(self):
        with self.assertRaises(ValidationError):
            self.controller.apply(
                "agent-1",
                [
                    {"type": "button", "button": "left", "state": "down"},
                    {"type": "hold_key", "key": "alt;touch", "durationMs": 10},
                ],
            )

        self.assertEqual(self.runner.commands, [])

    def test_scroll_supports_all_four_directions(self):
        self.controller.apply(
            "agent-1",
            [
                {"type": "scroll", "direction": "up", "delta": 2},
                {"type": "scroll", "direction": "down", "delta": 3},
                {"type": "scroll", "direction": "left", "delta": 1},
                {"type": "scroll", "direction": "right", "delta": 4},
            ],
        )

        self.assertEqual(
            self.runner.commands,
            [
                ["xdotool", "click", "--repeat", "2", "--delay", "35", "4"],
                ["xdotool", "click", "--repeat", "3", "--delay", "35", "5"],
                ["xdotool", "click", "--repeat", "1", "--delay", "35", "6"],
                ["xdotool", "click", "--repeat", "4", "--delay", "35", "7"],
            ],
        )

    def test_human_takeover_blocks_agent_input(self):
        self.lease.claim_human("browser-1")

        with self.assertRaises(Exception):
            self.controller.apply("agent-1", [{"type": "click", "button": "left"}])

        self.assertEqual(self.runner.commands, [])

    def test_human_takeover_between_batch_actions_stops_remaining_input(self):
        controller = self.controller
        lease = self.lease

        class TakeoverRunner(RecordingRunner):
            def run(self, command, cancelled=None):
                super().run(command, cancelled)
                if len(self.commands) == 1:
                    lease.claim_human("browser-1")
                    controller.preempt()

        runner = TakeoverRunner()
        controller.runner = runner

        with self.assertRaises(ConflictError):
            controller.apply(
                "agent-1",
                [
                    {"type": "move", "x": 100, "y": 100},
                    {"type": "click", "button": "left"},
                ],
            )

        self.assertEqual(runner.commands, [["xdotool", "mousemove", "100", "100"]])
        self.assertEqual(runner.cancel_calls, 1)

    def test_preemption_releases_held_mouse_and_key_state(self):
        controller = self.controller
        lease = self.lease

        class InFlightRunner(RecordingRunner):
            def run(self, command, cancelled=None):
                super().run(command, cancelled)
                if command[:3] == ["xdotool", "keydown", "alt"]:
                    lease.claim_human("browser-1")
                    controller.preempt()
                    raise ConflictError("preempted")

        runner = InFlightRunner()
        controller.runner = runner

        with self.assertRaises(ConflictError):
            controller.apply(
                "agent-1",
                [{"type": "hold_key", "key": "alt", "durationMs": 10_000}],
            )

        self.assertIn(["xdotool", "keyup", "alt"], runner.commands)
        self.assertEqual(runner.cancel_calls, 1)

    def test_drag_does_not_use_sync_for_same_position(self):
        self.controller.apply(
            "agent-1",
            [{"type": "drag", "x": 40, "y": 50, "toX": 40, "toY": 50}],
        )

        self.assertNotIn("--sync", self.runner.commands[0])

    def test_long_batch_renews_agent_lease_before_each_action(self):
        clock = FakeClock()
        lease = ControlLease(clock=clock, agent_ttl=12.0)
        lease.claim_agent("agent-1")

        class AdvancingRunner(RecordingRunner):
            def run(self, command, cancelled=None):
                super().run(command, cancelled)
                if len(self.commands) == 1:
                    clock.value = 15.0

        controller = InputController(
            width=1440, height=900, runner=AdvancingRunner(), lease=lease
        )

        controller.apply(
            "agent-1",
            [
                {"type": "click", "button": "left"},
                {"type": "click", "button": "left"},
            ],
        )

        self.assertEqual(len(controller.runner.commands), 2)
        self.assertEqual(lease.state()["owner"], "agent")


if __name__ == "__main__":
    unittest.main()
