"""In-memory event log for operator dashboards and debugging."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any


class EventLog:
    def __init__(self, *, capacity: int = 200) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._started_at = time.monotonic()

    def emit(self, kind: str, title: str, detail: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._entries.append(
                {
                    "id": uuid.uuid4().hex[:16],
                    "createdAtMs": round((time.monotonic() - self._started_at) * 1000),
                    "kind": kind,
                    "title": title,
                    "detail": detail or {},
                }
            )

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)[-limit:]

    def uptime_ms(self) -> int:
        return round((time.monotonic() - self._started_at) * 1000)
