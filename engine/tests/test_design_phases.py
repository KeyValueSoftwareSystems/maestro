"""design.yaml composes small stage children (design-import/-intake/-prd/-map/-hld/-lld/-contract).
Scoped architecture-review revisions must land on exactly the node the former inline routing chose."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402

ENTRY_STEPS = {"upgrade_entry", "import_entry", "lld_entry", "contract_entry"}


class DesignPhaseEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-phases-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(os.path.join(REPO, "workflows"),
                        os.path.join(self.tmp, ".maestro", "workflows"))
        shutil.copytree(os.path.join(REPO, "engine"), os.path.join(self.tmp, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))

    def first_work_step(self, workflow, inputs):
        """Run only the route-only entry scripts; return the first step that does real work."""
        slug = "demo"
        with statemod.locked(slug, self.tmp):
            resolver.init_run(slug, workflow, inputs, self.tmp, force=True)
        for _ in range(6):
            run = resolver.Run(slug, self.tmp)
            action = resolver.next_action(run)
            step = action.get("step") or ""
            if action["action"] != "run_script" or step.rsplit("/", 1)[-1] not in ENTRY_STEPS:
                return step
            proc = subprocess.run(action["argv"], cwd=self.tmp, capture_output=True,
                                  text=True, timeout=30)
            resolver.complete_step(run, step, exit_code=proc.returncode, stdout=proc.stdout)
            statemod.save(slug, run.state, self.tmp)
        self.fail("entry routing did not settle")

    def test_scoped_revisions_enter_the_earliest_affected_phase(self):
        design = ".maestro/workflows/design.yaml"
        cases = [
            ({}, "intake/assert_requirement"),
            ({"revision_scope": "product"}, "intake/assert_requirement"),
            ({"revision_scope": "cross-cutting"}, "intake/assert_requirement"),
            ({"revision_scope": "hld"}, "hld/prepare_hld_questions"),
            ({"revision_scope": "lld"}, "lld/lld_review_reopen"),
            ({"revision_mode": "lld_only", "revision_scope": "hld"},
             "lld/record_arch_lld_correction"),
            ({"revision_scope": "contract"}, "contract/corrections_context"),
            ({"revision_scope": "verification"}, "contract/test_cases"),
        ]
        for inputs, expected in cases:
            with self.subTest(inputs=inputs):
                self.assertEqual(
                    self.first_work_step(design, {"feature": "Demo", **inputs}), expected)

    def test_phase_children_default_to_their_normal_start(self):
        cases = [
            (".maestro/workflows/design-intake.yaml", {}, "assert_requirement"),
            (".maestro/workflows/design-map.yaml", {}, "check_codebase_map"),
            (".maestro/workflows/design-hld.yaml", {}, "prepare_hld_questions"),
            (".maestro/workflows/design-import.yaml", {"upgrade_manifest": "m.json", "state": "ready"},
             "upgrade_baseline_approval"),
            (".maestro/workflows/design-import.yaml", {"upgrade_manifest": "m.json", "state": "invalid"},
             "upgrade_baseline_invalid"),
            (".maestro/workflows/design-lld.yaml", {}, "lld_scope_serve"),
            (".maestro/workflows/design-lld.yaml", {"imported_workstreams": "true"},
             "lld_workstreams_check"),
            (".maestro/workflows/design-contract.yaml", {}, "corrections_context"),
        ]
        for workflow, inputs, expected in cases:
            with self.subTest(workflow=workflow, inputs=inputs):
                self.assertEqual(self.first_work_step(workflow, inputs), expected)


if __name__ == "__main__":
    unittest.main()
