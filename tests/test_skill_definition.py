import re
import unittest
from pathlib import Path


SKILL_ROOT = (
    Path(__file__).parents[1]
    / "desktop/home/.agents/skills/os-operator"
)


class SkillDefinitionTests(unittest.TestCase):
    def test_skill_has_complete_frontmatter_and_operating_contract(self):
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<header>.*?)\n---\n", content, re.DOTALL)

        self.assertIsNotNone(match, "SKILL.md must begin with YAML frontmatter")
        header = match.group("header")
        self.assertRegex(header, r"(?m)^name: os-operator$")
        self.assertRegex(header, r"(?m)^description: \S.+$")
        for heading in (
            "## Operating loop",
            "## Input primitives",
            "## Runtime installation",
            "## Authority boundary",
        ):
            self.assertIn(heading, content)

    def test_agent_metadata_and_helper_are_present(self):
        metadata = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")

        self.assertIn('display_name: "OS Operator"', metadata)
        self.assertIn("$os-operator", metadata)
        self.assertTrue((SKILL_ROOT / "scripts/relayctl.py").is_file())


if __name__ == "__main__":
    unittest.main()
