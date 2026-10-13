"""Incremental dispatch (worker claims) and engine-run script steps.

Proves the lead never has to round-trip engine-owned scripts, that a finished parallel worker
releases only ITS branch's follow-up work instead of waiting for the whole wave, that a branch
waiting on a human never holds back another branch's workers, and that a resumed run re-serves
workers a lost session had claimed.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ENGINE)
import maestroctl  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402


PARALLEL_WF = """\
version: 1
name: par
inputs:
  slug: {type: string, required: true}
start: fan
nodes:
  - id: fan
    type: parallel
    branches:
      - id: a
        start: impl
        steps:
          - id: impl
            instruction: Build A.
            outputs: [note]
            next: review
          - id: review
            instruction: Review A.
            outputs: [note]
            next: end
      - id: b
        start: impl
        steps:
          - id: impl
            instruction: Build B.
            outputs: [note]
            retries: 1
            next: approve
          - id: approve
            type: gate
            prompt: Ship B?
            options:
              - {id: yes, label: Yes, to: end}
    next: end
"""

SCRIPT_WF = """\
version: 1
name: scripted
inputs:
  slug: {type: string, required: true}
start: probe
nodes:
  - id: probe
    type: script
    run: [python3, .maestro/engine/probe.py, "${inputs.slug}"]
    routes:
      - {when: "${steps.probe.outputs.state} == ready", to: locker}
      - {to: end}
  - id: locker
    type: script
    run: [python3, .maestro/engine/locker.py, "${inputs.slug}"]
    next: external
  - id: external
    type: script
    run: [python3, tools/external.py]
    next: work
  - id: work
    instruction: Do the work.
    outputs: [note]
    next: end
"""

PROBE = """\
import json, sys
print("probing", sys.argv[1])
print(json.dumps({"state": "ready"}))
"""

# An engine helper that takes the SAME slug lock (like implementation_pool / lld_repo_pool):
# it would deadlock if the engine ran scripts while holding the ledger lock.
LOCKER = """\
import json, os, sys
sys.path.insert(0, %r)
import state as statemod
with statemod.locked(sys.argv[1], "."):
    pass
print(json.dumps({"locked": True}))
""" % ENGINE


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-dispatch-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, ".maestro", "engine"))
        os.makedirs(os.path.join(self.tmp, "tools"))
        for name, body in (("probe.py", PROBE), ("locker.py", LOCKER)):
            with open(os.path.join(self.tmp, ".maestro", "engine", name), "w") as fh:
                fh.write(body)
        with open(os.path.join(self.tmp, "tools", "external.py"), "w") as fh:
            fh.write("print('{}')\n")
        os.environ.pop("MAESTRO_AUTO_SCRIPTS", None)

    def write(self, rel, text):
        with open(os.path.join(self.tmp, rel), "w") as fh:
            fh.write(text)
        return rel

    def ctl(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = maestroctl.main(["--root", self.tmp, *argv])
        self.assertIn(code, (0, 4), err.getvalue())
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else None)

    def state(self, slug="feat"):
        return statemod.load(slug, self.tmp)


class ClaimTest(Base):
    def start(self):
        self.ctl("init", "--slug", "feat", "--workflow", self.write("w.yaml", PARALLEL_WF))

    def test_wave_is_claimed_and_not_reserved(self):
        self.start()
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual(action["action"], "run_agents")
        self.assertEqual({a["step"] for a in action["agents"]}, {"fan[a]/impl", "fan[b]/impl"})
        _, again = self.ctl("next", "--slug", "feat")
        self.assertEqual(again["action"], "wait")
        self.assertEqual(set(again["in_flight"]), {"fan[a]/impl", "fan[b]/impl"})

    def test_finished_worker_releases_only_its_own_followup(self):
        self.start()
        self.ctl("next", "--slug", "feat")
        _, action = self.ctl("complete", "--slug", "feat", "--step", "fan[a]/impl",
                             "--outputs", '{"note": "a"}')
        # branch a's review is ready now; branch b's impl is still in flight, not re-served
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fan[a]/review"))

    def test_ready_worker_is_served_before_another_branchs_gate(self):
        self.start()
        self.ctl("next", "--slug", "feat")
        _, action = self.ctl("complete", "--slug", "feat", "--step", "fan[b]/impl",
                             "--outputs", '{"note": "b"}')
        # b now waits on a human; a's impl is in flight, so the gate is what's left to do
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "fan[b]/approve"))
        _, action = self.ctl("complete", "--slug", "feat", "--step", "fan[a]/impl",
                             "--outputs", '{"note": "a"}')
        # a's review must be dispatched first; the open gate does not block it
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fan[a]/review"))
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual((action["action"], action["step"]), ("ask_gate", "fan[b]/approve"))

    def test_peek_never_claims(self):
        self.start()
        _, first = self.ctl("next", "--slug", "feat", "--peek")
        _, second = self.ctl("next", "--slug", "feat", "--peek")
        self.assertEqual(first, second)
        self.assertNotIn("dispatched_at", self.state()["steps"]["fan[a]/impl"])

    def test_retry_after_failure_reserves_the_step(self):
        self.start()
        self.ctl("next", "--slug", "feat")
        _, action = self.ctl("fail", "--slug", "feat", "--step", "fan[b]/impl",
                             "--reason", "worker crashed")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fan[b]/impl"))

    def test_resume_releases_claims_of_a_lost_session(self):
        self.start()
        self.ctl("next", "--slug", "feat")
        _, waiting = self.ctl("next", "--slug", "feat")
        self.assertEqual(waiting["action"], "wait")
        self.ctl("init", "--slug", "feat", "--workflow", "w.yaml")
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual(action["action"], "run_agents")

    def test_complete_batch_records_the_wave_in_one_call(self):
        self.start()
        self.ctl("next", "--slug", "feat")
        code, action = self.ctl("complete-batch", "--slug", "feat", "--results", json.dumps([
            {"step": "fan[a]/impl", "outputs": {"note": "a"}},
            {"step": "fan[b]/impl", "outputs": {}},  # missing field -> reported, not fatal
        ]))
        self.assertEqual(code, 4)
        self.assertEqual([r["status"] for r in action["batch"]], ["done", "error"])
        self.assertIn("missing output", action["batch"][1]["error"])
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fan[a]/review"))
        st = self.state()
        self.assertEqual(st["steps"]["fan[a]/impl"]["status"], "done")
        self.assertIn("dispatched_at", st["steps"]["fan[b]/impl"])  # still the lead's to retry

    def test_plain_resolver_view_is_unchanged(self):
        self.start()
        run = resolver.Run("feat", self.tmp)
        first = resolver.next_action(run)
        self.assertEqual(first["action"], "run_agents")
        self.assertEqual(resolver.next_action(run), first)
        self.assertFalse(any("dispatched_at" in e for e in run.state["steps"].values()))


INPUT_WF = """\
version: 1
name: inp
inputs:
  slug: {type: string, required: true}
