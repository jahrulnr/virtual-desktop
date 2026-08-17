"""Prometheus-style counters for the control API."""

from __future__ import annotations

import threading
from collections import defaultdict


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def inc(self, name: str, value: int = 1) -> None:
        if value <= 0:
            return
        with self._lock:
            self._counters[name] += value

    def prometheus(self) -> str:
        with self._lock:
            lines = [
                "# HELP relay_info Static build metadata for Relay desktop.",
                "# TYPE relay_info gauge",
                "relay_info 1",
            ]
            for key in sorted(self._counters):
                metric = key.split("{", 1)[0]
                lines.append(f"# TYPE {metric} counter")
                lines.append(f"{key} {self._counters[key]}")
            return "\n".join(lines) + "\n"
