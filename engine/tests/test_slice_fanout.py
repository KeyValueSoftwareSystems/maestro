"""Slice fan-out: the engine splits a validated task plan into slice groups, builds each in its own
worktree, merges them into the feature branch, and impl.yaml routes a one-group plan to the single
implementer as before."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import living_docs  # noqa: E402
import resolver  # noqa: E402
import run_layout  # noqa: E402
import slice_pool  # noqa: E402
import state as statemod  # noqa: E402
import todo  # noqa: E402
import validate_tasks  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SLUG = "demo"


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def call(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = slice_pool.main(list(argv))
    text = out.getvalue().strip()
    return code, json.loads(text) if code == 0 and text else err.getvalue()


def task(tid, group, writes, depends_on=()):
    return {"id": tid, "group_id": group, "title": f"task {tid}", "depends_on": list(depends_on),
            "reads": [], "writes": list(writes), "test": "unit", "standards": [],
            "needs_human_gate": False}


def plan(repo, groups):
    """groups: {group_id: [(task id, writes, depends_on), ...]} in plan order."""
    return {"schema_version": 1, "stack": repo, "feature_slug": SLUG,
            "context_manifest": {"read_once": ["lld"], "reference": []},
            "slices": [{"group_id": g, "task_ids": [t[0] for t in ts]} for g, ts in groups.items()],
            "tasks": [task(t[0], g, t[1], t[2] if len(t) > 2 else ()) for g, ts in groups.items()
                      for t in ts]}


class GitWorkspace(unittest.TestCase):
    """A workspace with one repository and the engine-made feature worktree for it."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="slices-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo_path = os.path.join(self.root, "codebase", "backend")
        os.makedirs(self.repo_path)
        git(self.repo_path, "init", "-q")
        git(self.repo_path, "config", "user.email", "test@example.com")
        git(self.repo_path, "config", "user.name", "Test")
        Path(self.repo_path, "README.md").write_text("backend\n")
        git(self.repo_path, "add", "README.md")
        git(self.repo_path, "commit", "-q", "-m", "initial")
        self.branch = f"feature/{SLUG}-backend"
        self.feature = os.path.join(self.root, ".maestro", "worktrees", SLUG, "backend")
        os.makedirs(os.path.dirname(self.feature))
        git(self.repo_path, "worktree", "add", "-q", "-b", self.branch, self.feature, "HEAD")
        self.tasks_path = os.path.join(self.root, ".maestro", "runs", SLUG, "build", "backend",
                                       "tasks.json")
        os.makedirs(os.path.dirname(self.tasks_path))

    def write_plan(self, groups):
        Path(self.tasks_path).write_text(json.dumps(plan("backend", groups)))

    def init(self, worktree=None):
        return call("init", "--root", self.root, "--slug", SLUG, "--repo", "backend",
                    "--tasks", self.tasks_path, "--worktree",
                    self.feature if worktree is None else worktree, "--branch", self.branch)

    def claim(self, slot):
        return call("claim", "--root", self.root, "--slug", SLUG, "--repo", "backend",
                    "--slot", slot)

    def record(self, slot, group, *extra):
        return call("record", "--root", self.root, "--slug", SLUG, "--repo", "backend",
                    "--slot", slot, "--group", group, "--tests-passed=true",
                    f"--summary=built {group}", *extra)

    def merge(self):
        return call("merge", "--root", self.root, "--slug", SLUG, "--repo", "backend")

    def build(self, claimed, files=None):
        """What a slice agent does: commit its files in the slice worktree it was given."""
        for name, content in (files or {f"{claimed['group_id']}.txt": "built\n"}).items():
            Path(claimed["worktree"], name).write_text(content)
        git(claimed["worktree"], "add", "-A")
        git(claimed["worktree"], "commit", "-q", "-m", f"slice {claimed['group_id']}")
        return git(claimed["worktree"], "rev-parse", "HEAD")

    def pool(self):
        return json.loads(Path(run_layout.path(SLUG, self.root, run_layout.slice_pool(
            "backend"))).read_text())

    def head(self):
        return git(self.feature, "rev-parse", "HEAD")