start: fan
nodes:
  - id: fan
    type: parallel
    branches:
      - id: a
        start: impl
        steps:
          - id: impl
            instruction: Build A.
            outputs: [note]
            next: review
          - id: review
            instruction: Review A.
            outputs: [note]
            next: end
      - id: b
        start: ask
        steps:
          - id: ask
            type: gate
            prompt: Ship B?
            options:
              - {id: yes, label: Yes, to: end}
              - {id: change, label: Change it, to: end, input: feedback}
    next: end
"""


class GateInputPriorityTest(Base):
    def test_requested_text_input_comes_before_another_branchs_ready_worker(self):
        self.ctl("init", "--slug", "feat", "--workflow", self.write("i.yaml", INPUT_WF))
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual(action["step"], "fan[a]/impl")
        # a's impl finishes without serving its follow-up: a/review is ready, unclaimed
        with statemod.locked("feat", self.tmp):
            run = resolver.Run("feat", self.tmp)
            resolver.complete_step(run, "fan[a]/impl", outputs={"note": "a"})
            statemod.save("feat", run.state, self.tmp)
        _, action = self.ctl("gate-record", "--slug", "feat", "--step", "fan[b]/ask",
                             "--option", "change")
        self.assertEqual((action["action"], action["step"]), ("ask_input", "fan[b]/ask"))
        _, action = self.ctl("gate-input-record", "--slug", "feat", "--step", "fan[b]/ask",
                             "--input", "rename it")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "fan[a]/review"))


class AutoScriptTest(Base):
    def start(self):
        self.ctl("init", "--slug", "feat", "--workflow", self.write("s.yaml", SCRIPT_WF))

    def test_engine_scripts_run_inside_the_serving_call(self):
        self.start()
        _, action = self.ctl("next", "--slug", "feat")
        # probe + locker ran (locker takes the slug lock itself: no deadlock), external is not
        # pack code, so it is still the lead's to run.
        self.assertEqual([s["step"] for s in action["auto_scripts"]], ["probe", "locker"])
        self.assertEqual((action["action"], action["step"]), ("run_script", "external"))
        st = self.state()
        self.assertEqual(st["steps"]["probe"]["outputs"]["state"], "ready")
        self.assertEqual(st["steps"]["probe"]["telemetry"], {"executor": "engine"})
        self.assertTrue(st["steps"]["locker"]["outputs"]["locked"])
        _, action = self.ctl("complete", "--slug", "feat", "--step", "external",
                             "--exit-code", "0", "--stdout", "{}")
        self.assertEqual((action["action"], action["step"]), ("run_agent", "work"))
        self.assertNotIn("auto_scripts", action)

    def test_opt_out_serves_scripts_to_the_lead(self):
        os.environ["MAESTRO_AUTO_SCRIPTS"] = "0"
        self.addCleanup(os.environ.pop, "MAESTRO_AUTO_SCRIPTS", None)
        self.start()
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual((action["action"], action["step"]), ("run_script", "probe"))
        self.assertNotIn("auto_scripts", action)

    def test_peek_does_not_run_scripts(self):
        self.start()
        _, action = self.ctl("next", "--slug", "feat", "--peek")
        self.assertEqual((action["action"], action["step"]), ("run_script", "probe"))
        self.assertEqual(self.state()["steps"]["probe"]["status"], "pending")

    def test_failing_engine_script_follows_on_fail(self):
        self.start()
        with open(os.path.join(self.tmp, ".maestro", "engine", "probe.py"), "w") as fh:
            fh.write("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
        _, action = self.ctl("next", "--slug", "feat")
        self.assertEqual(action["auto_scripts"][0]["exit_code"], 3)
        # default on_fail for a script is a synthesized retry/skip/abort gate
        self.assertEqual(action["action"], "ask_gate")
        self.assertIn("boom", self.state()["steps"]["probe"]["reason"])

    def test_only_pack_scripts_count_as_engine_owned(self):
        root = self.tmp
        self.assertTrue(maestroctl._engine_owned(["python3", ".maestro/engine/probe.py"], root))
        self.assertFalse(maestroctl._engine_owned(["python3", "tools/external.py"], root))
        self.assertFalse(maestroctl._engine_owned(
            ["python3", ".maestro/engine/../../tools/external.py"], root))
        self.assertFalse(maestroctl._engine_owned(["bash", ".maestro/engine/probe.py"], root))
        self.assertFalse(maestroctl._engine_owned(["python3"], root))


if __name__ == "__main__":
    unittest.main()
