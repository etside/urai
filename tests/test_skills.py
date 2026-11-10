"""skills.add_skill scaffolding + slug rules (CLI `urai skill add`)."""
import tempfile
import unittest
from pathlib import Path

from jev import skills


class SlugTests(unittest.TestCase):
    def test_normalizes(self):
        self.assertEqual(skills._slug("Code Review!"), "code-review")
        self.assertEqual(skills._slug("  My  Skill  "), "my-skill")

    def test_rejects_empty(self):
        with tempfile.TemporaryDirectory() as d:
            old = skills.SKILL_DIR
            skills.SKILL_DIR = Path(d)
            try:
                with self.assertRaises(ValueError):
                    skills.add_skill("!!!")
            finally:
                skills.SKILL_DIR = old


class AddSkillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = skills.SKILL_DIR
        skills.SKILL_DIR = Path(self._tmp.name)

    def tearDown(self):
        skills.SKILL_DIR = self._old
        self._tmp.cleanup()

    def test_add_creates_frontmatter(self):
        info = skills.add_skill("Data Cleaner", "tidy CSV files")
        p = Path(info["path"])
        self.assertTrue(p.is_file())
        text = p.read_text()
        self.assertTrue(text.startswith("---"))
        self.assertIn("name: data-cleaner", text)
        self.assertIn("description: tidy CSV files", text)

    def test_add_default_description(self):
        info = skills.add_skill("solo")
        self.assertIn("solo", info["description"])

    def test_duplicate_raises(self):
        skills.add_skill("dup")
        with self.assertRaises(ValueError):
            skills.add_skill("dup")

    def test_added_skill_is_listed(self):
        skills.add_skill("finder", "find things in a repo")
        names = {s["name"] for s in skills.all_skills()}
        self.assertIn("finder", names)

    def test_cli_skill_add(self):
        from jev import cli
        cli.main(["skill", "add", "clitest", "--desc", "from cli"])
        p = Path(self._tmp.name) / "clitest" / "SKILL.md"
        self.assertTrue(p.is_file())
        self.assertIn("from cli", p.read_text())


if __name__ == "__main__":
    unittest.main()