class SlicePoolTest(GitWorkspace):
    THREE = {"api": [("t1", ["src/api.py"]), ("t2", ["tests/test_api.py"], ["t1"])],
             "jobs": [("t3", ["src/jobs.py"])],
             "ui": [("t4", ["web/page.tsx"])]}

    def test_one_group_is_not_fanned_out(self):
        self.write_plan({"api": [("t1", ["src/api.py"])]})
        code, out = self.init()
        self.assertEqual(code, 0)
        self.assertEqual((out["slice_count"], out["fanout"], out["valid"]), (1, False, True))
        self.assertEqual(self.claim("slot_1")[1]["done"], True)

    def test_no_engine_worktree_or_a_dirty_one_keeps_the_single_implementer(self):
        self.write_plan(self.THREE)
        code, out = self.init(worktree="")
        self.assertEqual((code, out["fanout"], out["slice_count"]), (0, False, 3))
        self.assertIn("no engine-created feature worktree", out["fanout_summary"])
        Path(self.feature, "stray.txt").write_text("x\n")
        _code, out = self.init()
        self.assertFalse(out["fanout"])
        self.assertIn("uncommitted changes", out["fanout_summary"])

    def test_claims_hand_out_groups_in_plan_order_each_in_its_own_worktree(self):
        self.write_plan(self.THREE)
        base = self.head()
        code, out = self.init()
        self.assertEqual((code, out["fanout"], out["groups_csv"]), (0, True, "api,jobs,ui"))
        claims = [self.claim(slot)[1] for slot in ("slot_1", "slot_2", "slot_3")]
        self.assertEqual([c["group_id"] for c in claims], ["api", "jobs", "ui"])
        self.assertEqual(claims[0]["task_ids_csv"], "t1,t2")
        self.assertEqual(claims[0]["branch"], f"{self.branch}-slice-api")
        for claimed in claims:
            self.assertEqual(git(claimed["worktree"], "branch", "--show-current"),
                             claimed["branch"])
            self.assertEqual(git(claimed["worktree"], "rev-parse", "HEAD"), base)
        self.assertEqual(len({c["worktree"] for c in claims}), 3)
        # every group handed out: a slot that recorded its slice is done
        self.record("slot_1", "api")
        self.assertEqual(self.claim("slot_1")[1]["done"], True)

    def test_a_slot_that_has_not_recorded_gets_the_same_group_again(self):
        """A resumed run re-runs the claim step: the group is not lost, the worktree is reused
        (or checked out again when its folder was deleted)."""
        self.write_plan(self.THREE)
        self.init()
        first = self.claim("slot_1")[1]
        self.build(first)
        self.assertEqual(self.claim("slot_1")[1], first)
        shutil.rmtree(first["worktree"])
        again = self.claim("slot_1")[1]
        self.assertEqual(again["group_id"], "api")
        self.assertEqual(Path(again["worktree"], "api.txt").read_text(), "built\n")
        self.assertEqual(self.pool()["remaining"], ["jobs", "ui"])
        # the next slot still gets the next group
        self.assertEqual(self.claim("slot_2")[1]["group_id"], "jobs")

    def test_record_reads_the_commit_from_the_worktree(self):
        self.write_plan(self.THREE)
        self.init()
        claimed = self.claim("slot_1")[1]
        commit = self.build(claimed)
        code, out = self.record("slot_1", "api", "--escalate=false")
        self.assertEqual((code, out["commit"], out["empty"]), (0, commit, False))
        self.assertEqual(self.pool()["results"]["api"]["summary"], "built api")
        # nothing committed: recorded as empty, merged as nothing
        empty = self.claim("slot_2")[1]
        self.assertEqual(self.record("slot_2", "jobs")[1]["empty"], True)
        # uncommitted work is refused: it would be lost at the merge
        dirty = self.claim("slot_3")[1]
        Path(dirty["worktree"], "ui.txt").write_text("x\n")
        code, err = self.record("slot_3", "ui")
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", err)
        self.assertNotEqual(empty["worktree"], dirty["worktree"])

    def test_an_escalated_slice_stops_further_claims(self):
        self.write_plan(self.THREE)
        self.init()
        self.claim("slot_1")
        code, out = self.record("slot_1", "api", "--escalate=true",
                                "--escalation=needs an unplanned orders.tax column")
        self.assertEqual((code, out["escalate"]), (0, True))
        self.assertTrue(self.claim("slot_2")[1]["done"])
        code, merged = self.merge()
        self.assertEqual(code, 0)
        self.assertEqual((merged["merged"], merged["escalate"]), (False, True))
        self.assertIn("slice api: needs an unplanned orders.tax column", merged["escalation"])
        self.assertIn("not built: jobs, ui", merged["escalation"])

    def test_a_new_plan_replaces_the_queue_and_cleans_up_the_old_slices(self):
        self.write_plan(self.THREE)
        self.init()
        old = self.claim("slot_1")[1]
        self.build(old)  # committed, never merged: its branch is kept
        clean = self.claim("slot_2")[1]
        self.write_plan({"api": [("t1", ["src/api.py"])], "jobs": [("t3", ["src/jobs.py"])]})
        code, out = self.init()
        self.assertEqual((code, out["fanout"]), (0, True))
        self.assertFalse(os.path.isdir(old["worktree"]))
        self.assertFalse(os.path.isdir(clean["worktree"]))
        branches = git(self.repo_path, "branch", "--format=%(refname:short)").split()
        self.assertIn(old["branch"], branches)  # unmerged work survives
        self.assertNotIn(clean["branch"], branches)
        fresh = self.claim("slot_1")[1]
        self.assertEqual(fresh["branch"], f"{self.branch}-slice-api-r2")
        self.assertEqual(self.pool()["generation"], 2)


