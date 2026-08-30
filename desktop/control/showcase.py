"""Pointer-following presentation camera for AI-operated desktop showcases."""

from __future__ import annotations

import threading
from collections.abc import Callable


SHOWCASE_IDLE_ZOOM = 1.0
SHOWCASE_ACTIVE_ZOOM = 2.0
SHOWCASE_IDLE_TIMEOUT_SECONDS = 1.0
SHOWCASE_TRANSITION_SECONDS = 0.24


class ShowcaseCamera:
    """Keep one fixed-zoom camera centered on the AI's latest pointer activity."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        idle_timeout_seconds: float = SHOWCASE_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self.width = width
        self.height = height
        self.idle_timeout_seconds = max(0.0, idle_timeout_seconds)
        self._lock = threading.Lock()
        self._pivot = {"x": width // 2, "y": height // 2}
        self._active = False
        self._activity_generation = 0
        self._idle_timer: threading.Timer | None = None
        self._listeners: list[Callable[[dict[str, object]], None]] = []

    def subscribe(self, listener: Callable[[dict[str, object]], None]) -> None:
        self._listeners.append(listener)

    def state(self) -> dict[str, object]:
        with self._lock:
            return self._state_locked()

    def follow(self, x: int, y: int) -> dict[str, object]:
        with self._lock:
            pivot = {
                "x": min(self.width - 1, max(0, x)),
                "y": min(self.height - 1, max(0, y)),
            }
            changed = pivot != self._pivot or not self._active
            self._pivot = pivot
            self._active = True
            self._activity_generation += 1
            generation = self._activity_generation
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = threading.Timer(
                self.idle_timeout_seconds,
                self._return_to_idle,
                args=(generation,),
            )
            self._idle_timer.daemon = True
            self._idle_timer.start()
            state = self._state_locked()
            listeners = tuple(self._listeners) if changed else ()
        for listener in listeners:
            listener(state)
        return state

    def _return_to_idle(self, generation: int) -> None:
        with self._lock:
            if generation != self._activity_generation or not self._active:
                return
            self._active = False
            self._idle_timer = None
            state = self._state_locked()
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)

    def _state_locked(self) -> dict[str, object]:
        return {
            "zoom": SHOWCASE_ACTIVE_ZOOM if self._active else SHOWCASE_IDLE_ZOOM,
            "pivot": dict(self._pivot),
            "display": {"width": self.width, "height": self.height},
        }
