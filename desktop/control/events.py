"""In-memory event log for operator dashboards and debugging."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from typing import Any, Iterator


class EventLog:
    def __init__(self, *, capacity: int = 200) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []

    def emit(self, kind: str, title: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = {
            "id": uuid.uuid4().hex[:16],
            "createdAtMs": round((time.monotonic() - self._started_at) * 1000),
            "kind": kind,
            "title": title,
            "detail": detail or {},
        }
        with self._lock:
            self._entries.append(entry)
            for subscriber in self._subscribers:
                subscriber.put(entry)
        return entry

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)[-limit:]

    def uptime_ms(self) -> int:
        return round((time.monotonic() - self._started_at) * 1000)

    def subscribe(self, *, heartbeat_seconds: float = 20.0) -> Iterator[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
            backlog = list(self._entries)
        try:
            for entry in backlog:
                yield entry
            while True:
                try:
                    yield subscriber.get(timeout=heartbeat_seconds)
                except queue.Empty:
                    yield {
                        "id": uuid.uuid4().hex[:16],
                        "createdAtMs": self.uptime_ms(),
                        "kind": "heartbeat",
                        "title": "stream alive",
                        "detail": {},
                    }
        finally:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)
