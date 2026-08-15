"""Regression tests for HLD/LLD design quality and implementation handoff."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
HLD_SKILL = ROOT / "skills" / "core" / "sdlc" / "plan" / "SKILL.md"
LLD_SKILL = ROOT / "skills" / "core" / "sdlc" / "repo-design" / "SKILL.md"


class DesignSkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hld = HLD_SKILL.read_text(encoding="utf-8")
        cls.lld = LLD_SKILL.read_text(encoding="utf-8")

    def test_hld_has_decision_focused_shape(self):
        for section in (
            "Decision summary",
            "Context and scope",
            "Proposed design",
            "Key decisions and trade-offs",
            "Delivery and risks",
            "Open questions",
        ):
            self.assertIn(section, self.hld)
        self.assertIn("700–1,400 words", self.hld)
        self.assertIn("without re-deciding", self.hld)

    def test_hld_does_not_force_artificial_design_work(self):
        lowered = self.hld.lower()
        self.assertIn("do not invent alternatives", lowered)
        self.assertIn("never add `n/a` headings", lowered)
        self.assertNotIn("2–3 genuinely different approaches", self.hld)
        self.assertNotIn("every section present", lowered)

    def test_lld_has_implementation_ready_shape(self):
        for section in (
            "Change summary",
            "Existing design seam",
            "Proposed changes",
            "Critical flows",
            "Implementation sequence",
            "Verification",
        ):
            self.assertIn(section, self.lld)
        self.assertIn("area | change | responsibility", self.lld)
        self.assertIn("claim | source", self.lld)
        self.assertIn("900–1,800 words", self.lld)
        self.assertIn("dependency-ordered increments", self.lld)
        self.assertIn("without another architecture pass", self.lld)

    def test_lld_omits_irrelevant_sections_instead_of_padding(self):
        lowered = self.lld.lower()
        self.assertIn("omit irrelevant optional sections completely", lowered)
        self.assertIn("do not add empty headings, `n/a` entries", lowered)
        self.assertNotIn("what the lld must cover (write all", lowered)
        self.assertNotIn("each constraint citing", lowered)

    def test_revision_feedback_never_becomes_document_content(self):
        for skill in (self.hld, self.lld):
            lowered = skill.lower()
            self.assertIn("feedback", lowered)
            self.assertIn("revision history", lowered)
            self.assertIn("do not include", lowered)


if __name__ == "__main__":
    unittest.main()
