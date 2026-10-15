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


class StageRelayoutTest(unittest.TestCase):
    """Format 2 -> 3: inline steps re-nest under the stage children that now declare them."""

    REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-relayout-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(os.path.join(self.REPO, "workflows"),
                        os.path.join(self.tmp, ".maestro", "workflows"))
        wrapper = os.path.join(self.tmp, ".maestro", "workflows", "wrapper.yaml")
        with open(wrapper, "w", encoding="utf-8") as fh:
            fh.write(
                "version: 1\nname: wrapper\nnodes:\n"
                "  - id: design\n    type: subworkflow\n"
                "    workflow: .maestro/workflows/design.yaml\n"
                "    inputs: {slug: \"${inputs.slug}\", feature: Demo}\n"
            )

    @staticmethod
    def done(**outputs):
        return {"status": "done", "attempts": 0, "visits": 1, "outputs": outputs}

    @staticmethod
    def pending():
        return {"status": "pending", "attempts": 0, "visits": 1, "outputs": {}}

    def legacy_layout(self, prefix):
        """A format-2 ledger paused at the HLD interview, PRD approved inline."""
        steps = {
            prefix + "upgrade_entry": self.done(state="normal"),
            prefix + "assert_requirement": self.done(state="have"),
            prefix + "project_context": self.done(project_context="ctx"),
            prefix + "prd_approval": self.done(choice="approve"),
            prefix + "check_codebase_map": self.done(stale=False),
            prefix + "prepare_hld_questions": self.pending(),
        }
        return steps, [prefix + "prepare_hld_questions"], [
            {"step": prefix + "prd_approval", "option": "approve", "at": "t"}]

    def upgrade(self, slug, workflow, steps, cursors, gates, frames=None):
        data, _ = resolver.init_run(slug, workflow, {"feature": "Demo"}, self.tmp)
        data["steps"] = steps
        data["run"]["cursors"] = cursors
        data["gates"] = gates
        data["frames"] = frames or {}
        data.pop("run_format")
        statemod.save(slug, data, self.tmp)
        self.assertEqual(run_upgrade.inspect(slug, self.tmp, workflow)["mode"], "compatible-rebase")
        self.assertTrue(run_upgrade.apply(slug, self.tmp, workflow)["applied"])
        return statemod.load(slug, self.tmp)

    def test_main_frame_steps_move_under_stage_children(self):
        state = self.upgrade("feature", ".maestro/workflows/design.yaml", *self.legacy_layout(""))
        self.assertEqual(state["run"]["cursors"], ["hld/prepare_hld_questions"])
        self.assertIn("upgrade_entry", state["steps"])
        self.assertEqual(state["steps"]["intake/project_context"]["outputs"],
                         {"project_context": "ctx"})
        self.assertEqual(state["steps"]["intake"]["outputs"]["project_context"], "ctx")
        self.assertEqual(state["steps"]["prd"]["status"], "done")
        self.assertEqual(state["frames"]["prd"]["inputs"]["project_context"], "ctx")
        self.assertEqual(state["steps"]["prd"]["outputs"]["prd_path"],
                         ".maestro/runs/feature/requirement/prd.md")
        self.assertEqual(state["steps"]["map"]["status"], "done")
        self.assertIn("map/check_codebase_map", state["steps"])
        self.assertEqual(state["steps"]["hld"]["status"], "running")
        self.assertEqual(state["frames"]["hld"]["inputs"]["slug"], "feature")
        self.assertNotIn("lld", state["frames"])
        self.assertNotIn("import", state["frames"])
        self.assertEqual(state["gates"][0]["step"], "prd/prd_approval")
        run = resolver.Run("feature", self.tmp)
        self.assertEqual(resolver.next_action(run)["step"], "hld/prepare_hld_questions")

    def test_nested_design_frame_and_contract_name_clash(self):
        design = ".maestro/workflows/design.yaml"
        frames = {"design": {
            "workflow": design, "sha256": "stale",
            "inputs": {"slug": "nested", "feature": "Demo"},
        }}
        steps, cursors, gates = self.legacy_layout("design/")
        running = {"status": "running", "attempts": 0, "visits": 1, "outputs": {},
                   "node_type": "subworkflow"}
        state = self.upgrade("nested", ".maestro/workflows/wrapper.yaml",
                             {"design": running, **steps}, cursors, gates, frames=frames)
        self.assertEqual(state["run"]["cursors"], ["design/hld/prepare_hld_questions"])
        self.assertEqual(state["steps"]["design/prd"]["status"], "done")
        self.assertIn("design/prd/prd_approval", state["steps"])
        self.assertIn("design/intake/assert_requirement", state["steps"])
        self.assertNotIn("design/prd_approval", state["steps"])
        # `contract` is both the old inline agent and the new stage node id.
        data = statemod.load("nested", self.tmp)
        relaid = resolver.Run("nested", self.tmp, state_data={
            **data, "steps": {"design/contract": self.done(contract_summary="old")},
            "frames": {"design": data["frames"]["design"]},
            "run": {"status": "running", "cursors": ["design/test_cases"]}, "gates": [],
        })
        run_upgrade.relayout_stages(relaid)
        self.assertEqual(relaid.state["steps"]["design/contract/contract"]["outputs"],
                         {"contract_summary": "old"})
        self.assertEqual(relaid.state["steps"]["design/contract"]["status"], "running")
        self.assertEqual(relaid.state["run"]["cursors"], ["design/contract/test_cases"])
        # Already in the stage layout: a second pass changes nothing.
        before = json.dumps(relaid.state, sort_keys=True)
        self.assertEqual(run_upgrade.relayout_stages(relaid), [])
        self.assertEqual(json.dumps(relaid.state, sort_keys=True), before)

    def test_sdlc_main_stages_keep_a_run_parked_at_release(self):
        """Old flat sdlc-main: review steps, subworkflow frames and parallel branches move too."""
        sub = lambda: {"status": "done", "attempts": 0, "visits": 1, "outputs": {},
                       "node_type": "subworkflow"}
        steps = {
            "design": {**sub(), "outputs": {"hld_path": "h.md", "contract_path": "c.yaml"}},
            "effective_design": self.done(),
            "arch_review": self.done(summary="sound", blocking=False),
            "arch_review_validate": self.done(blocking=False, revision_scope="none"),
            "contract_approval": self.done(choice="approve"),
            "implement": {**sub(), "node_type": "parallel"},
            "implement[slot_1]/claim": self.done(done=True),
            "finalize_implementation": self.done(manifest_path="m.json"),
            "qa": sub(),
            "qa/qa_run": self.done(passed=True),
            "review_pack": self.done(pack_path="pack.md"),
            "release_approval": self.pending(),
        }
        frames = {
            "design": {"workflow": ".maestro/workflows/design.yaml", "sha256": "stale",
                       "inputs": {"slug": "shipit"}},
            "qa": {"workflow": ".maestro/workflows/qa.yaml", "sha256": "stale",
                   "inputs": {"slug": "shipit"}},
        }
        gates = [{"step": "contract_approval", "option": "approve", "at": "t"}]
        state = self.upgrade("shipit", ".maestro/workflows/sdlc-main.yaml", steps,
                             ["release_approval"], gates, frames=frames)
        self.assertEqual(state["run"]["cursors"], ["delivery/release_approval"])
        self.assertIn("design", state["frames"])
        self.assertIn("delivery/qa", state["frames"])
        self.assertNotIn("qa", state["frames"])
        self.assertIn("delivery/qa/qa_run", state["steps"])
        self.assertIn("delivery/implement[slot_1]/claim", state["steps"])
        self.assertEqual(state["steps"]["review"]["status"], "done")
        self.assertEqual(state["steps"]["review"]["outputs"]["approval"], "approve")
        self.assertEqual(state["frames"]["review"]["inputs"]["hld_path"], "h.md")
        self.assertEqual(state["steps"]["delivery"]["status"], "running")
        self.assertEqual(state["gates"][0]["step"], "review/contract_approval")
        run = resolver.Run("shipit", self.tmp)
        action = resolver.next_action(run)
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "delivery/release_approval"))


if __name__ == "__main__":
    unittest.main()
