"""Fixture-driven validator tests: every invalid-* must fail with its rule id,
every valid-* must pass clean, every warn-* must pass with a warning."""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import validate  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURES = os.path.join(ROOT, "testdata", "workflows")

# fixture name -> rule id that must appear among its errors
EXPECTED_RULE = {
    "invalid-unknown-key": "unknown-key",
    "invalid-missing-default-route": "no-default-route",
    "invalid-bad-placeholder": "bad-placeholder",
    "invalid-undeclared-input": "undeclared-input",
    "invalid-gate-route-missing": "missing-route-target",
    "invalid-dup-id": "dup-id",
    "invalid-branch-nested-parallel": "branch-bad-type",
    "invalid-subworkflow-missing": "subworkflow-missing-file",
}


class FixtureTest(unittest.TestCase):
    def issues_for(self, name):
        return validate.validate_file(
            os.path.join("testdata", "workflows", name + ".yaml"), root=ROOT
        )

    def test_valid_fixtures_pass_clean(self):
        for path in glob.glob(os.path.join(FIXTURES, "valid-*.yaml")):
            name = os.path.basename(path)[:-5]
            issues = self.issues_for(name)
            self.assertEqual([str(i) for i in issues], [], name)

    def test_invalid_fixtures_fail_with_expected_rule(self):
        found = 0
        for path in glob.glob(os.path.join(FIXTURES, "invalid-*.yaml")):
            name = os.path.basename(path)[:-5]
            found += 1
            issues = self.issues_for(name)
            errors = [i for i in issues if i.level == "error"]
            self.assertTrue(errors, f"{name}: expected errors, got none")
            expected = EXPECTED_RULE.get(name)
            self.assertIsNotNone(expected, f"{name}: add it to EXPECTED_RULE")
            self.assertIn(expected, {i.code for i in errors},
                          f"{name}: wanted rule {expected}, got {[str(i) for i in errors]}")
        self.assertEqual(found, len(EXPECTED_RULE), "fixture / table drift")

    def test_warn_fixtures_warn_but_pass(self):
        for path in glob.glob(os.path.join(FIXTURES, "warn-*.yaml")):
            name = os.path.basename(path)[:-5]
            issues = self.issues_for(name)
            self.assertFalse([i for i in issues if i.level == "error"], name)
            self.assertTrue([i for i in issues if i.level == "warning"], name)

    def test_rule_ids_registered(self):
        # every rule id used in code exists in the declared catalog (UI parity anchor)
        for rule in EXPECTED_RULE.values():
            self.assertIn(rule, validate.RULE_IDS)

    def test_subworkflow_cycle_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "workflows"))
            a = ("version: 1\nname: a\nstart: s\nnodes:\n  - id: s\n    type: subworkflow\n"
                 "    workflow: workflows/b.yaml\n    next: end\n")
            b = ("version: 1\nname: b\nstart: s\nnodes:\n  - id: s\n    type: subworkflow\n"
                 "    workflow: workflows/a.yaml\n    next: end\n")
            open(os.path.join(tmp, "workflows", "a.yaml"), "w").write(a)
            open(os.path.join(tmp, "workflows", "b.yaml"), "w").write(b)
            issues = validate.validate_file("workflows/a.yaml", root=tmp)
            self.assertIn("subworkflow-cycle", {i.code for i in issues})


class MemoryPlaceholderTest(unittest.TestCase):
    def _doc(self, ref):
        return {
            "version": 1, "name": "mem", "start": "work",
            "nodes": [{
                "id": "work", "type": "agent", "instruction": "go",
                "inputs": {"lessons": ref}, "outputs": ["note"],
                "artifact": ".maestro/x/work.md", "next": "end",
            }],
        }

    def test_memory_ref_ok(self):
        issues = validate.validate_doc(self._doc("${memory.knowledge.backend-review}"))
        self.assertFalse([i for i in issues if i.code == "bad-placeholder"],
                         [str(i) for i in issues])

    def test_memory_nested_ref_ok(self):
        issues = validate.validate_doc(self._doc("${memory.knowledge.${inputs.slug}-review}"))
        self.assertFalse([i for i in issues if i.code == "bad-placeholder"],
                         [str(i) for i in issues])

    def test_memory_ref_malformed(self):
        issues = validate.validate_doc(self._doc("${memory.oops}"))
        self.assertTrue(any(i.code == "bad-placeholder" for i in issues))


if __name__ == "__main__":
    unittest.main()
