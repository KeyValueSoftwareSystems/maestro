"""sizing: a small single-repository change with no non-functional targets takes the light path."""
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

    def test_a_person_can_force_either_path(self):
        self.assertEqual(self.size(prd(criteria=9), path="light")["path"], "light")
        self.assertEqual(self.size(prd(), path="full")["path"], "full")


if __name__ == "__main__":
    unittest.main()
