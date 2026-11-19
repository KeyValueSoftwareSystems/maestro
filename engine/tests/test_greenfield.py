"""Greenfield: an empty workspace gets the repositories its plan marks new — created, scaffolded,
configured and proven to build and test before the plan is approved."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import codebase_scan  # noqa: E402
import greenfield  # noqa: E402
import project_config  # noqa: E402

PLAN = """# Notes — plan
Type: major · Run: demo · PRD: .maestro/runs/demo/requirement/prd.md · Status: active

## Summary
A new notes product.

## Repositories
| repo | role in this change | new? |
|---|---|---|
| notes-api | stores and serves notes (python) | yes |
| notes-web | the notes UI (react) | yes |
"""


def git_env():
    return {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e"}


class GreenfieldTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="greenfield-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = os.path.join(self.root, ".maestro", "runs", "demo")
        os.makedirs(self.run_dir)
        plan = os.path.join(self.root, "docs", "plans", "active", "demo.md")
        os.makedirs(os.path.dirname(plan))
        with open(plan, "w") as fh:
            fh.write(PLAN)

    def cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = greenfield.main(list(argv))
        return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()

    def test_check_create_and_configure(self):
        self.assertTrue(self.cmd("check", "--root", self.root)[1]["greenfield"])
        code, out, _ = self.cmd("create", "--root", self.root, "--slug", "demo")
        self.assertEqual((code, out["created_csv"]), (0, "notes-api,notes-web"))
        self.assertEqual(self.cmd("check", "--root", self.root)[1]["repo_count"], 2)
        # created again: nothing is recreated
        self.assertEqual(self.cmd("create", "--root", self.root, "--slug", "demo")[1]["created_csv"], "")
        api = os.path.join(self.root, "codebase", "notes-api")
        with open(os.path.join(api, "README.md"), "w") as fh:
            fh.write("# notes-api\n")
        map_path = codebase_scan.map_path(self.root, "notes-api")
        os.makedirs(os.path.dirname(map_path))
        with open(map_path, "w") as fh:
            fh.write("# notes-api map\n")
        subprocess.run(["git", "-C", api, "add", "-A"], check=True)
        subprocess.run(["git", "-C", api, "commit", "-qm", "scaffold"], check=True, env=git_env())
        with open(project_config.config_path(self.root), "w") as fh:
            fh.write("version: 1\nrepos:\n  notes-web: {stack: react, commands: {build: \"true\", "
                     "test: \"true\"}}\n")
        scaffold = os.path.join(self.run_dir, "scaffold.json")
        with open(scaffold, "w") as fh:
            json.dump({"repos": {
                "notes-api": {"stack": "python", "commands": {"build": "test -f README.md",
                                                              "test": "true", "lint": "true"}},
                "notes-web": {"stack": "react", "commands": {"build": "false", "test": "false"}}}}, fh)
        code, out, _ = self.cmd("configure", "--root", self.root, "--scaffold", scaffold)
        # notes-web keeps the entry a person already wrote (which passes); notes-api is added
        self.assertTrue(out["valid"], out)
        self.assertEqual(out["added_csv"], "notes-api")
        config = project_config.load(self.root)
        self.assertEqual(config["repos"]["notes-api"]["commands"]["build"], "test -f README.md")
        self.assertEqual(config["repos"]["notes-web"]["commands"]["build"], "true")
        self.assertTrue(os.path.exists(project_config.config_path(self.root) + ".bak"))
        # the map is stamped; the repository is left clean
        self.assertEqual(codebase_scan.read_marker(map_path), codebase_scan._head(api))
        status = subprocess.run(["git", "-C", api, "status", "--porcelain"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(status.stdout, "")

    def test_configure_refuses_missing_or_failing_commands(self):
        self.cmd("create", "--root", self.root, "--slug", "demo")
        scaffold = os.path.join(self.run_dir, "scaffold.json")
        with open(scaffold, "w") as fh:
            json.dump({"repos": {"notes-api": {"commands": {"build": "true"}}}}, fh)
        out = self.cmd("configure", "--root", self.root, "--scaffold", scaffold)[1]
        self.assertFalse(out["valid"])
        self.assertIn("notes-api: no test command", out["summary"])
        with open(scaffold, "w") as fh:
            json.dump({"repos": {"notes-api": {"commands": {"build": "true",
                                                            "test": "echo 1 failed; exit 1"}}}}, fh)
        out = self.cmd("configure", "--root", self.root, "--scaffold", scaffold)[1]
        self.assertEqual((out["valid"], out["failed_csv"]), (False, "notes-api"))
        self.assertIn("test failed", out["summary"])

    def test_create_writes_the_planned_list_and_refuses_a_plan_without_new_repos(self):
        code, out, _ = self.cmd("create", "--root", self.root, "--slug", "demo")
        self.assertEqual(code, 0)
        with open(os.path.join(self.root, out["plan_path"])) as fh:
            self.assertEqual([r["name"] for r in json.load(fh)["repos"]], ["notes-api", "notes-web"])
        self.assertEqual(out["plan_path"], ".maestro/runs/demo/.engine/greenfield-plan.json")
        with open(os.path.join(self.root, "docs", "plans", "active", "demo.md"), "w") as fh:
            fh.write(PLAN.replace("| yes |", "| no |"))
        code, _out, err = self.cmd("create", "--root", self.root, "--slug", "demo")
        self.assertEqual(code, 1)
        self.assertIn("marks no repository new", err)


if __name__ == "__main__":
    unittest.main()
