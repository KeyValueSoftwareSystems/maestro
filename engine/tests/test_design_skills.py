"""Contract tests for the design writer skills: no artificial word limits."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDLC = ROOT / "skills" / "core" / "sdlc"


class DesignSkillContractTest(unittest.TestCase):
    def test_the_prd_writer_never_forces_a_word_limit(self):
        text = (SDLC / "prd-writing" / "SKILL.md").read_text(encoding="utf-8").lower()
        self.assertIn("no word-count target or ceiling", text)

    def test_current_writers_never_force_a_word_limit(self):
        # the plan's size is set by its type (a minor plan is 5-10 lines), never by a word count
        for name in ("prd-writing", "plan-writing"):
            text = (SDLC / name / "SKILL.md").read_text(encoding="utf-8").lower()
            self.assertNotIn("word maximum", text, name)
            self.assertNotIn("validator ceiling", text, name)


if __name__ == "__main__":
    unittest.main()
