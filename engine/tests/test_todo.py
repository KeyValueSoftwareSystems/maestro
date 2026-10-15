"""The run's todo list: stages in order, the running stage expanded, optional stages only once
entered, and `init` / `next` handing it to the lead only when what the human sees has moved."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import maestroctl  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import test_sdlc_e2e as e2e  # noqa: E402
import todo  # noqa: E402

STAGE = """\
version: 1
name: stage
nodes:
  - id: build
    label: Build it
    instruction: Build.
    next: approve
  - id: approve
    type: gate
    label: Ship approval
    prompt: Ship?
    options:
      - {id: yes, label: Yes, to: end}
"""

STAGED = """\
version: 1
name: staged
nodes:
  - id: first
    type: subworkflow
    label: First stage
    workflow: stage.yaml
    next: second
  - id: second
    type: subworkflow
    label: Second stage
    workflow: stage.yaml
    routes:
      - {when: "${steps.second.outputs.redo} == true", to: optional}
      - {to: end}
  - id: optional
    type: subworkflow
    label: Optional rework
    workflow: stage.yaml
    next: second
"""


class SdlcTodoTest(unittest.TestCase):
    """The shipped pipeline, driven without an LLM to the HLD approval gate."""

    def test_running_stage_expands_and_names_the_open_gate(self):
        driver = e2e.SdlcE2E("test_happy_path")
        driver.setUp()
        self.addCleanup(driver.doCleanups)
        with self.assertRaises(AssertionError):  # stops at the first unscripted gate
            driver.drive({"design/intake/collect_references": [("none", None)],
                          "design/prd/prd_approval": [("approve", None)]})
        built = todo.build(resolver.Run("demo", driver.tmp))
        self.assertEqual(todo.render(built).splitlines(), [
            "demo · sdlc-main · running",
            "[x] Workspace sync (feature start)",
            "[>] Design phase",
            "    [x] Requirement and context",
            "    [x] PRD",
            "    [x] Codebase map check",
            "    [?] HLD",
            "          ↳ waiting on you: HLD approval",
            "    [ ] Repository LLDs",
            "    [ ] API contract and test cases",
            "[ ] Design review",
            "[ ] Implementation, QA and release",
            "[ ] Archival (harvest + publish)",
        ])
        tasks = todo.flat(built)
        self.assertIn({"content": "Design phase › HLD — waiting on you: HLD approval",
                       "status": "in_progress"}, tasks)
        self.assertEqual(tasks[0], {"content": "Workspace sync (feature start)",
                                    "status": "completed"})
        # The scoped architecture revision and the legacy import never ran: not listed.
        labels = " ".join(task["content"] for task in tasks)
        self.assertNotIn("Scoped architecture-review revision", labels)
        self.assertNotIn("Legacy run import", labels)


class CliTodoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-todo-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, text in (("stage.yaml", STAGE), ("staged.yaml", STAGED)):
            with open(os.path.join(self.tmp, name), "w") as fh:
                fh.write(text)

    def ctl(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = maestroctl.main(["--root", self.tmp, *argv])
        self.assertEqual(code, 0, err.getvalue())
        text = out.getvalue()
        try:
            return json.loads(text)
        except ValueError:
            return text

    def test_init_and_changes_carry_the_list_and_nothing_else_does(self):
        started = self.ctl("init", "--slug", "feat", "--workflow", "staged.yaml")
        self.assertEqual(started["todo"], [
            {"content": "First stage — now: Build it", "status": "in_progress"},
            {"content": "Second stage", "status": "pending"},
        ])
        action = self.ctl("next", "--slug", "feat")
        self.assertEqual(action["step"], "first/build")
        self.assertNotIn("todo", action)  # claiming the worker changed nothing the human sees
        action = self.ctl("complete", "--slug", "feat", "--step", "first/build",
                          "--outputs", "{}")
        self.assertEqual(action["step"], "first/approve")
        self.assertEqual(action["todo"][0],
                         {"content": "First stage — waiting on you: Ship approval",
                          "status": "in_progress"})
        self.assertNotIn("todo", self.ctl("next", "--slug", "feat", "--peek"))
        self.assertNotIn("todo", self.ctl("next", "--slug", "feat"))
        # Resume re-sends the list even though nothing moved.
        self.assertIn("todo", self.ctl("init", "--slug", "feat", "--workflow", "staged.yaml"))
        action = self.ctl("gate-record", "--slug", "feat", "--step", "first/approve",
                          "--option", "yes")
        self.assertEqual([t["status"] for t in action["todo"]], ["completed", "in_progress"])

    def test_optional_stage_is_listed_once_entered(self):
        self.ctl("init", "--slug", "feat", "--workflow", "staged.yaml")
        state = statemod.load("feat", self.tmp)
        run = resolver.Run("feat", self.tmp, state_data=state)
        self.assertEqual([i["label"] for i in todo.build(run)["items"]],
                         ["First stage", "Second stage"])
        state["steps"]["optional"] = {"status": "done", "attempts": 0, "visits": 1,
                                      "outputs": {}}
        self.assertEqual([i["label"] for i in todo.build(run)["items"]],
                         ["First stage", "Second stage", "Optional rework"])

    def test_todo_command_prints_the_checklist(self):
        self.ctl("init", "--slug", "feat", "--workflow", "staged.yaml")
        self.assertEqual(self.ctl("todo", "--slug", "feat").splitlines(), [
            "feat · staged · running",
            "[>] First stage",
            "      ↳ now: Build it",
            "[ ] Second stage",
        ])
        as_json = self.ctl("todo", "--slug", "feat", "--json")
        self.assertEqual(as_json["items"][0]["now"][0]["step"], "first/build")
        self.assertEqual(as_json["tasks"][1], {"content": "Second stage", "status": "pending"})


if __name__ == "__main__":
    unittest.main()
