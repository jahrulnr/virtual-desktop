"""FFmpeg recording with a pointer-following AI showcase camera."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .showcase import (
    SHOWCASE_ACTIVE_ZOOM,
    SHOWCASE_IDLE_ZOOM,
    SHOWCASE_TRANSITION_SECONDS,
)


RECORDING_FRAME_RATE = 30


def render_timeout_seconds(duration_seconds: float) -> int:
    """Bound rendering time while allowing long recordings to finish."""
    return max(900, math.ceil(max(0.0, duration_seconds) * 4 + 60))


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


@dataclass(frozen=True)
class CameraKeyframe:
    elapsed_seconds: float
    crop_x: int
    crop_y: int
    zoom: float = SHOWCASE_ACTIVE_ZOOM


def smooth_camera_keyframes(
    keyframes: list[CameraKeyframe],
    *,
    duration_seconds: float,
) -> list[CameraKeyframe]:
    """Sample interruptible ease-out camera motion at the recording frame rate."""
    if not keyframes:
        return []

    recording_end = max(0.0, duration_seconds)
    ordered = [frame for frame in keyframes if frame.elapsed_seconds <= recording_end]
    if not ordered:
        return []

    initial = ordered[0]
    samples = [CameraKeyframe(0.0, initial.crop_x, initial.crop_y, initial.zoom)]
    transition_started = 0.0
    transition_end = 0.0
    transition_from = (float(initial.crop_x), float(initial.crop_y))
    transition_to = transition_from
    transition_from_zoom = float(initial.zoom)
    transition_to_zoom = transition_from_zoom

    def transition_end_for(timestamp: float) -> float:
        frame_index = math.floor(
            (timestamp + SHOWCASE_TRANSITION_SECONDS) * RECORDING_FRAME_RATE + 0.5
        )
        return max(timestamp, frame_index / RECORDING_FRAME_RATE)

    def position_at(timestamp: float) -> tuple[float, float]:
        transition_duration = transition_end - transition_started
        if transition_duration <= 0:
            return transition_to
        progress = min(
            1.0,
            max(0.0, (timestamp - transition_started) / transition_duration),
        )
        eased = 1.0 - (1.0 - progress) ** 3
        return (
            transition_from[0] + (transition_to[0] - transition_from[0]) * eased,
            transition_from[1] + (transition_to[1] - transition_from[1]) * eased,
        )

    def progress_at(timestamp: float) -> float:
        transition_duration = transition_end - transition_started
        if transition_duration <= 0:
            return 1.0
        return min(1.0, max(0.0, (timestamp - transition_started) / transition_duration))

    def zoom_at(timestamp: float) -> float:
        progress = progress_at(timestamp)
        return transition_from_zoom + (transition_to_zoom - transition_from_zoom) * progress

    event_index = 1
    last_frame_index = max(
        0,
        math.ceil(recording_end * RECORDING_FRAME_RATE - 1e-9) - 1,
    )
    motion_end = min(
        last_frame_index / RECORDING_FRAME_RATE,
        transition_end_for(max(0.0, ordered[-1].elapsed_seconds)),
    )
    final_frame_index = math.floor(motion_end * RECORDING_FRAME_RATE + 1e-9)
    for frame_index in range(1, final_frame_index + 1):
        timestamp = frame_index / RECORDING_FRAME_RATE
        while (
            event_index < len(ordered)
            and ordered[event_index].elapsed_seconds <= timestamp
        ):
            event = ordered[event_index]
            event_time = max(0.0, event.elapsed_seconds)
            transition_from = position_at(event_time)
            transition_to = (float(event.crop_x), float(event.crop_y))
            transition_from_zoom = zoom_at(event_time)
            transition_to_zoom = float(event.zoom)
            transition_started = event_time
            transition_end = transition_end_for(event_time)
            event_index += 1

        position = position_at(timestamp)
        zoom = zoom_at(timestamp)
        sample = CameraKeyframe(timestamp, round(position[0]), round(position[1]), zoom)
        previous = samples[-1]
        settled_on_target = (
            event_index > 1
            and frame_index == final_frame_index
            and timestamp >= transition_end
        )
        if (
            (sample.crop_x, sample.crop_y) != (previous.crop_x, previous.crop_y)
            or sample.zoom != previous.zoom
            or settled_on_target
        ):
            samples.append(sample)

    return samples


def camera_crop(
    width: int,
    height: int,
    zoom: float,
    pivot: dict[str, int],
) -> tuple[int, int, int, int]:
    """Return an even crop rectangle equivalent to CSS scale around a pivot."""
    crop_width = max(2, int(width / zoom) // 2 * 2)
    crop_height = max(2, int(height / zoom) // 2 * 2)
    x = round(pivot["x"] * (1 - 1 / zoom))
    y = round(pivot["y"] * (1 - 1 / zoom))
    x = min(width - crop_width, max(0, x))
    y = min(height - crop_height, max(0, y))
    return crop_width, crop_height, x, y


class ScreenRecorder:
    OUTPUT_DIR = Path(os.environ.get("RELAY_RECORDING_DIR", "/home/desktop/Downloads/recordings"))
    MAX_BYTES = 512 * 1024 * 1024

    def __init__(self, *, display: str | None = None, width: int = 1440, height: int = 900) -> None:
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("recording dimensions must be positive even integers")
        self.display = display or os.environ.get("DISPLAY", ":0")
        self.width = width
        self.height = height
        self.output_dir = Path(os.environ.get("RELAY_RECORDING_DIR", str(self.OUTPUT_DIR)))
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._rendering = False
        self._started_at = 0.0
        self._raw_path: Path | None = None
        self._output_path: Path | None = None
        self._camera_keyframes: list[CameraKeyframe] = []

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
            if self._rendering or (self._process is not None and self._process.poll() is None):
                raise RecordingConflictError("a recording is already active")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            suffix = time.strftime("%Y%m%d-%H%M%S")
            output_path = self.output_dir / f"relay-{suffix}.mp4"
            raw_path = self.output_dir / f".relay-{suffix}.source.mp4"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "x11grab",
                "-framerate",
                str(RECORDING_FRAME_RATE),
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
                str(raw_path),
            ]
            self._process = subprocess.Popen(command)
            self._started_at = time.monotonic()
            self._raw_path = raw_path
            self._output_path = output_path
            self._camera_keyframes = []
            return self.state()

    def track_camera(self, state: dict[str, object]) -> None:
        """Record a camera keyframe only while X11 capture is active."""
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return
            pivot = state.get("pivot")
            if not isinstance(pivot, dict):
                return
            x = pivot.get("x")
            y = pivot.get("y")
            if isinstance(x, bool) or not isinstance(x, int):
                return
            if isinstance(y, bool) or not isinstance(y, int):
                return
            zoom = state.get("zoom")
            if isinstance(zoom, bool) or not isinstance(zoom, (int, float)):
                return
            if not math.isfinite(float(zoom)):
                return
            if not SHOWCASE_IDLE_ZOOM <= float(zoom) <= SHOWCASE_ACTIVE_ZOOM:
                return
            _, _, crop_x, crop_y = camera_crop(
                self.width,
                self.height,
                float(zoom),
                {"x": x, "y": y},
            )
            if self._camera_keyframes:
                latest = self._camera_keyframes[-1]
                if (latest.crop_x, latest.crop_y) == (crop_x, crop_y) and math.isclose(
                    latest.zoom, float(zoom), rel_tol=0.0, abs_tol=1e-6
                ):
                    return
            self._camera_keyframes.append(
                CameraKeyframe(
                    elapsed_seconds=max(0.0, time.monotonic() - self._started_at),
                    crop_x=crop_x,
                    crop_y=crop_y,
                    zoom=float(zoom),
                )
            )

    def stop(self, *, save: bool) -> dict[str, object]:
        with self._lock:
            process, raw_path, output_path, keyframes = self._stop_capture_locked()
            duration_ms = round((time.monotonic() - self._started_at) * 1000)
            if process is None or output_path is None or raw_path is None:
                raise RecordingConflictError("no recording is active")
            self._rendering = True

        try:
            if not save:
                raw_path.unlink(missing_ok=True)
                return {"status": "discarded"}
            if process.returncode not in (0, None) and not raw_path.exists():
                raise RecordingError("recording process failed before saving")
            if not raw_path.exists() or raw_path.stat().st_size <= 0:
                raise RecordingError("recording produced an empty file")
            self._render_showcase(
                raw_path,
                output_path,
                keyframes,
                duration_seconds=duration_ms / 1000,
            )
            size = output_path.stat().st_size if output_path.exists() else 0
            if size <= 0:
                output_path.unlink(missing_ok=True)
                raise RecordingError("showcase render produced an empty file")
            if size > self.MAX_BYTES:
                output_path.unlink(missing_ok=True)
                raise RecordingError("recording exceeded the 512 MiB limit")
            raw_path.unlink(missing_ok=True)
            return {
                "status": "saved",
                "path": str(output_path),
                "sizeBytes": size,
                "durationMs": duration_ms,
            }
        finally:
            with self._lock:
                self._rendering = False

    def _render_showcase(
        self,
        raw_path: Path,
        output_path: Path,
        keyframes: list[CameraKeyframe],
        *,
        duration_seconds: float,
    ) -> None:
        motion = smooth_camera_keyframes(
            keyframes,
            duration_seconds=duration_seconds,
        )
        if not motion:
            motion = [CameraKeyframe(0.0, 0, 0, SHOWCASE_IDLE_ZOOM)]

        def timeline_expression(attribute: str) -> str:
            points: list[tuple[int, float]] = []
            for frame in motion:
                frame_index = max(0, round(frame.elapsed_seconds * RECORDING_FRAME_RATE))
                value = float(getattr(frame, attribute))
                if points and points[-1][0] == frame_index:
                    points[-1] = (frame_index, value)
                else:
                    points.append((frame_index, value))
            expression = f"{points[-1][1]:.6f}"
            for index in range(len(points) - 2, -1, -1):
                _, value = points[index]
                next_frame = points[index + 1][0]
                expression = f"if(lt(on,{next_frame}),{value:.6f},{expression})"
            return expression

        zoom_expression = timeline_expression("zoom")
        x_expression = timeline_expression("crop_x")
        y_expression = timeline_expression("crop_y")
        rendering_path = output_path.with_name(f".{output_path.stem}.rendering.mp4")
        filters = [
            (
                f"zoompan=z='{zoom_expression}':x='{x_expression}':y='{y_expression}':"
                f"d=1:s={self.width}x{self.height}:fps={RECORDING_FRAME_RATE}"
            )
        ]
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(raw_path),
            "-vf",
            ",".join(filters),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(rendering_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                timeout=render_timeout_seconds(duration_seconds),
            )
        except (OSError, subprocess.SubprocessError) as error:
            rendering_path.unlink(missing_ok=True)
            raise RecordingError(
                "showcase render failed; raw capture retained for recovery"
            ) from error
        if not rendering_path.exists() or rendering_path.stat().st_size <= 0:
            rendering_path.unlink(missing_ok=True)
            raise RecordingError(
                "showcase render failed; raw capture retained for recovery"
            )
        rendering_path.replace(output_path)

    def _cleanup_finished(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._raw_path = None
            self._output_path = None
            self._camera_keyframes = []

    def _stop_capture_locked(
        self,
    ) -> tuple[
        subprocess.Popen[bytes] | None,
        Path | None,
        Path | None,
        list[CameraKeyframe],
    ]:
        if self._process is None:
            return None, None, None, []
        process = self._process
        raw_path = self._raw_path
        output_path = self._output_path
        keyframes = list(self._camera_keyframes)
        self._process = None
        self._raw_path = None
        self._output_path = None
        self._camera_keyframes = []
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        return process, raw_path, output_path, keyframes
