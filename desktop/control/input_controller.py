"""Validated XTEST input adapter for the agent operator."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from typing import Protocol

from .domain import ControlLease, ValidationError


class CommandRunner(Protocol):
    def run(self, command: list[str]) -> None: ...


class SubprocessRunner:
    def run(self, command: list[str]) -> None:
        subprocess.run(command, check=True, timeout=15)


class InputController:
    BUTTONS = {"left": "1", "middle": "2", "right": "3"}
    KEY_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

    def __init__(
        self,
        *,
        width: int,
        height: int,
        runner: CommandRunner,
        lease: ControlLease,
    ) -> None:
        self.width = width
        self.height = height
        self.runner = runner
        self.lease = lease

    def apply(self, owner_id: str, actions: object) -> None:
        self.lease.assert_owner("agent", owner_id)
        commands = self._validate_batch(actions)
        for command in commands:
            self.runner.run(command)

    def _validate_batch(self, actions: object) -> list[list[str]]:
        if not isinstance(actions, list) or not 1 <= len(actions) <= 50:
            raise ValidationError("actions must contain between 1 and 50 items")
        return [self._command_for(action) for action in actions]

    def _command_for(self, action: object) -> list[str]:
        if not isinstance(action, dict):
            raise ValidationError("each action must be an object")
        action_type = action.get("type")
        if action_type == "move":
            return self._move(action)
        if action_type == "click":
            return self._click(action)
        if action_type == "text":
            return self._text(action)
        if action_type == "key":
            return self._key(action)
        if action_type == "scroll":
            return self._scroll(action)
        raise ValidationError("unsupported action type")

    def _move(self, action: dict[object, object]) -> list[str]:
        x, y = action.get("x"), action.get("y")
        if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < self.width:
            raise ValidationError("x is outside the desktop")
        if isinstance(y, bool) or not isinstance(y, int) or not 0 <= y < self.height:
            raise ValidationError("y is outside the desktop")
        # --sync waits for a position change and can hang when a caller repeats
        # the current coordinates. xdotool flushes this request before it exits.
        return ["xdotool", "mousemove", str(x), str(y)]

    def _click(self, action: dict[object, object]) -> list[str]:
        button = action.get("button", "left")
        if button not in self.BUTTONS:
            raise ValidationError("button must be left, middle, or right")
        count = action.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 3:
            raise ValidationError("click count must be between 1 and 3")
        command = ["xdotool", "click"]
        if count > 1:
            command.extend(["--repeat", str(count), "--delay", "80"])
        command.append(self.BUTTONS[button])
        return command

    def _text(self, action: dict[object, object]) -> list[str]:
        value = action.get("text")
        if not isinstance(value, str) or not 1 <= len(value) <= 4096:
            raise ValidationError("text must contain between 1 and 4096 characters")
        return [
            "xdotool",
            "type",
            "--clearmodifiers",
            "--delay",
            "2",
            "--",
            value,
        ]

    def _key(self, action: dict[object, object]) -> list[str]:
        keys = action.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
            raise ValidationError("keys must contain between 1 and 5 names")
        if not all(isinstance(key, str) and self.KEY_PATTERN.fullmatch(key) for key in keys):
            raise ValidationError("key names may contain only letters, numbers, and underscore")
        return ["xdotool", "key", "--clearmodifiers", "+".join(keys)]

    def _scroll(self, action: dict[object, object]) -> list[str]:
        delta = action.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0 or not -10 <= delta <= 10:
            raise ValidationError("scroll delta must be an integer from -10 to 10, excluding zero")
        button = "4" if delta > 0 else "5"
        return ["xdotool", "click", "--repeat", str(abs(delta)), "--delay", "35", button]
