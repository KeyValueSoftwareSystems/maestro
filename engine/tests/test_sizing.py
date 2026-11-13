"""sizing: the design path follows the impact assessment's facts, never the repository count."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sizing  # noqa: E402


def prd(criteria=2, nfr="None beyond the existing service standards.", extra=""):
    acs = "\n".join(f"- AC-{i:02d}: Behaviour {i} is visible." for i in range(1, criteria + 1))
    return (f"# Tweak — PRD\n\n## Functional scope\n\nRename a label.{extra}\n\n"
            f"## Non-functional requirements\n\n{nfr}\n\n## Acceptance criteria\n\n{acs}\n")


class SizingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sizing-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo("web")

    def repo(self, name):
        path = os.path.join(self.root, "codebase", name)
        os.makedirs(path)
        subprocess.run(["git", "init", "-q", path], check=True)

    def size(self, text, path="auto"):
        with open(os.path.join(self.root, "prd.md"), "w") as fh:
            fh.write(text)
        out = io.StringIO()
        with redirect_stdout(out):
            sizing.main(["--root", self.root, "--prd", "prd.md", "--path", path])
        return json.loads(out.getvalue())

    def test_small_single_repo_change_is_light(self):
        result = self.size(prd())
        self.assertEqual(result["path"], "light")
        self.assertIn("Light path", result["summary"])

    def test_any_rule_failing_keeps_the_full_path(self):
        cases = [
            (prd(criteria=6), "6 acceptance criteria"),
            (prd(nfr="- p95 under 200 ms."), "non-functional targets"),
            (prd(extra=" Placement (to confirm)."), "(to confirm)"),
        ]
        for text, reason in cases:
            with self.subTest(reason=reason):
                result = self.size(text)
                self.assertEqual(result["path"], "full")
                self.assertIn(reason, result["reasons"])
        self.repo("api")
        self.assertIn("2 repositories", self.size(prd())["reasons"])

    def impact(self, repos, interfaces=False, infrastructure=False, size=None):
        path = os.path.join(self.root, f"impact-{len(os.listdir(self.root))}.json")
        with open(path, "w") as fh:
            json.dump({"schema_version": 1,
                       "repos": [{"name": name, "change": "changes"} for name in repos],
                       "interfaces_change": interfaces, "data_migration": False,
                       "infrastructure_change": infrastructure, **({"size": size} if size else {})}, fh)
        return path

    def size_with(self, impact_path, text=None):
        with open(os.path.join(self.root, "prd.md"), "w") as fh:
            fh.write(text or prd())
        out = io.StringIO()
        with redirect_stdout(out):
            sizing.main(["--root", self.root, "--prd", "prd.md", "--impact", impact_path])
        return json.loads(out.getvalue())

    def facts(self, repos, **facts):
        """A schema-3 assessment: facts only, no verdict."""
        doc = {"schema_version": 3,
               "repos": [{"name": name, "change": "changes"} for name in repos],
               "interface_change": "lockstep" if len(repos) > 1 else "none",
               "data_change": "none", "infrastructure_change": False,
               "compatibility_risk": False, "open_decisions": [], **facts}
        path = os.path.join(self.root, f"impact-{len(os.listdir(self.root))}.json")
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def test_a_lockstep_change_across_repositories_is_light(self):
        # the OTP case: backend, web and mobile change together; the wire format does not
        for name in ("backend", "mobile"):
            self.repo(name)
        rollout = {"kind": "rollout", "question": "Ship clients first?", "evidence": "AC-02"}
        result = self.size_with(self.facts(["backend", "web", "mobile"], compatibility_risk=True,
                                           open_decisions=[rollout]))
        self.assertEqual(result["path"], "light", result["reasons"])
        self.assertIn("backend, web and mobile change in step", result["explanation"])
        self.assertIn("say what ships first", result["explanation"])
        self.assertIn("Ship clients first?", result["explanation"])
        self.assertFalse(result["forced"])

    def test_each_design_fact_that_needs_an_architecture_forces_full(self):
        self.repo("api")
        placement = {"kind": "placement", "question": "Which service owns transfers?",
                     "evidence": "PRD"}
        cases = [
            ({"open_decisions": [placement]}, "open decision (placement): Which service owns transfers?"),
            ({"interface_change": "shape"}, "interface between repositories changes shape"),
            ({"data_change": "reshape"}, "stored data changes shape"),
            ({"infrastructure_change": True}, "infrastructure changes"),
        ]
        for facts, reason in cases:
            with self.subTest(reason=reason):
                result = self.size_with(self.facts(["web", "api"], **facts))
                self.assertEqual(result["path"], "full")
                self.assertIn(reason, result["reasons"])
                self.assertIn("needs architecture decisions", result["explanation"])
        self.assertEqual(self.size_with(self.facts(["web"], data_change="additive"))["path"], "light")
        result = self.size_with(self.facts(["web"]), prd(extra=" Placement (to confirm)."))
        self.assertIn("(to confirm)", result["reasons"])

    def test_criteria_and_quality_targets_do_not_decide_with_an_assessment(self):
        result = self.size_with(self.facts(["web"]), prd(criteria=9, nfr="- p95 under 200 ms."))
        self.assertEqual(result["path"], "light", result["reasons"])

    def test_an_hld_from_an_earlier_pass_keeps_the_full_path(self):
        hld = os.path.join(self.root, "hld.md")
        with open(hld, "w") as fh:
            fh.write("# HLD\n")
        with open(os.path.join(self.root, "prd.md"), "w") as fh:
            fh.write(prd())
        out = io.StringIO()
        with redirect_stdout(out):
            sizing.main(["--root", self.root, "--prd", "prd.md", "--impact", self.facts(["web"]),
                         "--hld", hld])
        result = json.loads(out.getvalue())
        self.assertEqual(result["path"], "full")
        self.assertIn("HLD exists from an earlier pass", result["reasons"])

    def test_an_older_format_assessment_still_sizes(self):
        self.repo("api")
        self.assertEqual(self.size_with(self.impact(["web"], size="minor"))["path"], "light")
        result = self.size_with(self.impact(["web"], size="major"))
        self.assertEqual(result["path"], "full")
        self.assertIn("classifies it as major", result["reasons"])
        result = self.size_with(self.impact(["web", "api"], interfaces=True, size="minor"))
        self.assertIn("interface between repositories changes shape", result["reasons"])

    def test_a_bad_item_list_does_not_discard_the_facts(self):
        # a domain with no doc page fails the agent's check, but sizing still reads the facts
        self.repo("api")
        os.makedirs(os.path.join(self.root, "docs", "technical"))
        with open(os.path.join(self.root, "docs", "technical", "notes.md"), "w") as fh:
            fh.write("---\ndoc: technical\ndomain: notes\nid_prefix: NT\n---\n")
        bad = [{"name": "billing", "reason": "r", "evidence": "e"}]
        result = self.size_with(self.facts(["web", "api"], schema_version=3, domains=bad))
        self.assertEqual(result["path"], "light", result["reasons"])
        self.assertNotIn("repositories in the workspace", result["reasons"])

    def test_choose_applies_the_persons_answer(self):
        cases = [("light", "accept", "light"), ("light", "", "light"), ("full", "", "full"),
                 ("light", "plan", "full"), ("full", "direct", "light"), ("bogus", "x", "full")]
        for sized, choice, want in cases:
            with self.subTest(sized=sized, choice=choice):
                self.assertEqual(sizing.choose(self.root, sized, choice)["path"], want)
        empty = tempfile.mkdtemp(prefix="sizing-empty-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        refused = sizing.choose(empty, "full", "direct")
        self.assertEqual(refused["path"], "full")
        self.assertIn("no repository yet", refused["summary"])
        out = io.StringIO()
        with redirect_stdout(out):
            sizing.main(["choose", "--root", self.root, "--sized", "full", "--choice", "direct"])
        self.assertEqual(json.loads(out.getvalue())["path"], "light")

    def test_without_a_valid_assessment_the_rules_decide(self):
        for path in (self.impact(["web"]), self.impact(["mobile"], size="minor"),
                     os.path.join(self.root, "missing.json")):
            with self.subTest(path=path):
                self.assertEqual(self.size_with(path)["path"], "light")  # one repository, 2 criteria
        self.repo("api")
        self.assertEqual(self.size_with(self.impact(["web"]))["path"], "full")

    def test_the_criteria_limit_is_a_config_value(self):
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\ndesign:\n  light_max_criteria: 8\n")
        self.assertEqual(self.size(prd(criteria=8))["path"], "light")
        result = self.size(prd(criteria=9))
        self.assertIn("9 acceptance criteria (light allows 8)", result["reasons"])

    def test_a_person_can_force_either_path(self):
        self.assertEqual(self.size(prd(criteria=9), path="light")["path"], "light")
        self.assertEqual(self.size(prd(), path="full")["path"], "full")


if __name__ == "__main__":
    unittest.main()