class SliceMergeTest(GitWorkspace):
    def build_all(self, groups, files=None):
        self.write_plan(groups)
        self.base = self.head()
        self.assertTrue(self.init()[1]["fanout"])
        commits = {}
        for index, group in enumerate(groups):
            claimed = self.claim(f"slot_{index % 3 + 1}")[1]
            commits[group] = self.build(claimed, (files or {}).get(group))
            self.record(f"slot_{index % 3 + 1}", group)
        return commits

    def test_two_slices_merge_into_the_feature_branch(self):
        commits = self.build_all({"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])]})
        code, out = self.merge()
        self.assertEqual(code, 0)
        self.assertEqual((out["merged"], out["escalate"], out["conflict"]), (True, False, False))
        self.assertEqual((out["branch"], out["worktree"]), (self.branch, self.feature))
        self.assertEqual(out["commit"], self.head())
        self.assertEqual(git(self.feature, "branch", "--show-current"), self.branch)
        for name in ("api.txt", "jobs.txt"):
            self.assertTrue(Path(self.feature, name).is_file())
        # plan order: the first slice fast-forwards, the next is a merge commit on top of it
        first_parents = git(self.feature, "rev-list", "--first-parent",
                            f"{self.base}..HEAD").split()
        self.assertEqual(first_parents[-1], commits["api"])
        self.assertIn("Merge slice jobs (1 tasks)", git(self.feature, "log", "-1", "--format=%s"))
        self.assertIn("api: built api; jobs: built jobs", out["summary"])
        # slice worktrees removed, merged slice branches deleted
        pool = self.pool()
        self.assertEqual(pool["merge"]["status"], "merged")
        for group in pool["groups"]:
            self.assertFalse(os.path.isdir(group["worktree"]))
        self.assertEqual(git(self.repo_path, "branch", "--list", f"{self.branch}-slice-*"), "")

    def test_three_slices_merge_in_plan_order(self):
        commits = self.build_all({"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])],
                                  "ui": [("t3", ["ui.txt"])]})
        code, out = self.merge()
        self.assertEqual((code, out["merged"]), (0, True))
        subjects = git(self.feature, "log", "--first-parent", "--format=%s",
                       f"{self.base}..HEAD").splitlines()
        self.assertEqual(subjects, [f"Merge slice ui (1 tasks) into {self.branch}",
                                    f"Merge slice jobs (1 tasks) into {self.branch}",
                                    "slice api"])
        for commit in commits.values():
            git(self.feature, "merge-base", "--is-ancestor", commit, "HEAD")

    def test_merging_again_changes_nothing(self):
        self.build_all({"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])]})
        _code, first = self.merge()
        code, second = self.merge()
        self.assertEqual(code, 0)
        self.assertEqual((second["merged"], second["commit"]), (True, first["commit"]))
        self.assertEqual(self.head(), first["commit"])

    def test_an_empty_slice_is_skipped(self):
        self.write_plan({"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])]})
        self.init()
        commit = self.build(self.claim("slot_1")[1])
        self.record("slot_1", "api")
        self.claim("slot_2")
        self.record("slot_2", "jobs")
        _code, out = self.merge()
        self.assertEqual((out["merged"], out["commit"]), (True, commit))
        self.assertIn("jobs: built jobs (no commit)", out["summary"])

    def test_a_conflict_is_reported_and_the_feature_branch_is_left_alone(self):
        commits = self.build_all(
            {"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])],
             "ui": [("t3", ["ui.txt"])]},
            files={"api": {"routes.txt": "api\n"}, "jobs": {"jobs.txt": "jobs\n"},
                   "ui": {"routes.txt": "ui\n"}})
        code, out = self.merge()
        self.assertEqual(code, 0)
        self.assertEqual((out["merged"], out["conflict"], out["escalate"]), (False, True, True))
        self.assertIn("merging slice ui", out["escalation"])
        self.assertIn("after merging api, jobs", out["escalation"])
        self.assertIn("conflicts in routes.txt", out["escalation"])
        self.assertEqual(self.head(), self.base)
        self.assertEqual(git(self.feature, "status", "--porcelain"), "")
        pool = self.pool()
        self.assertEqual((pool["merge"]["status"], pool["merge"]["files"]),
                         ("conflict", ["routes.txt"]))
        branches = git(self.repo_path, "branch", "--format=%(refname:short)").split()
        for group in pool["groups"]:  # kept for the person to inspect
            self.assertIn(group["branch"], branches)
        self.assertEqual(git(self.repo_path, "rev-parse", pool["groups"][0]["branch"]),
                         commits["api"])
        self.assertFalse(os.path.isdir(os.path.join(os.path.dirname(
            pool["groups"][0]["worktree"]), ".merge")))
        # the merge stays a report until the plan changes: running it again says the same
        _code, again = self.merge()
        self.assertEqual((again["conflict"], self.head()), (True, self.base))

    def test_a_dirty_feature_worktree_is_refused(self):
        self.build_all({"api": [("t1", ["api.txt"])], "jobs": [("t2", ["jobs.txt"])]})
        Path(self.feature, "stray.txt").write_text("x\n")
        code, err = self.merge()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", err)


class GroupSizeCapTest(unittest.TestCase):
    def doc(self, tasks, keep_together=None):
        slice_ = {"group_id": "g", "task_ids": [t["id"] for t in tasks]}
        if keep_together is not None:
            slice_["keep_together"] = keep_together
        return {"schema_version": 1, "stack": "backend", "feature_slug": SLUG,
                "context_manifest": {"read_once": [], "reference": []},
                "slices": [slice_], "tasks": tasks}

    def independent(self, n):
        return [task(f"t{i}", "g", [f"src/mod{i}.py"]) for i in range(1, n + 1)]

    def validate(self, doc):
        path = os.path.join(self.tmp, "tasks.json")
        Path(path).write_text(json.dumps(doc))
        proc = subprocess.run([sys.executable, os.path.join(REPO, "engine", "validate_tasks.py"),
                               path], capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tasks-cap-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_long_dependency_chain_stays_one_group(self):
        chain = [task(f"t{i}", "g", [f"src/step{i}.py"], [f"t{i - 1}"] if i > 1 else [])
                 for i in range(1, 16)]
        self.assertEqual(self.validate(self.doc(chain))[0], 0)

    def test_tasks_tied_by_a_shared_or_nested_write_stay_one_group(self):
        shared = [task(f"t{i}", "g", ["src/routes.py", f"src/h{i}.py"]) for i in range(1, 13)]
        self.assertIsNone(validate_tasks.check_group_sizes(self.doc(shared)))
        nested = [task("t1", "g", ["src/api/"])] + [
            task(f"t{i}", "g", [f"src/api/h{i}.py"]) for i in range(2, 13)]
        self.assertIsNone(validate_tasks.check_group_sizes(self.doc(nested)))

    def test_an_oversized_group_that_could_be_split_is_rejected_with_its_parts(self):
        tasks = self.independent(11)
        tasks[1]["depends_on"] = ["t1"]  # t1+t2 are one part, the other nine are separate
        code, out = self.validate(self.doc(tasks))
        self.assertEqual(code, 1)
        self.assertIn("slice g has 11 tasks (more than 10) in 10 independent parts", out)
        self.assertIn("[t1, t2]; [t3]", out)
        self.assertIn("give each part its own slice group", out)
        self.assertIn('"keep_together"', out)

    def test_the_cap_starts_above_ten_tasks(self):
        self.assertEqual(self.validate(self.doc(self.independent(10)))[0], 0)

    def test_keep_together_is_the_escape_hatch_and_needs_a_reason(self):
        tasks = self.independent(14)
        self.assertEqual(self.validate(self.doc(
            tasks, keep_together="one generated client; split builds would race"))[0], 0)
        code, out = self.validate(self.doc(tasks, keep_together=" "))
        self.assertEqual(code, 1)
        self.assertIn("keep_together must be a non-empty reason", out)

    def test_split_along_the_parts_validates(self):
        """The fix the message asks for always passes: one group per part."""
        tasks = self.independent(12)
        doc = self.doc(tasks)
        parts = validate_tasks.independent_parts(tasks)
        doc["slices"] = [{"group_id": f"g{i}", "task_ids": part} for i, part in enumerate(parts)]
        for i, part in enumerate(parts):
            for t in tasks:
                if t["id"] in part:
                    t["group_id"] = f"g{i}"
        self.assertEqual(self.validate(doc)[0], 0)


# -------------------------------------------------------------------------- impl.yaml routing

class ImplRoutingTest(GitWorkspace):
    """Drives the shipped impl.yaml for one repository with every engine script run for real:
    a one-group plan goes to the single implementer, two or more groups to the slice fan-out."""

    def setUp(self):
        super().setUp()
        shutil.copytree(os.path.join(REPO, "workflows"),
                        os.path.join(self.root, ".maestro", "workflows"))
        shutil.copytree(os.path.join(REPO, "engine"), os.path.join(self.root, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        Path(self.root, "maestro.config.yaml").write_text(
            'version: 1\nrepos:\n  backend:\n    commands: {build: "true", lint: "true", '
            'test: "true"}\n')
        living_docs.write_minimal_docs(self.root, "demo", ["backend"])
        self.groups = None
        self.slice_agent = None
        self.prompts = {}
        self.waves = []
        self.todos = []

    def implement(self, act):
        Path(self.feature, "single.txt").write_text("built\n")
        git(self.feature, "add", "-A")
        git(self.feature, "commit", "-q", "-m", "single implementer")
        return {"branch": self.branch, "worktree": self.feature, "commit": self.head(),
                "summary": "built", "tests_passed": True, "escalate": False,
                "escalation": "None"}

    def implement_slice(self, act):
        value = {k: re.search(rf"^- {k}: (.*)$", act["prompt"], re.MULTILINE).group(1).strip()
                 for k in ("worktree", "branch", "group_id")}
        if self.slice_agent:
            return self.slice_agent(value)
        commit = self.build({"group_id": value["group_id"], "worktree": value["worktree"]})
        return {"branch": value["branch"], "commit": commit, "summary": "built",
                "tests_passed": True, "escalate": False, "escalation": "None"}

    def agent(self, act):
        node = act["step"].rsplit("/", 1)[-1]
        for rel in act.get("artifacts", []):
            full = Path(self.root, rel)
            full.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("tasks.json"):
                full.write_text(json.dumps(plan("backend", self.groups)))
            elif rel.endswith(".findings.json"):
                full.write_text(json.dumps({"schema_version": 1, "findings": []}))
            else:
                full.write_text(f"{node}\n")
        if node == "tasks":
            return {"task_count": 1, "slice_count": 1, "escalate": False, "escalation": "None"}
        if node == "implement":
            return self.implement(act)
        if node == "implement_slice":
            return self.implement_slice(act)
        if node == "review":
            return {"review_path": "reviews/code-backend.md", "blocking": False, "summary": "ok"}
        raise AssertionError(f"unexpected agent {act['step']}")

    def drive(self, gates=None, max_steps=120):
        gates = dict(gates or {})
        with statemod.locked(SLUG, self.root):
            resolver.init_run(SLUG, ".maestro/workflows/impl.yaml", {
                "stack": "backend", "repo_path": "codebase/backend", "worktree": self.feature,
                "branch": self.branch}, self.root)
        trace = []
        for _ in range(max_steps):
            run = resolver.Run(SLUG, self.root)
            action = resolver.next_action(run)
            if action["action"] in ("done", "failed"):
                return action, trace
            batch = action["agents"] if action["action"] == "run_agents" else [action]
            self.waves.append([a["step"] for a in batch])
            self.todos.append(todo.render(todo.build(run)))  # the lead's list, mid fan-out too
            for act in batch:
                step = act["step"]
                trace.append(step + ("#check" if act.get("check") else ""))
                if "prompt" in act:
                    self.prompts.setdefault(step.rsplit("/", 1)[-1], []).append(act["prompt"])
                run = resolver.Run(SLUG, self.root)
                if act["action"] == "run_agent":
                    resolver.complete_step(run, step, outputs=self.agent(act))
                elif act["action"] == "run_script":
                    proc = subprocess.run(act["argv"], cwd=self.root, capture_output=True,
                                          text=True, timeout=120)
                    resolver.complete_step(run, step, exit_code=proc.returncode,
                                           stdout=proc.stdout)
                elif act["action"] == "ask_gate":
                    resolver.record_gate(run, step, gates[step.rsplit("/", 1)[-1]])
                else:
                    raise AssertionError(f"unexpected action {act}")
                statemod.save(SLUG, run.state, self.root)
        self.fail("impl did not finish")

    @staticmethod
    def nodes(trace):
        return [s.rsplit("/", 1)[-1] for s in trace]

    def test_one_slice_group_goes_to_the_single_implementer(self):
        self.groups = {"api": [("t1", ["src/api.py"]), ("t2", ["src/b.py"], ["t1"])]}
        action, trace = self.drive()
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(self.nodes(trace)[:6], ["tasks", "tasks#check", "tasks#check", "facts",
                                                 "implement", "handoff"])
        self.assertFalse([s for s in trace if s.startswith("slices/")])
        state = statemod.load(SLUG, self.root)
        self.assertEqual(state["steps"]["tasks"]["outputs"]["fanout"], False)
        self.assertEqual(state["steps"]["handoff"]["outputs"]["commit"], self.head())
        self.assertTrue(Path(self.feature, "single.txt").is_file())

    def test_two_slice_groups_fan_out_and_merge_before_the_handoff(self):
        self.groups = {"api": [("t1", ["api.txt"]), ("t2", ["src/b.py"], ["t1"])],
                       "jobs": [("t3", ["jobs.txt"])]}
        action, trace = self.drive()
        self.assertEqual(action["action"], "done", action)
        self.assertNotIn("implement", self.nodes(trace))
        slices = [s for s in trace if s.endswith("/implement_slice")]
        self.assertEqual(sorted(slices), ["slices/pool[slot_1]/implement_slice",
                                          "slices/pool[slot_2]/implement_slice"])
        nodes = self.nodes(trace)
        self.assertLess(nodes.index("merge"), nodes.index("handoff"))
        self.assertEqual(nodes[nodes.index("merge") + 1:nodes.index("merge") + 3],
                         ["handoff", "verify"])
        state = statemod.load(SLUG, self.root)
        # the engine decided the fan-out: its slice count wins over the planner's report
        self.assertEqual((state["steps"]["tasks"]["outputs"]["slice_count"],
                          state["steps"]["tasks"]["outputs"]["fanout"]), (2, True))
        handoff = state["steps"]["handoff"]["outputs"]
        self.assertEqual((handoff["branch"], handoff["commit"]), (self.branch, self.head()))
        for name in ("api.txt", "jobs.txt"):
            self.assertTrue(Path(self.feature, name).is_file())
        prompt = next(p for p in self.prompts["implement_slice"] if "- group_id: api" in p)
        self.assertIn("Implement ONLY slice group api", prompt)
        self.assertIn("- task_ids: t1,t2", prompt)
        self.assertIn(f"on branch `{self.branch}-slice-api`", prompt)
        self.assertEqual(action["outputs"]["commit"], self.head())
        self.assertTrue(any("Implement slices in parallel" in t for t in self.todos))

    def test_at_most_three_slices_run_at_once(self):
        self.groups = {g: [(f"t-{g}", [f"{g}.txt"])] for g in ("a", "b", "c", "d", "e")}
        action, trace = self.drive()
        self.assertEqual(action["action"], "done", action)
        self.assertEqual(len([s for s in trace if s.endswith("/implement_slice")]), 5)
        widest = max(len([s for s in wave if s.endswith("/implement_slice")])
                     for wave in self.waves)
        self.assertEqual(widest, 3)
        for g in ("a", "b", "c", "d", "e"):
            self.assertTrue(Path(self.feature, f"{g}.txt").is_file())

    def test_an_escalating_slice_goes_to_the_stop_gate(self):
        self.groups = {"api": [("t1", ["api.txt"])], "jobs": [("t3", ["jobs.txt"])]}

        def slice_agent(value):
            escalate = value["group_id"] == "jobs"
            return {"branch": value["branch"], "commit": "", "summary": "stopped",
                    "tests_passed": False, "escalate": escalate,
                    "escalation": "needs an unplanned jobs table" if escalate else "None"}
        self.slice_agent = slice_agent
        base = self.head()
        action, trace = self.drive({"stop_gate": "abandon"})
        self.assertEqual(action["action"], "failed", action)
        nodes = self.nodes(trace)
        self.assertEqual(nodes[nodes.index("merge") + 1], "stop_gate")
        self.assertIn("Slices: slice jobs: needs an unplanned jobs table",
                      self.prompts["stop_gate"][0])
        self.assertEqual(self.head(), base)

    def test_a_merge_conflict_goes_to_the_stop_gate_and_leaves_the_branch(self):
        self.groups = {"api": [("t1", ["api.txt"])], "jobs": [("t3", ["jobs.txt"])]}

        def slice_agent(value):  # both slices write a file neither task listed
            commit = self.build({"group_id": value["group_id"], "worktree": value["worktree"]},
                                {"routes.txt": f"{value['group_id']}\n"})
            return {"branch": value["branch"], "commit": commit, "summary": "built",
                    "tests_passed": True, "escalate": False, "escalation": "None"}
        self.slice_agent = slice_agent
        base = self.head()
        action, trace = self.drive({"stop_gate": "abandon"})
        self.assertEqual(action["action"], "failed", action)
        self.assertEqual(self.nodes(trace)[-1], "stop_gate")
        self.assertIn("conflicts in routes.txt", self.prompts["stop_gate"][0])
        self.assertEqual(self.head(), base)


if __name__ == "__main__":
    unittest.main()
