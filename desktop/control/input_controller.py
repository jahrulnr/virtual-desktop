"""Validated XTEST input adapter for the agent operator."""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Sequence
from collections.abc import Callable
from typing import Protocol

from .domain import ConflictError, ControlLease, ValidationError


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        cancelled: Callable[[], bool] | None = None,
    ) -> None: ...

    def cancel_current(self) -> None: ...


class SubprocessRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: subprocess.Popen[bytes] | None = None

    def run(
        self,
        command: list[str],
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        with self._lock:
            if cancelled is not None and cancelled():
                raise ConflictError("desktop input was preempted")
            process = subprocess.Popen(command)
            self._current = process
        try:
            return_code = process.wait(timeout=15)
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command)
        except subprocess.TimeoutExpired:
            self._stop(process)
            raise
        finally:
            with self._lock:
                if self._current is process:
                    self._current = None

    def cancel_current(self) -> None:
        with self._lock:
            process = self._current
        if process is not None and process.poll() is None:
            self._stop(process)

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


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
        self._state_lock = threading.Lock()
        self._generation = 0
        self._held_buttons: set[str] = set()
        self._held_keys: set[str] = set()

    def apply(self, owner_id: str, actions: object) -> None:
        self.lease.assert_owner("agent", owner_id)
        commands = self._validate_batch(actions)
        assert isinstance(actions, list)
        with self._state_lock:
            generation = self._generation
        for action, command in zip(actions, commands, strict=True):
            self._assert_active(owner_id, generation)
            assert isinstance(action, dict)
            self._mark_held(action)
            try:
                self.runner.run(
                    command,
                    lambda: self._cancelled(generation),
                )
            except Exception:
                self._release_held()
                if self._cancelled(generation):
                    raise ConflictError("desktop input was preempted") from None
                raise
            else:
                self._complete_action(action)

    def preempt(self) -> None:
        """Cancel live AI input and release any X state before human claim returns."""
        with self._state_lock:
            self._generation += 1
        cancel = getattr(self.runner, "cancel_current", None)
        if callable(cancel):
            cancel()
        self._release_held()

    def _assert_active(self, owner_id: str, generation: int) -> None:
        # Renew before expiry checks so long batches (smooth paths, hold_key, wait)
        # can exceed the 12-second agent TTL without losing mid-batch ownership.
        self.lease.extend_if_owner("agent", owner_id)
        if self._cancelled(generation):
            raise ConflictError("desktop input was preempted")

    def _cancelled(self, generation: int) -> bool:
        with self._state_lock:
            return generation != self._generation

    def _mark_held(self, action: dict[object, object]) -> None:
        with self._state_lock:
            if action.get("type") in {"drag", "button"}:
                button = action.get("button", "left")
                if isinstance(button, str):
                    self._held_buttons.add(button)
            if action.get("type") == "hold_key":
                key = action.get("key")
                if isinstance(key, str):
                    self._held_keys.add(key)

    def _complete_action(self, action: dict[object, object]) -> None:
        with self._state_lock:
            action_type = action.get("type")
            if action_type == "drag" or (
                action_type == "button" and action.get("state") == "up"
            ):
                button = action.get("button", "left")
                if isinstance(button, str):
                    self._held_buttons.discard(button)
            if action_type == "hold_key":
                key = action.get("key")
                if isinstance(key, str):
                    self._held_keys.discard(key)

    def _release_held(self) -> None:
        with self._state_lock:
            buttons = sorted(self._held_buttons)
            keys = sorted(self._held_keys)
            self._held_buttons.clear()
            self._held_keys.clear()
        for key in keys:
            self._cleanup(["xdotool", "keyup", key])
        for button in buttons:
            self._cleanup(["xdotool", "mouseup", self.BUTTONS[button]])

    def _cleanup(self, command: list[str]) -> None:
        try:
            self.runner.run(command)
        except (OSError, subprocess.SubprocessError):
            pass

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
        if action_type == "drag":
            return self._drag(action)
        if action_type == "button":
            return self._button(action)
        if action_type == "hold_key":
            return self._hold_key(action)
        if action_type == "wait":
            return self._wait(action)
        raise ValidationError("unsupported action type")

    def _coordinates(
        self,
        action: dict[object, object],
        x_name: str = "x",
        y_name: str = "y",
    ) -> tuple[int, int]:
        x, y = action.get(x_name), action.get(y_name)
        if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < self.width:
            raise ValidationError(f"{x_name} is outside the desktop")
        if isinstance(y, bool) or not isinstance(y, int) or not 0 <= y < self.height:
            raise ValidationError(f"{y_name} is outside the desktop")
        return x, y

    def _move(self, action: dict[object, object]) -> list[str]:
        x, y = self._coordinates(action)
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
        direction = action.get("direction")
        if direction is None:
            direction = "up" if delta > 0 else "down"
        if direction not in {"up", "down", "left", "right"}:
            raise ValidationError("scroll direction must be up, down, left, or right")
        button = {"up": "4", "down": "5", "left": "6", "right": "7"}[direction]
        return ["xdotool", "click", "--repeat", str(abs(delta)), "--delay", "35", button]

    def _drag(self, action: dict[object, object]) -> list[str]:
        x, y = self._coordinates(action)
        to_x, to_y = self._coordinates(action, "toX", "toY")
        button = action.get("button", "left")
        if button not in self.BUTTONS:
            raise ValidationError("button must be left, middle, or right")
        number = self.BUTTONS[button]
        return [
            "xdotool",
            "mousemove",
            str(x),
            str(y),
            "mousedown",
            number,
            "mousemove",
            str(to_x),
            str(to_y),
            "mouseup",
            number,
        ]

    def _button(self, action: dict[object, object]) -> list[str]:
        button = action.get("button", "left")
        if button not in self.BUTTONS:
            raise ValidationError("button must be left, middle, or right")
        state = action.get("state")
        if state not in {"down", "up"}:
            raise ValidationError("button state must be down or up")
        return ["xdotool", f"mouse{state}", self.BUTTONS[button]]

    def _hold_key(self, action: dict[object, object]) -> list[str]:
        key = action.get("key")
        if not isinstance(key, str) or not self.KEY_PATTERN.fullmatch(key):
            raise ValidationError("key may contain only letters, numbers, and underscore")
        duration = action.get("durationMs")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 1 <= duration <= 10_000
        ):
            raise ValidationError("durationMs must be between 1 and 10000")
        seconds = f"{duration / 1000:.3f}"
        return ["xdotool", "keydown", key, "sleep", seconds, "keyup", key]

    @staticmethod
    def _wait(action: dict[object, object]) -> list[str]:
        duration = action.get("durationMs")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 1 <= duration <= 10_000
        ):
            raise ValidationError("durationMs must be between 1 and 10000")
        return ["xdotool", "sleep", f"{duration / 1000:.3f}"]
