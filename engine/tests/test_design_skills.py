"""Contract tests for the design writer skills: no artificial length limits."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_WRITERS = (
    ROOT / "skills" / "core" / "sdlc" / "prd-writing" / "SKILL.md",
    ROOT / "skills" / "core" / "sdlc" / "hld-writing" / "SKILL.md",
    ROOT / "skills" / "core" / "sdlc" / "lld-writing" / "SKILL.md",
)


class DesignSkillContractTest(unittest.TestCase):
    def test_current_writers_never_force_a_word_limit(self):
        for path in CURRENT_WRITERS:
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("no word-count target or ceiling", text)
            self.assertNotIn("word maximum", text)
            self.assertNotIn("validator ceiling", text)


if __name__ == "__main__":
    unittest.main()
