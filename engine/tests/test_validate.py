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
    "invalid-script-timeout-string": "bad-type",
    "invalid-bad-on-branch-fail": "bad-type",
    "invalid-next-list": "bad-type",
    "invalid-route-when-bool": "bad-type",
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


class TitleTest(unittest.TestCase):
    def _doc(self, title):
        return {"version": 1, "name": "t", "title": title,
                "nodes": [{"id": "work", "instruction": "go", "next": "end"}]}

    def test_title_accepted(self):
        self.assertEqual([str(i) for i in validate.validate_doc(self._doc("Build a feature"))], [])

    def test_title_must_be_a_string(self):
        issues = validate.validate_doc(self._doc(["no"]))
        self.assertTrue(any(i.code == "bad-type" for i in issues), [str(i) for i in issues])


class InputEnumTest(unittest.TestCase):
    def _doc(self, spec):
        return {"version": 1, "name": "t", "inputs": {"path": spec},
                "nodes": [{"id": "work", "instruction": "go", "next": "end"}]}

    def test_enum_accepted_and_default_checked(self):
        self.assertEqual(validate.validate_doc(self._doc(
            {"type": "string", "required": True, "enum": ["major", "minor"]})), [])
        issues = validate.validate_doc(self._doc({"type": "string", "default": "auto",
                                                  "enum": ["major", "minor"]}))
        self.assertTrue(any("not one of its enum values" in i.msg for i in issues),
                        [str(i) for i in issues])
        issues = validate.validate_doc(self._doc({"type": "string", "enum": []}))
        self.assertTrue(any(i.code == "bad-type" for i in issues), [str(i) for i in issues])


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


class BranchScopeTest(unittest.TestCase):
    def test_branch_steps_resolve_against_their_own_branch(self):
        doc = {"version": 1, "nodes": [{"id": "fan", "type": "parallel", "branches": [
            {"id": "a", "start": "claim", "steps": [
                {"id": "claim", "type": "script", "run": ["true"], "next": "work"},
                {"id": "work", "instruction": "Use ${steps.claim.outputs.repo}.", "next": "end"},
            ]}], "next": "end"}]}
        issues = validate.validate_doc(doc)
        self.assertEqual([str(i) for i in issues if i.code == "bad-placeholder"], [])


class AgentCheckValidationTest(unittest.TestCase):
    def _codes(self, check):
        doc = {"version": 1, "nodes": [
            {"id": "write", "instruction": "Write.", "check": check, "next": "end"}]}
        return [i.code for i in validate.validate_doc(doc) if i.level == "error"]

    def test_valid_check(self):
        self.assertEqual(self._codes({"run": ["python3", "x.py"], "attempts": 2, "timeout": 30}), [])

    def test_check_needs_run(self):
        self.assertIn("missing-key", self._codes({"attempts": 2}))
        self.assertIn("missing-key", self._codes({"run": []}))

    def test_check_rejects_unknown_keys_and_bad_numbers(self):
        self.assertIn("unknown-key", self._codes({"run": ["x"], "pass": "valid"}))
        self.assertIn("bad-type", self._codes({"run": ["x"], "attempts": 0}))
        self.assertIn("bad-type", self._codes("python3 x.py"))


