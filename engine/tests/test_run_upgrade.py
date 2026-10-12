"""One-time legacy run upgrade and imported LLD workstream tests."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import run_upgrade  # noqa: E402
import state as statemod  # noqa: E402


WORKFLOW = """version: 1
name: current
inputs:
  slug: {type: string, required: true}
  feature: {type: string, default: "${inputs.slug}"}
  upgrade_manifest: {type: string, default: ""}
start: work
nodes:
  - id: work
    instruction: Do current work.
    outputs: [summary]
"""

CHILD_WORKFLOW = """version: 1
name: child
inputs:
  slug: {type: string, required: true}
  parent_slug: {type: string, required: true}
  repo: {type: string, required: true}
  repo_path: {type: string, required: true}
  feature: {type: string, default: "${inputs.parent_slug}"}
  imported_lld: {type: string, default: ""}
start: work
nodes:
  - id: work
    instruction: Review imported LLD.
    outputs: [summary]
"""


class RunUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-upgrade-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.workflow = self.write("workflows/main.yaml", WORKFLOW)
        self.child_workflow = self.write("workflows/repo-lld.yaml", CHILD_WORKFLOW)

    def write(self, relative, text):
        path = os.path.join(self.tmp, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_compatible_upgrade_is_one_time_and_preserves_cursor(self):
        data, _ = resolver.init_run("feature", "workflows/main.yaml", {}, self.tmp)
        data.pop("run_format")
        statemod.save("feature", data, self.tmp)
        plan = run_upgrade.inspect("feature", self.tmp, "workflows/main.yaml")
        self.assertEqual(plan["mode"], "compatible-rebase")
        self.assertEqual(plan["validations"], {})
        result = run_upgrade.apply("feature", self.tmp, "workflows/main.yaml")
        self.assertTrue(result["applied"])
        upgraded = statemod.load("feature", self.tmp)
        self.assertEqual(upgraded["run_format"], statemod.RUN_FORMAT_VERSION)
        self.assertEqual(upgraded["run"]["cursors"], ["work"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, result["backup_path"])))
        again = run_upgrade.apply("feature", self.tmp, "workflows/main.yaml")
        self.assertFalse(again["applied"])

    def test_legacy_steps_rebuild_fresh_state_and_preserve_backup(self):
        data, _ = resolver.init_run("legacy", "workflows/main.yaml", {"feature": "Auth"}, self.tmp)
        data.pop("run_format")
        data["steps"]["design/brainstorm_draft"] = {
            "status": "done", "attempts": 0, "visits": 1, "outputs": {},
        }
        statemod.save("legacy", data, self.tmp)
        result = run_upgrade.apply("legacy", self.tmp, "workflows/main.yaml")
        self.assertEqual(result["mode"], "legacy-rebuild")
        upgraded = statemod.load("legacy", self.tmp)
        self.assertNotIn("design/brainstorm_draft", upgraded["steps"])
        self.assertEqual(upgraded["inputs"]["feature"], "Auth")
        self.assertTrue(upgraded["inputs"]["upgrade_manifest"].endswith("run-upgrade.json"))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, result["backup_path"])))

    def test_current_repo_lld_approval_is_not_misclassified_as_legacy(self):
        data, _ = resolver.init_run("child", "workflows/repo-lld.yaml", {
            "parent_slug": "feature", "repo": "backend", "repo_path": "codebase/backend",
        }, self.tmp)
        data.pop("run_format")
        data["steps"] = {
            "lld_approval": {"status": "pending", "attempts": 0, "visits": 1, "outputs": {}},
        }
        data["run"]["cursors"] = ["lld_approval"]
        statemod.save("child", data, self.tmp)
        plan = run_upgrade.inspect("child", self.tmp, "workflows/repo-lld.yaml")
        self.assertEqual(plan["mode"], "compatible-rebase")

    def test_activate_imports_each_legacy_lld_as_unapproved_child(self):
        resolver.init_run("feature", "workflows/main.yaml", {}, self.tmp)
        repo = os.path.join(self.tmp, "codebase", "backend")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        hld = self.write(".maestro/runs/feature/hld.md", "# imported HLD\n")
        legacy_lld = self.write(".maestro/runs/feature/lld/backend.md", "# imported LLD\n")
        manifest_path = self.write(
            ".maestro/runs/feature/run-upgrade.json",
            json.dumps({
                "schema_version": 1,
                "slug": "feature",
                "feature": "Booking",
                "status": "applied",
                "mode": "legacy-rebuild",
                "baseline_valid": True,
                "selected_repos": ["backend"],
                "validations": {
                    "llds": {"backend": {
                        "path": os.path.relpath(legacy_lld, self.tmp), "valid": False,
                    }},
                },
            }),
        )
        result = run_upgrade.activate(
            manifest_path, self.tmp, "workflows/repo-lld.yaml",
        )
        self.assertTrue(result["has_workstreams"])
        child_slug = "feature--lld--backend"
        child = statemod.load(child_slug, self.tmp)
        self.assertEqual(child["run"]["status"], "running")
        self.assertFalse(any(gate.get("option") == "approve" for gate in child["gates"]))
        self.assertEqual(
            Path(self.tmp, child["inputs"]["imported_lld"]).read_text(encoding="utf-8"),
            "# imported LLD\n",
        )
        queue = json.loads(Path(
            self.tmp, ".maestro", "runs", "feature", "lld-repos.json",
        ).read_text(encoding="utf-8"))
        self.assertEqual(queue["workstreams"], [{"repo": "backend", "slug": child_slug}])
        self.assertEqual(queue["hld_sha256"], statemod.sha256_file(hld))


if __name__ == "__main__":
    unittest.main()
