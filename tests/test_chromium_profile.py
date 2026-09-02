import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "desktop/scripts/configure-chromium-profile.py"
MODULE_SPEC = importlib.util.spec_from_file_location("configure_chromium_profile", SCRIPT_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULE)


class ChromiumProfileTests(unittest.TestCase):
    def test_hides_bookmark_bar_without_touching_other_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Preferences"
            path.write_text(json.dumps({
                "bookmark_bar": {"show_on_all_tabs": True},
                "browser": {"show_home_button": True},
            }))
            original_stat = path.stat()

            self.assertTrue(MODULE._set_bookmark_bar_hidden(path))
            result = json.loads(path.read_text())
            updated_stat = path.stat()

            self.assertFalse(result["bookmark_bar"]["show_on_all_tabs"])
            self.assertTrue(result["browser"]["show_home_button"])
            self.assertEqual(updated_stat.st_uid, original_stat.st_uid)
            self.assertEqual(updated_stat.st_gid, original_stat.st_gid)
            self.assertEqual(
                stat.S_IMODE(updated_stat.st_mode),
                stat.S_IMODE(original_stat.st_mode),
            )
            self.assertFalse(MODULE._set_bookmark_bar_hidden(path))

    def test_missing_or_invalid_preferences_are_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            invalid = Path(directory) / "invalid"
            invalid.write_text("not json")

            self.assertFalse(MODULE._set_bookmark_bar_hidden(missing))
            self.assertFalse(MODULE._set_bookmark_bar_hidden(invalid))
            self.assertEqual(invalid.read_text(), "not json")

    def test_configure_profile_applies_existing_and_master_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile" / "Preferences"
            master = root / "master_preferences"
            profile.parent.mkdir()
            profile.write_text(json.dumps({
                "bookmark_bar": {"show_on_all_tabs": True},
                "session": {
                    "restore_on_startup": 1,
                    "startup_urls": ["http://127.0.0.1:8080/"],
                },
            }))
            master.write_text(json.dumps({"bookmark_bar": {"show_on_all_tabs": True}}))

            self.assertEqual(MODULE.configure_profile(profile, master), 0)
            result = json.loads(profile.read_text())
            self.assertFalse(result["bookmark_bar"]["show_on_all_tabs"])
            self.assertEqual(result["session"]["restore_on_startup"], 4)
            self.assertEqual(result["session"]["startup_urls"], [MODULE.DEFAULT_START_PAGE])
            self.assertFalse(json.loads(master.read_text())["bookmark_bar"]["show_on_all_tabs"])
            master_result = json.loads(master.read_text())
            self.assertEqual(master_result["session"]["restore_on_startup"], 4)
            self.assertEqual(master_result["session"]["startup_urls"], [MODULE.DEFAULT_START_PAGE])

    def test_oversized_window_placement_is_reset_for_showcase(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Preferences"
            path.write_text(json.dumps({
                "browser": {
                    "window_placement": {
                        "left": 120,
                        "top": 29,
                        "right": 1328,
                        "bottom": 920,
                        "maximized": False,
                    },
                },
            }))

            self.assertTrue(MODULE._set_showcase_window_placement(path))
            result = json.loads(path.read_text())
            self.assertEqual(
                result["browser"]["window_placement"],
                MODULE.SHOWCASE_WINDOW_PLACEMENT,
            )

    def test_safe_window_placement_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Preferences"
            placement = {
                "left": 170,
                "top": 41,
                "right": 1278,
                "bottom": 852,
                "maximized": False,
            }
            path.write_text(json.dumps({"browser": {"window_placement": placement}}))

            self.assertFalse(MODULE._set_showcase_window_placement(path))
            self.assertEqual(
                json.loads(path.read_text())["browser"]["window_placement"],
                placement,
            )


if __name__ == "__main__":
    unittest.main()