class InterviewValidationTest(unittest.TestCase):
    def _doc(self, sections=None, artifact=".maestro/runs/x/context.json",
             questions_artifact=None, batch_size=None, presentation=None):
        node = {
            "id": "ask", "type": "interview", "skill": "prd-interview",
            "artifact": artifact, "next": "end",
        }
        if sections is not None:
            node["sections"] = sections
        if questions_artifact is not None:
            node["questions_artifact"] = questions_artifact
        if batch_size is not None:
            node["batch_size"] = batch_size
        if presentation is not None:
            node["presentation"] = presentation
        return {
            "version": 1, "name": "interview", "start": "ask",
            "nodes": [node],
        }

    def test_valid_interview(self):
        issues = validate.validate_doc(self._doc([
            {"id": "users", "title": "Users", "proposal": "Admins"},
            {"id": "scope", "title": "Scope", "prompt": "What is in scope?"},
        ]))
        self.assertFalse([i for i in issues if i.level == "error"], [str(i) for i in issues])

    def test_interview_requires_sections_and_artifact(self):
        issues = validate.validate_doc(self._doc([], artifact=""))
        codes = {i.code for i in issues}
        self.assertIn("interview-no-sections", codes)
        self.assertIn("interview-no-source", codes)
        self.assertIn("artifact-not-string", codes)

    def test_interview_section_ids_are_unique(self):
        issues = validate.validate_doc(self._doc([
            {"id": "users", "title": "Users"}, {"id": "users", "title": "Again"},
        ]))
        self.assertIn("interview-dup-sections", {i.code for i in issues})

    def test_valid_dynamic_interview(self):
        issues = validate.validate_doc(self._doc(
            questions_artifact=".maestro/runs/x/questions.json", batch_size=12,
            presentation="popup",
        ))
        self.assertFalse([i for i in issues if i.level == "error"], [str(i) for i in issues])

    def test_interview_rejects_two_question_sources(self):
        issues = validate.validate_doc(self._doc(
            [{"id": "users", "title": "Users"}],
            questions_artifact=".maestro/runs/x/questions.json",
        ))
        self.assertIn("interview-multiple-sources", {i.code for i in issues})

    def test_interview_batch_size_must_be_positive(self):
        issues = validate.validate_doc(self._doc(
            questions_artifact=".maestro/runs/x/questions.json", batch_size=0,
        ))
        self.assertIn("bad-batch-size", {i.code for i in issues})

    def test_interview_presentation_is_validated(self):
        issues = validate.validate_doc(self._doc(
            questions_artifact=".maestro/runs/x/questions.json", presentation="modal",
        ))
        self.assertIn("bad-type", {i.code for i in issues})


class InterviewDiscussTest(unittest.TestCase):
    def codes(self, discuss):
        node = {"id": "ask", "type": "interview", "questions_artifact": "q.json",
                "artifact": "d.json", "discuss": discuss}
        return {issue.code for issue in validate.validate_doc({"nodes": [node]})
                if issue.level == "error"}

    def test_discuss_block(self):
        self.assertEqual(self.codes({"inputs": {"map": "docs/map.md"}, "model": "sonnet"}), set())
        self.assertIn("unknown-key", self.codes({"evidence": {}}))
        self.assertIn("bad-type", self.codes({"inputs": ["docs/map.md"]}))
        self.assertIn("bad-type", self.codes("docs/map.md"))


class FieldTypeTest(unittest.TestCase):
    """Every node field the JSON schema types or enumerates is enforced, with the node id."""

    def errors(self, node, **doc):
        issues = validate.validate_doc({"version": 1, "nodes": [node], **doc})
        return [i for i in issues if i.level == "error"]

    def assert_bad(self, node, key, **doc):
        errs = self.errors(node, **doc)
        self.assertTrue(any(i.code == "bad-type" and key in i.msg and "#" not in i.where
                            and i.where == node["id"] for i in errs),
                        [str(i) for i in errs])

    def test_wrong_scalar_types_and_enums(self):
        script = {"id": "s", "type": "script", "run": ["x"]}
        agent = {"id": "a", "instruction": "go"}
        gate = {"id": "g", "type": "gate", "prompt": "p",
                "options": [{"id": "o", "label": "O", "to": "end"}]}
        fan = {"id": "f", "type": "parallel", "branches": [
            {"id": "b1", "start": "x", "steps": [{"id": "x", "instruction": "i"}]},
            {"id": "b2", "start": "y", "steps": [{"id": "y", "instruction": "i"}]}]}
        cases = [
            (script, "timeout", "30s"), (script, "timeout", 0), (script, "timeout", True),
            (script, "label", 3), (script, "ui", []),
            (agent, "timeout", "1h"), (agent, "retries", -1), (agent, "retries", "2"),
            (agent, "execution", "lad"), (agent, "brief", "loud"), (agent, "fresh", "yes"),
            (agent, "isolate", "container"), (agent, "outputs", "x"), (agent, "outputs", [1]),
            (agent, "inputs", ["a"]), (agent, "inputs", {"k": [1]}), (agent, "model", 4),
            (agent, "skill", []), (agent, "agent", {}),
            (gate, "prompt", ""), (gate, "prompt", 5),
            (fan, "on_branch_fail", "failall"), (fan, "join", "some"),
            (fan, "isolate", "tmp"),
        ]
        for node, key, bad in cases:
            self.assert_bad({**node, key: bad}, key)

    def test_valid_values_still_pass(self):
        node = {"id": "a", "instruction": "go", "timeout": 5, "retries": 0, "execution": "lead",
                "brief": "full", "fresh": True, "isolate": "worktree", "outputs": ["x"],
                "inputs": {"k": 1, "j": "v", "i": False}, "model": "m", "next": "end"}
        self.assertEqual(self.errors(node), [])

    def test_attempts_and_check_timeout(self):
        node = {"id": "a", "instruction": "go", "check": {"run": ["x"], "attempts": "3"}}
        self.assertIn("bad-type", {i.code for i in self.errors(node)})

    def test_top_level_types(self):
        node = {"id": "a", "instruction": "go"}
        for extra in ({"inputs": True}, {"inputs": {"x": "string"}}, {"inputs": {"x": {"type": "path"}}},
                      {"defaults": [1]}, {"defaults": {"model": 3}}, {"defaults": {"extra": 1}},
                      {"outputs": {"o": 1}}, {"outputs": []}, {"ui": "x"}, {"start": ["a"]}):
            errs = self.errors(node, **extra)
            self.assertTrue(errs, extra)

    def test_bool_version_rejected(self):
        issues = validate.validate_doc({"version": True, "nodes": [{"id": "a", "instruction": "x"}]})
        self.assertIn("bad-version", {i.code for i in issues})


