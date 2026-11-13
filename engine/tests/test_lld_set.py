"""lld_set: one LLD per selected repo, validated together, approved with hashes, checked for staleness."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lld_set  # noqa: E402

LLD = """# {repo} — LLD

**Parent feature:** `demo`
**Repository:** `{repo}`
**Status:** Ready for review

## Change summary

- Deliver repository behavior one.
- Deliver repository behavior two.
- Deliver repository behavior three.
- Deliver repository behavior four.

## Existing seam

Requests enter through `src/routes.py` and follow the existing service boundary.

## Proposed changes

Extend the current service with the approved behavior. Keep state inside the data layer.

## Data model and migrations

No repository-owned persistence change.

## API and client contract

No externally consumed interface change.

## State and flows

The route validates input, invokes the service, and returns the result.

## Failure and operational behavior

Validation failures use the existing client error. Storage failures preserve prior state.

## Implementation sequence

1. Extend the service boundary and cover its behavior.
2. Connect the route and add an integration test.

## Verification

Service tests cover validation and state changes. Route tests cover the result.
"""


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = lld_set.main(list(argv))
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None), err.getvalue()


class LldSetTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lld-set-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for repo in ("api", "web"):
            path = os.path.join(self.root, "codebase", repo)
            os.makedirs(path)
            subprocess.run(["git", "init", "-q", path], check=True)
        self.run_dir = os.path.join(self.root, ".maestro", "runs", "demo")
        os.makedirs(self.run_dir)
        self.write("design/hld.md", "# Demo — HLD\n")

    def write(self, rel, text):
        path = os.path.join(self.run_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def write_llds(self, repos=("api", "web")):
        for repo in repos:
            self.write(f"design/lld/{repo}.md", LLD.format(repo=repo))

    def test_pick_rejects_unknown_repo_and_records_paths(self):
        code, _, err = run("init", "--root", self.root, "--slug", "demo", "--choice", "pick",
                           "--repos-text", "api, mobile")
        self.assertEqual(code, 1)
        self.assertIn("mobile", err)
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "pick",
                           "--repos-text", "WEB")
        self.assertEqual(code, 0)
        self.assertEqual(out["selected_csv"], "web")
        self.assertEqual(out["lld_paths_csv"], ".maestro/runs/demo/design/lld/web.md")

    def test_validate_needs_every_selected_lld(self):
        run("init", "--root", self.root, "--slug", "demo")
        self.write_llds(("api",))
        _, out, _ = run("validate", "--root", self.root, "--slug", "demo")
        self.assertFalse(out["valid"])
        self.assertIn("web: LLD missing", out["issues_summary"])
        self.write_llds()
        _, out, _ = run("validate", "--root", self.root, "--slug", "demo")
        self.assertTrue(out["valid"], out)

    def test_validate_checks_each_lld_names_its_repository(self):
        run("init", "--root", self.root, "--slug", "demo")
        self.write_llds()
        self.write("design/lld/web.md", LLD.format(repo="api"))
        _, out, _ = run("validate", "--root", self.root, "--slug", "demo")
        self.assertFalse(out["valid"])
        self.assertIn("web:", out["issues_summary"])

    def test_approval_goes_stale_when_hld_contract_or_lld_changes(self):
        run("init", "--root", self.root, "--slug", "demo")
        self.write_llds()
        self.write("design/openapi.yaml", "openapi: 3.1.0\n")
        code, _, _ = run("approve", "--root", self.root, "--slug", "demo")
        self.assertEqual(code, 0)
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertFalse(out["stale"], out)

        self.write("design/openapi.yaml", "openapi: 3.1.0\n# frontend needs updated_at\n")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertTrue(out["stale"])
        self.assertIn("contract changed", out["reasons"])

        run("approve", "--root", self.root, "--slug", "demo")
        self.write("design/lld/web.md", LLD.format(repo="web") + "\nEdited after approval.\n")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertIn("web: LLD changed", out["reasons"])

        run("approve", "--root", self.root, "--slug", "demo")
        self.write("design/hld.md", "# Demo — HLD\n\nChanged.\n")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertIn("HLD changed", out["reasons"])

    def test_no_approval_or_changed_scope_is_stale(self):
        run("init", "--root", self.root, "--slug", "demo")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertTrue(out["stale"])
        self.assertIn("no approval record", out["reasons"])
        self.write_llds()
        run("approve", "--root", self.root, "--slug", "demo")
        run("init", "--root", self.root, "--slug", "demo", "--choice", "pick", "--repos-text", "api")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertIn("selected repositories changed", out["reasons"])

    def test_light_path_approves_without_an_hld_and_tracks_the_prd(self):
        os.remove(os.path.join(self.run_dir, "design", "hld.md"))
        self.write("requirement/prd.md", "# Demo — PRD\n")
        run("init", "--root", self.root, "--slug", "demo")
        self.write_llds()
        code, _, err = run("approve", "--root", self.root, "--slug", "demo")
        self.assertEqual(code, 1)
        self.assertIn("only the light path", err)
        code, _, _ = run("approve", "--root", self.root, "--slug", "demo", "--light", "light")
        self.assertEqual(code, 0)
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertFalse(out["stale"], out)
        self.write("requirement/prd.md", "# Demo — PRD\n\nChanged scope.\n")
        _, out, _ = run("verify", "--root", self.root, "--slug", "demo")
        self.assertIn("the PRD changed after LLD approval", out["reasons"])

    def test_infrastructure_owners_cannot_be_dropped_from_scope(self):
        code, _, err = run("init", "--root", self.root, "--slug", "demo", "--choice", "pick",
                           "--repos-text", "web", "--require", "api")
        self.assertEqual(code, 1)
        self.assertIn("api must be in scope", err)
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "pick",
                           "--repos-text", "web, api", "--require", "api")
        self.assertEqual((code, out["selected_csv"]), (0, "web,api"))

    def test_impact_scope_takes_the_assessed_repos_plus_infrastructure_owners(self):
        self.write("design/impact.json", json.dumps({
            "schema_version": 1, "repos": [{"name": "web", "change": "new screen"}],
            "interfaces_change": False, "data_migration": False, "infrastructure_change": False,
            "size": "minor"}))
        impact = os.path.join(self.run_dir, "design", "impact.json")
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "impact",
                           "--impact", impact)
        self.assertEqual((code, out["selected_csv"]), (0, "web"))
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "impact",
                           "--impact", impact, "--require", "api")
        self.assertEqual((code, out["selected_csv"]), (0, "web,api"))
        # no usable assessment (greenfield, light path forced, invalid): every repository
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "impact",
                           "--impact", os.path.join(self.run_dir, "missing.json"))
        self.assertEqual((code, out["selected_csv"]), (0, "api,web"))

    def test_impact_scope_survives_a_wrong_item_list(self):
        # a domain with no doc page fails the agent's check, not the repositories it named
        os.makedirs(os.path.join(self.root, "docs", "technical"), exist_ok=True)
        with open(os.path.join(self.root, "docs", "technical", "notes.md"), "w") as fh:
            fh.write("---\ndoc: technical\ndomain: notes\nid_prefix: NT\n---\n")
        self.write("impact.json", json.dumps({
            "schema_version": 3, "repos": [{"name": "web", "change": "new screen"}],
            "interface_change": "none", "data_change": "none", "infrastructure_change": False,
            "compatibility_risk": False, "open_decisions": [],
            "domains": [{"name": "billing", "reason": "r", "evidence": "e"}]}))
        code, out, _ = run("init", "--root", self.root, "--slug", "demo", "--choice", "impact",
                           "--impact", os.path.join(self.run_dir, "impact.json"))
        self.assertEqual((code, out["selected_csv"]), (0, "web"))

    def test_approve_refuses_a_missing_lld(self):
        run("init", "--root", self.root, "--slug", "demo")
        self.write_llds(("api",))
        code, _, err = run("approve", "--root", self.root, "--slug", "demo")
        self.assertEqual(code, 1)
        self.assertIn("web", err)


if __name__ == "__main__":
    unittest.main()
