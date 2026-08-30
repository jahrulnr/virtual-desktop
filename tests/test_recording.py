import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop.control.recording import (
    CameraKeyframe,
    RecordingConflictError,
    RecordingError,
    ScreenRecorder,
    camera_crop,
    render_timeout_seconds,
    smooth_camera_keyframes,
)


class ScreenRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def recording_process(self):
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = 0
        return process

    def test_camera_motion_eases_across_multiple_video_frames(self):
        frames = smooth_camera_keyframes(
            [
                CameraKeyframe(0.0, 80, 60),
                CameraKeyframe(1.0, 140, 90),
            ],
            duration_seconds=2.0,
        )

        motion = [frame for frame in frames if frame.elapsed_seconds > 1.0]
        self.assertGreaterEqual(len(motion), 4)
        self.assertLess(motion[0].crop_x, 140)
        self.assertLess(motion[0].crop_y, 90)
        self.assertEqual((motion[-1].crop_x, motion[-1].crop_y), (140, 90))
        self.assertEqual(
            [frame.crop_x for frame in motion],
            sorted(frame.crop_x for frame in motion),
        )
        self.assertEqual(
            [frame.crop_y for frame in motion],
            sorted(frame.crop_y for frame in motion),
        )

    def test_camera_motion_retargets_from_its_interpolated_position(self):
        frames = smooth_camera_keyframes(
            [
                CameraKeyframe(0.0, 80, 60),
                CameraKeyframe(1.0, 200, 120),
                CameraKeyframe(1.08, 20, 20),
            ],
            duration_seconds=2.0,
        )

        positions = [(frame.crop_x, frame.crop_y) for frame in frames]
        self.assertNotIn((200, 120), positions)
        self.assertEqual(positions[-1], (20, 20))
        self.assertTrue(all(20 <= x <= 200 and 20 <= y <= 120 for x, y in positions))
        self.assertTrue(
            all(abs(right[0] - left[0]) < 120 for left, right in zip(positions, positions[1:]))
        )

    def test_camera_motion_interpolates_active_zoom_and_returns_to_idle(self):
        frames = smooth_camera_keyframes(
            [
                CameraKeyframe(0.0, 0, 0, 1.0),
                CameraKeyframe(0.2, 40, 30, 1.5),
                CameraKeyframe(1.2, 40, 30, 1.0),
            ],
            duration_seconds=2.0,
        )

        zooms = [frame.zoom for frame in frames]
        self.assertEqual(zooms[0], 1.0)
        self.assertGreater(max(zooms), 1.0)
        self.assertEqual(frames[-1].zoom, 1.0)

    def test_camera_motion_settles_on_a_real_frame_before_a_nearby_recording_end(self):
        frames = smooth_camera_keyframes(
            [
                CameraKeyframe(0.0, 80, 60),
                CameraKeyframe(1.0, 140, 90),
            ],
            duration_seconds=1.25,
        )

        self.assertTrue(
            all(
                abs(frame.elapsed_seconds * 30 - round(frame.elapsed_seconds * 30))
                < 1e-9
                for frame in frames
            )
        )
        self.assertEqual(frames[-1], CameraKeyframe(37 / 30, 140, 90))

    def test_camera_transition_duration_is_rounded_to_the_nearest_video_frame(self):
        event_time = 1.02
        frames = smooth_camera_keyframes(
            [
                CameraKeyframe(0.0, 80, 60),
                CameraKeyframe(event_time, 140, 90),
            ],
            duration_seconds=2.0,
        )

        self.assertEqual(frames[-1], CameraKeyframe(38 / 30, 140, 90))
        self.assertLessEqual(abs((frames[-1].elapsed_seconds - event_time) - 0.24), 1 / 60)

    def test_render_timeout_scales_with_long_recordings(self):
        self.assertEqual(render_timeout_seconds(60), 900)
        self.assertEqual(render_timeout_seconds(3600), 14460)

    def test_camera_crop_matches_the_pointer_anchored_web_transform(self):
        self.assertEqual(
            camera_crop(1440, 900, 1.25, {"x": 900, "y": 420}),
            (1152, 720, 180, 84),
        )
        self.assertEqual(
            camera_crop(1440, 900, 1.25, {"x": 1439, "y": 899}),
            (1152, 720, 288, 180),
        )

    def test_start_captures_a_hidden_raw_source_at_thirty_fps(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = self.recording_process()

        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process) as popen,
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            state = recorder.start()

        command = popen.call_args.args[0]
        self.assertIn("-framerate", command)
        self.assertEqual(command[command.index("-framerate") + 1], "30")
        self.assertTrue(command[-1].endswith("/.relay-test.source.mp4"))
        self.assertTrue(state.outputPath.endswith("/relay-test.mp4"))

    def test_save_renders_the_camera_timeline_and_never_returns_raw_capture(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = self.recording_process()
        captured = {}

        def render(command, **kwargs):
            captured["command"] = command
            captured["timeout"] = kwargs["timeout"]
            Path(command[-1]).write_bytes(b"rendered-showcase" * 16)
            return subprocess.CompletedProcess(command, 0)

        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process),
            patch("desktop.control.recording.subprocess.run", side_effect=render),
            patch("desktop.control.recording.time.strftime", return_value="test"),
            patch("desktop.control.recording.time.monotonic", side_effect=[100.0, 100.0, 100.5, 101.0]),
        ):
            state = recorder.start()
            raw_path = recorder._raw_path
            self.assertIsNotNone(raw_path)
            raw_path.write_bytes(b"raw-x11-capture" * 16)
            recorder.track_camera({
                "zoom": 1.25,
                "pivot": {"x": 400, "y": 300},
                "display": {"width": 800, "height": 600},
            })
            recorder.track_camera({
                "zoom": 1.25,
                "pivot": {"x": 700, "y": 450},
                "display": {"width": 800, "height": 600},
            })
            result = recorder.stop(save=True)

        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["path"], state.outputPath)
        self.assertFalse(raw_path.exists())
        self.assertTrue(Path(state.outputPath).exists())
        filter_graph = captured["command"][captured["command"].index("-vf") + 1]
        self.assertIn("zoompan=", filter_graph)
        self.assertIn("s=800x600", filter_graph)
        self.assertIn("fps=30", filter_graph)
        self.assertNotIn("sendcmd", filter_graph)
        self.assertNotIn("crop@relay_camera", filter_graph)
        self.assertEqual(captured["timeout"], 900)

    def test_render_failure_keeps_raw_source_but_does_not_publish_it(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = self.recording_process()

        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process),
            patch(
                "desktop.control.recording.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]),
            ),
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            state = recorder.start()
            raw_path = recorder._raw_path
            raw_path.write_bytes(b"raw-x11-capture" * 16)
            with self.assertRaises(RecordingError):
                recorder.stop(save=True)

        self.assertTrue(raw_path.exists())
        self.assertFalse(Path(state.outputPath).exists())

    def test_discard_removes_the_raw_capture_and_allows_another_recording(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        first_process = self.recording_process()
        second_process = self.recording_process()

        with (
            patch(
                "desktop.control.recording.subprocess.Popen",
                side_effect=[first_process, second_process],
            ),
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            recorder.start()
            raw_path = recorder._raw_path
            raw_path.write_bytes(b"raw-x11-capture" * 16)
            result = recorder.stop(save=False)
            restarted = recorder.start()

        self.assertEqual(result, {"status": "discarded"})
        self.assertFalse(raw_path.exists())
        self.assertTrue(restarted.active)

    def test_start_while_active_raises_conflict(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = self.recording_process()
        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process),
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            recorder.start()
            with self.assertRaises(RecordingConflictError):
                recorder.start()

    def test_recorder_rejects_dimensions_that_yuv420p_cannot_encode(self):
        for width, height in ((799, 600), (800, 599), (0, 600)):
            with self.subTest(width=width, height=height):
                with self.assertRaisesRegex(ValueError, "positive even integers"):
                    ScreenRecorder(width=width, height=height)

    def test_stop_without_an_active_recording_does_not_spawn_a_dummy_process(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir

        with patch("desktop.control.recording.subprocess.Popen") as popen:
            with self.assertRaises(RecordingConflictError):
                recorder.stop(save=True)

        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
