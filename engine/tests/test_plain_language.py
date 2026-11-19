"""Every message a shipped workflow puts in front of the person is plain language.

Each node carries a `say:` progress line that passes the `say-style` lint; every gate option
carries a one-line `description` (its consequence); and no say line, label, gate prompt or
option text uses the engine's internal vocabulary or a step id. Recovery questions the engine
synthesizes name the step by its label, not its path."""
import glob
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import validate as validatemod  # noqa: E402
import wf  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = sorted(glob.glob(os.path.join(ROOT, "workflows", "*.yaml")))

# Words the person should never have to decode. Placeholders are stripped first, so a value
# pulled from a step's outputs is not held against the wording around it.
BANNED = re.compile(
    r"\b(worktrees?|manifests?|lld|hld|slices?|fan-out|verdicts?|json|skills?|subagents?|"
    r"ledger|engine|dag|provenance|snapshots?|grill)\b", re.IGNORECASE)
# A step id or config key: snake_case words such as `plan_approval` or `sync_restart`.
STEP_ID = re.compile(r"\b[a-z]+_[a-z_]+\b")
PLACEHOLDER = re.compile(r"\$\{[^}]*\}")


def nodes(steps, prefix=""):
    for node in steps or []:
        yield prefix + node["id"], node
        for branch in node.get("branches") or []:
            yield from nodes(branch.get("steps"), f"{prefix}{node['id']}[{branch['id']}]/")


def shipped():
    for path in WORKFLOWS:
        with open(path, encoding="utf-8") as fh:
            doc = wf.loads(fh.read())
        for node_path, node in nodes(doc.get("nodes")):
            yield os.path.basename(path), node_path, node


def plain_problems(text):
    bare = PLACEHOLDER.sub("", text)
    return BANNED.findall(bare) + STEP_ID.findall(bare)


class ShippedWordingTest(unittest.TestCase):
    def test_every_node_has_a_plain_say_line(self):
        for name, path, node in shipped():
            with self.subTest(workflow=name, node=path):
                say = node.get("say")
                self.assertIsInstance(say, str, "missing say:")
                self.assertTrue(say.strip())
                self.assertLessEqual(len(say.strip()), validatemod.SAY_MAX)
                self.assertNotIn("${steps.", say)
                self.assertNotIn("\n", say.strip())

    def test_validate_reports_no_say_style_warning(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=os.path.basename(path)):
                issues = validatemod.validate_file(path)
                self.assertEqual([str(i) for i in issues if i.code == "say-style"], [])

    def test_every_gate_option_says_what_it_leads_to(self):
        gates = 0
        for name, path, node in shipped():
            if node.get("type") != "gate":
                continue
            gates += 1
            for option in node["options"]:
                with self.subTest(workflow=name, gate=path, option=option["id"]):
                    self.assertTrue((option.get("description") or "").strip(),
                                    "option needs a one-line description (its consequence)")
                    self.assertNotIn("\n", option["description"].strip())
        self.assertGreater(gates, 10)

    def test_no_internal_words_reach_the_person(self):
        for name, path, node in shipped():
            texts = {"say": node.get("say") or "", "label": node.get("label") or ""}
            if node.get("type") == "gate":
                texts["prompt"] = node["prompt"]
                for option in node["options"]:
                    texts[f"option {option['id']}"] = (
                        option["label"] + " " + (option.get("description") or ""))
            for field, text in texts.items():
                with self.subTest(workflow=name, node=path, field=field):
                    self.assertEqual(plain_problems(text), [])

    def test_gate_prompt_opens_with_the_question(self):
        """The decision comes first: the prompt's first line asks it."""
        for name, path, node in shipped():
            if node.get("type") != "gate":
                continue
            with self.subTest(workflow=name, gate=path):
                first = node["prompt"].strip().splitlines()[0]
                self.assertTrue(first.rstrip().endswith("?"), first)


RECOVERY_WF = """\
version: 1
name: recovery
start: build_step
nodes:
  - id: build_step
    type: script
    label: Build the app
    say: Building the app.
    run: ["false"]
    on_fail: ask
    next: end
"""


class RecoveryWordingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-plain-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "workflows"))
        rel = os.path.join("workflows", "w.yaml")
        with open(os.path.join(self.tmp, rel), "w") as fh:
            fh.write(RECOVERY_WF)
        resolver.init_run("feat", rel, {}, self.tmp)

    def test_a_failed_step_is_named_by_its_label(self):
        run = resolver.Run("feat", self.tmp)
        resolver.complete_step(run, "build_step", exit_code=1, stdout="boom")
        statemod.save("feat", run.state, self.tmp)
        action = resolver.next_action(resolver.Run("feat", self.tmp))
        self.assertEqual((action["action"], action["synthesized"]), ("ask_gate", "fail"))
        self.assertIn("Build the app", action["prompt"])
        self.assertNotIn("build_step", action["prompt"])
        self.assertEqual([o["id"] for o in action["options"]], ["retry", "skip", "abort"])
        for option in action["options"]:
            self.assertTrue(option["description"])
        self.assertEqual(action["say"], "Building the app.")


class DescriptionServedTest(unittest.TestCase):
    def test_option_description_is_served_with_its_placeholders_resolved(self):
        tmp = tempfile.mkdtemp(prefix="maestro-plain-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "workflows"))
        rel = os.path.join("workflows", "w.yaml")
        with open(os.path.join(tmp, rel), "w") as fh:
            fh.write("""\
version: 1
name: described
inputs:
  slug: {type: string, required: true}
start: ask
nodes:
  - id: ask
    type: gate
    say: One choice for you.
    prompt: Go on?
    options:
      - id: later
        label: Later
        description: "Resume with /maestro ${inputs.slug}."
        pause: true
      - {id: go, label: Go, to: end}
""")
        resolver.init_run("feat", rel, {"slug": "feat"}, tmp)
        action = resolver.next_action(resolver.Run("feat", tmp))
        self.assertEqual(action["options"][0]["description"], "Resume with /maestro feat.")
        self.assertNotIn("description", action["options"][1])


if __name__ == "__main__":
    unittest.main()