class NoCrashOnWrongTypesTest(unittest.TestCase):
    """Wrong-typed values are reported as ordinary issues, never raised."""

    BAD = [None, True, False, 0, 1.5, "30s", "", [], ["b"], [1], {}, {"a": 1}, [[]], [{}]]

    def base(self):
        return {"version": 1, "name": "r", "inputs": {"a": {"type": "string"}},
                "defaults": {"model": "m", "max_visits": 3, "brief": "full"},
                "outputs": {"o": "x"}, "ui": {}, "nodes": [
            {"id": "w", "instruction": "go", "inputs": {"k": "v"}, "outputs": ["x"],
             "artifact": ["a.md"], "check": [{"run": ["x"], "attempts": 2}], "timeout": 5,
             "routes": [{"when": "x == y", "to": "i"}, {"to": "g"}], "on_fail": "abort"},
            {"id": "i", "type": "interview", "artifact": "a.json", "next": "g",
             "sections": [{"id": "s1", "title": "T"}],
             "discuss": {"inputs": {}}, "auto": {"modes": ["auto"], "when": ["x == y"]}},
            {"id": "g", "type": "gate", "prompt": "p", "auto": {"option": "b"},
             "options": [{"id": "a", "label": "A", "to": "s", "input": "t"},
                         {"id": "b", "label": "B", "to": "end"}]},
            {"id": "s", "type": "script", "run": ["x"], "next": "p"},
            {"id": "p", "type": "parallel", "next": "end", "branches": [
                {"id": "b1", "start": "c", "steps": [{"id": "c", "instruction": "x"}]},
                {"id": "b2", "start": "e", "steps": [
                    {"id": "e", "type": "subworkflow", "workflow": "x.yaml"}]}]}]}

    def paths(self, obj, prefix=()):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield prefix + (k,)
                yield from self.paths(v, prefix + (k,))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield prefix + (i,)
                yield from self.paths(v, prefix + (i,))

    def test_no_exception_for_any_wrong_typed_field(self):
        import copy
        for path in list(self.paths(self.base())):
            for bad in self.BAD:
                doc = copy.deepcopy(self.base())
                target = doc
                for p in path[:-1]:
                    target = target[p]
                target[path[-1]] = bad
                try:
                    validate.validate_doc(doc)
                except Exception as exc:  # noqa: BLE001
                    self.fail(f"{path} = {bad!r}: {type(exc).__name__}: {exc}")

    def test_reported_not_raised(self):
        node = {"id": "a", "instruction": "x"}
        for patch, code in (({"next": ["b"]}, "bad-type"),
                            ({"routes": [{"when": False, "to": "end"}]}, "bad-type"),
                            ({"on_fail": ["b"]}, "bad-type"),
                            ({"routes": True}, "bad-type"),
                            ({"type": []}, "bad-type")):
            issues = validate.validate_doc({"nodes": [{**node, **patch}]})
            self.assertIn(code, {i.code for i in issues}, patch)


if __name__ == "__main__":
    unittest.main()
