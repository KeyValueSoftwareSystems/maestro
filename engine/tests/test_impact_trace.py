"""impact_trace: every impacted item must be dealt with in the HLD / LLDs (the fee-groups example)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import impact  # noqa: E402
import impact_trace  # noqa: E402

PAGES = {
    "fees": "---\ndoc: technical\ndomain: fees\nid_prefix: FC\n---\n## Invariants and consistency\n| ID | Invariant |\n| --- | --- |\n| FC-INV-001 | A student is charged a fee once per cycle. |\n",
    "payments": "---\ndoc: technical\ndomain: payments\nid_prefix: PL\n---\n## Invariants and consistency\n| ID | Invariant |\n| --- | --- |\n| PL-INV-001 | One active link per invoice. |\n"
                "\n## Change scenarios\n| ID | When changing | Also affects |\n| --- | --- | --- |\n| PL-CS-001 | Payment links | Reminders |\n",
    "whatsapp": "---\ndoc: technical\ndomain: whatsapp\nid_prefix: WA\n---\n## Invariants and consistency\n| ID | Invariant |\n| --- | --- |\n| WA-INV-001 | Never message an opted-out parent. |\n",
}
SIDE_EFFECTS = """version: 1
scenarios:
  - id: PL-CS-001
    domain: payments
    summary: Changing payment links
    rules: [PL-INV-001]
    repo: backend
    when_changing: ["internal/links/create.go"]
    also_impacts:
      queues: [payment.succeeded]
"""


def item(name, reason="the feature uses it", key="name", **extra):
    return {key: name, "reason": reason, "evidence": "docs/codebase-map.md", **extra}


FEE_GROUPS = {
    "schema_version": 2,
    "repos": [{"name": "backend", "change": "fee groups and scheduled fee runs"}],
    "interfaces_change": False, "data_migration": True, "infrastructure_change": False,
    "size": "major", "summary": "fee groups",
    "domains": [item("fees")],
    "tables": [item("fee_groups"), item("fee_group_members")],
    "jobs": [item("fee-schedule-run")],
    "queues": [item("whatsapp.send", "reused for fee reminders", consumers=["notifier"]),
               item("payment.succeeded", "reused to settle fees")],
    "endpoints": [item("POST /v1/fee-groups", consumers=["web: FeeGroupsScreen"])],
    "rules": [item("FC-INV-001", key="id"), item("PL-INV-001", key="id"), item("WA-INV-001", key="id")],
}
HLD = """# HLD
New tables `fee_groups` and `fee_group_members` in the fees domain.
The `fee-schedule-run` job charges each group (FC-INV-001) and posts POST /v1/fee-groups results.
It reuses `whatsapp.send` for reminders, honouring WA-INV-001, and settles on `payment.succeeded`.
PL-INV-001: no change needed, because links are created exactly as today.
"""
NEEDLES = ["fee_groups", "fee-schedule-run", "whatsapp.send", "payment.succeeded",
           "FC-INV-001", "PL-INV-001", "WA-INV-001"]


class ImpactTraceTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="impact-trace-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        subprocess.run(["git", "init", "-q", os.path.join(self.root, "codebase", "backend")], check=True)
        for name, text in PAGES.items():
            self.write(f"docs/technical/{name}.md", text)
        self.write("docs/impact/side-effects.yaml", SIDE_EFFECTS)
        self.impact = self.write("impact.json", json.dumps(FEE_GROUPS))

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def check(self, text, stage="hld", match=False):
        hld = self.write("hld.md", text)
        rows, missing, issues, added, skipped = impact_trace.trace(self.root, self.impact, [hld], stage, match)
        return rows, missing, issues, added

    def test_fee_groups_assessment_is_valid_and_lists_every_item(self):
        result = impact.validate(self.root, self.impact)
        self.assertTrue(result["valid"], result["issues_summary"])
        self.assertEqual(result["item_count"], 10)

    def test_full_hld_covers_every_item(self):
        rows, missing, issues, _ = self.check(HLD)
        self.assertEqual((missing, issues), ([], []))
        self.assertEqual(len(rows), 10)

    def test_deleting_any_item_from_the_hld_fails_naming_it(self):
        for needle in NEEDLES:
            with self.subTest(needle=needle):
                text = "\n".join(line for line in HLD.splitlines() if needle not in line)
                _rows, missing, issues, _ = self.check(text)
                self.assertIn(needle, missing)
                self.assertTrue(any(f"does not deal with" in i and needle in i for i in issues), issues)

    def test_no_change_needed_needs_a_reason(self):
        _rows, _missing, issues, _ = self.check(HLD.replace(", because links are created exactly as today", ""))
        self.assertTrue(any("PL-INV-001 needs no change but not why" in i for i in issues), issues)

    def test_match_adds_the_scenario_a_planned_file_triggers(self):
        lld = HLD + "\nChange internal/links/create.go to tag fee invoices.\n"
        _rows, missing, _issues, added = self.check(lld, stage="lld", match=True)
        self.assertEqual(added, ["PL-CS-001"])
        self.assertIn("PL-CS-001", missing)  # the scenario itself must now be dealt with
        with open(self.impact) as fh:
            self.assertIn("PL-CS-001", [s["id"] for s in json.load(fh)["scenarios"]])

    def test_cli_writes_report_and_skips_without_assessment(self):
        hld = self.write("hld.md", HLD)
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "impact_trace.py"),
                              "check", "--root", self.root, "--impact", self.impact, "--docs", hld,
                              "--out", os.path.join(self.root, "impact-trace.md")],
                             capture_output=True, text=True, check=True)
        result = json.loads(out.stdout)
        self.assertTrue(result["valid"], result)
        with open(os.path.join(self.root, "impact-trace.md")) as fh:
            self.assertIn("`fee-schedule-run`", fh.read())
        rows, missing, issues, _added, skipped = impact_trace.trace(
            self.root, os.path.join(self.root, "missing.json"), [hld], "hld")
        self.assertTrue(skipped)


if __name__ == "__main__":
    unittest.main()
