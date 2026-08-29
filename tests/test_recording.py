import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop.control.recording import RecordingConflictError, ScreenRecorder


class ScreenRecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_start_and_stop_saves_file(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = MagicMock()
        process.poll.return_value = None
        output_path = self.output_dir / "relay-test.mp4"
        output_path.write_bytes(b"x" * 128)
        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process) as popen,
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            recorder.start()
            recorder._output_path = output_path
            result = recorder.stop(save=True)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["sizeBytes"], 128)
        self.assertTrue(popen.called)

    def test_start_while_active_raises_conflict(self):
        recorder = ScreenRecorder(width=800, height=600)
        recorder.output_dir = self.output_dir
        process = MagicMock()
        process.poll.return_value = None
        with (
            patch("desktop.control.recording.subprocess.Popen", return_value=process),
            patch("desktop.control.recording.time.strftime", return_value="test"),
        ):
            recorder.start()
            with self.assertRaises(RecordingConflictError):
                recorder.start()


if __name__ == "__main__":
    unittest.main()
