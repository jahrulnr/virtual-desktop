import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).parents[1]
PANEL_CONFIG = (
    ROOT
    / "desktop/home/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
)
ENTRYPOINT = ROOT / "desktop/scripts/entrypoint.sh"
PLAYWRIGHT_CONFIG = ROOT / "desktop/config/playwright.json"
XVFB_CONFIGS = (
    ROOT / "desktop/config/supervisord.conf",
    ROOT / "desktop/scripts/run-native.sh",
)


class DesktopShowcaseDefaultsTests(unittest.TestCase):
    def test_launcher_panel_hides_when_an_app_overlaps_it(self):
        root = ET.parse(PANEL_CONFIG).getroot()
        panel = root.find(".//property[@name='panel-2']")
        self.assertIsNotNone(panel)

        properties = {
            prop.attrib["name"]: prop.attrib for prop in panel.findall("property")
        }
        self.assertEqual(properties["autohide-behavior"]["value"], "1")

    def test_existing_desktop_volumes_receive_the_panel_update(self):
        entrypoint = ENTRYPOINT.read_text()
        self.assertIn(".relay-xfce-v2", entrypoint)
        self.assertIn("install -D -m 0644", entrypoint)
        self.assertIn(
            "/opt/relay/home-template/.config/xfce4/xfconf/"
            "xfce-perchannel-xml/xfce4-panel.xml",
            entrypoint,
        )

    def test_chromium_defaults_are_inset_for_showcase(self):
        config = json.loads(PLAYWRIGHT_CONFIG.read_text())
        launch_args = config["browser"]["launchOptions"]["args"]
        viewport = config["browser"]["contextOptions"]["viewport"]

        self.assertIn("--window-size=1200,760", launch_args)
        self.assertIn("--window-position=120,60", launch_args)
        self.assertEqual(viewport, {"width": 1200, "height": 760})

    def test_xvfb_uses_showcase_dpi(self):
        for config_path in XVFB_CONFIGS:
            self.assertIn("-dpi 80", config_path.read_text())


if __name__ == "__main__":
    unittest.main()
