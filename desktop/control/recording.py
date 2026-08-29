"""FFmpeg-based screen recording for the shared X11 desktop."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class RecordingError(Exception):
    """Base class for recording failures safe to expose via the API."""


class RecordingConflictError(RecordingError):
    """A recording is already active or no recording is active."""


@dataclass(frozen=True)
class RecordingState:
    active: bool
    startedAtMs: int | None = None
    outputPath: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"active": self.active}
        if self.startedAtMs is not None:
            payload["startedAtMs"] = self.startedAtMs
        if self.outputPath is not None:
            payload["outputPath"] = self.outputPath
        return payload


class ScreenRecorder:
    OUTPUT_DIR = Path(os.environ.get("RELAY_RECORDING_DIR", "/home/desktop/Downloads/recordings"))
    MAX_BYTES = 512 * 1024 * 1024

    def __init__(self, *, display: str | None = None, width: int = 1440, height: int = 900) -> None:
        self.display = display or os.environ.get("DISPLAY", ":0")
        self.width = width
        self.height = height
        self.output_dir = Path(os.environ.get("RELAY_RECORDING_DIR", str(self.OUTPUT_DIR)))
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._started_at = 0.0
        self._output_path: Path | None = None

    def state(self) -> RecordingState:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return RecordingState(active=False)
            return RecordingState(
                active=True,
                startedAtMs=round(self._started_at * 1000),
                outputPath=str(self._output_path) if self._output_path else None,
            )

    def start(self) -> RecordingState:
        with self._lock:
            self._cleanup_finished()
            if self._process is not None and self._process.poll() is None:
                raise RecordingConflictError("a recording is already active")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            filename = time.strftime("relay-%Y%m%d-%H%M%S.mp4")
            output_path = self.output_dir / filename
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "x11grab",
                "-video_size",
                f"{self.width}x{self.height}",
                "-i",
                self.display,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                str(output_path),
            ]
            process = subprocess.Popen(command)
            self._process = process
            self._started_at = time.monotonic()
            self._output_path = output_path
            return self.state()

    def stop(self, *, save: bool) -> dict[str, object]:
        with self._lock:
            process, output_path = self._stop_process()
            if output_path is None:
                raise RecordingConflictError("no recording is active")
            if not save:
                output_path.unlink(missing_ok=True)
                return {"status": "discarded"}
            if process.returncode not in (0, None) and not output_path.exists():
                raise RecordingError("recording process failed before saving")
            size = output_path.stat().st_size if output_path.exists() else 0
            if size <= 0:
                output_path.unlink(missing_ok=True)
                raise RecordingError("recording produced an empty file")
            if size > self.MAX_BYTES:
                output_path.unlink(missing_ok=True)
                raise RecordingError("recording exceeded the 512 MiB limit")
            return {
                "status": "saved",
                "path": str(output_path),
                "sizeBytes": size,
                "durationMs": round((time.monotonic() - self._started_at) * 1000),
            }

    def _cleanup_finished(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._output_path = None

    def _stop_process(self) -> tuple[subprocess.Popen[bytes], Path | None]:
        self._cleanup_finished()
        if self._process is None or self._output_path is None:
            return subprocess.Popen(["true"]), None
        process = self._process
        output_path = self._output_path
        self._process = None
        self._output_path = None
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        return process, output_path
