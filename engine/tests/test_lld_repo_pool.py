"""Repository LLD workstreams keep team approvals in separate durable ledgers."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lld_repo_pool  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class LldWorkstreamTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="maestro-lld-workstreams-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        workflow_dir = os.path.join(self.root, ".maestro", "workflows")
        os.makedirs(workflow_dir)
        shutil.copy(
            os.path.join(REPO, "workflows", "repo-lld.yaml"),
            os.path.join(workflow_dir, "repo-lld.yaml"),
        )
        shutil.copytree(
            os.path.join(REPO, "engine"), os.path.join(self.root, ".maestro", "engine"),
            ignore=shutil.ignore_patterns("tests", "__pycache__"),
        )
        for repo in ("backend", "frontend"):
            path = os.path.join(self.root, "codebase", repo)
            os.makedirs(path)
            subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        parent = statemod.feature_dir("feature", self.root)
        os.makedirs(parent)
        with open(os.path.join(parent, "hld.md"), "w", encoding="utf-8") as fh:
            fh.write("# Feature HLD\n\nInitial architecture.\n")
        parent_state = statemod.new_state(
            "feature", ".maestro/workflows/sdlc-main.yaml", "parent-hash",
            {"slug": "feature", "feature": "Feature"},
        )
        parent_state["run"]["cursors"] = ["design/lld_workstreams_wait"]
        statemod.save("feature", parent_state, self.root)
        self.assertEqual(lld_repo_pool.cmd_init(SimpleNamespace(
            root=self.root, slug="feature", choice="all", repos_text="",
        )), 0)
        self.assertEqual(lld_repo_pool.cmd_workstreams(SimpleNamespace(
            root=self.root,
            slug="feature",
            workflow=".maestro/workflows/repo-lld.yaml",
            feature="Feature",
        )), 0)

    def queue(self):
        with open(os.path.join(
            self.root, ".maestro", "runs", "feature", "lld-repos.json",
        ), encoding="utf-8") as fh:
            return json.load(fh)

    def check(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = lld_repo_pool.cmd_check(SimpleNamespace(
                root=self.root, slug="feature",
            ))
        self.assertEqual(code, 0)
        return json.loads(output.getvalue().splitlines()[-1])

    def approve(self, repo):
        child_slug = next(
            item["slug"] for item in self.queue()["workstreams"] if item["repo"] == repo
        )
        child_dir = statemod.feature_dir(child_slug, self.root)
        for _ in range(30):
            run = resolver.Run(child_slug, self.root)
            action = resolver.next_action(run)
            if action["action"] == "done":
                break
            step = action["step"]
            if action["action"] in ("run_agent", "run_lead"):
                for rel in action.get("artifacts", []):
                    full = os.path.join(self.root, rel)
                    os.makedirs(os.path.dirname(full), exist_ok=True)
                    if rel.endswith("lld-questions.json"):
                        context = os.path.join(child_dir, "lld-context.json")
                        questions = [] if os.path.exists(context) else [{
                            "id": "failure-path",
                            "title": "Failure path",
                            "question": "How should this repository expose a failed operation?",
                            "why": "The result changes the repository contract.",
                            "proposal": "Use the existing typed failure result.",
                            "must_resolve": ["failure result"],
                        }]
                        with open(full, "w", encoding="utf-8") as fh:
                            json.dump({
                                "schema_version": 2,
                                "questions": questions,
                                "audit": {
                                    "unresolved": [] if not questions else ["failure result"],
                                    "contradictions": [],
                                },
                            }, fh)
                    elif rel.endswith("lld-post-questions.json"):
                        with open(full, "w", encoding="utf-8") as fh:
                            json.dump({
                                "schema_version": 2,
                                "questions": [],
                                "audit": {"unresolved": [], "contradictions": []},
                            }, fh)
                    elif rel.endswith("/lld.md"):
                        sections = {
                            "Change summary": "\n".join(
                                f"- Deliver repository behavior {index}."
                                for index in range(1, 5)
                            ),
                            "Existing seam": "Requests enter through `src/routes.py`.",
                            "Proposed changes": "Extend the existing service boundary.",
                            "Interfaces, state, and flows": (
                                "The route validates input, invokes the service, and returns state."
                            ),
                            "Failure and operational behavior": (
                                "Failures preserve prior state and use existing logging."
                            ),
                            "Implementation sequence": (
                                "1. Extend the service and its tests.\n"
                                "2. Connect the route and integration test."
                            ),
                            "Verification": "Service and route tests cover the behavior.",
                        }
                        with open(full, "w", encoding="utf-8") as fh:
                            fh.write(
                                f"# Feature {repo} — LLD\n\n"
                                "**Parent feature:** `feature`\n"
                                f"**Repository:** `{repo}`\n"
                                "**Status:** Ready for review\n\n"
                            )
                            fh.write("\n\n".join(
                                f"## {heading}\n\n{body}"
                                for heading, body in sections.items()
                            ) + "\n")
                outputs = (
                    {"summary": "repository questions prepared"}
                    if step == "prepare_lld_questions"
                    else {"lld_path": "lld.md", "contract_notes": "none"}
                )
                resolver.complete_step(run, step, outputs=outputs)
            elif action["action"] == "ask_interview":
                resolver.record_interview(run, step, action["section"], accept=True)
            elif action["action"] == "ask_interview_batch":
                resolver.record_interview_batch(run, step, {
                    question["section"]: {"accept": True}
                    for question in action["questions"]
                })
            elif action["action"] == "ask_gate":
                self.assertEqual(step, "lld_approval")
                resolver.record_gate(run, step, "approve")
            elif action["action"] == "run_script":
                proc = subprocess.run(
                    action["argv"], cwd=self.root, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                resolver.complete_step(
                    run, step, exit_code=proc.returncode, stdout=proc.stdout,
                )
            else:
                self.fail(f"unexpected LLD child action: {action}")
            statemod.save(child_slug, run.state, self.root)
        else:
            self.fail(f"LLD child {child_slug} did not finish")
        self.assertEqual(resolver.next_action(resolver.Run(child_slug, self.root))["action"], "done")
        return child_slug

    def test_one_team_approval_does_not_approve_another(self):
        summary = lld_repo_pool.workstream_summary("feature", self.root)
        self.assertTrue(summary["available"])
        self.assertEqual(
            {item["repo"] for item in summary["workstreams"]}, {"backend", "frontend"},
        )
        backend_slug = self.approve("backend")
        status = self.check()
        self.assertFalse(status["ready"])
        self.assertEqual(status["pending_csv"], "frontend")
        self.assertEqual(statemod.load(backend_slug, self.root)["run"]["status"], "done")
        frontend = statemod.load("feature--lld--frontend", self.root)
        self.assertEqual(frontend["run"]["status"], "running")
        self.assertEqual(frontend["run"]["cursors"], ["prepare_lld_questions"])
        self.assertEqual(frontend["inputs"]["repo_path"], "codebase/frontend")

        self.approve("frontend")
        self.assertTrue(self.check()["ready"])

    def test_hld_change_creates_new_pending_generation(self):
        self.approve("backend")
        self.approve("frontend")
        self.assertTrue(self.check()["ready"])
        with open(os.path.join(
            statemod.feature_dir("feature", self.root), "hld.md",
        ), "a", encoding="utf-8") as fh:
            fh.write("Changed architecture.\n")

        self.assertEqual(lld_repo_pool.cmd_init(SimpleNamespace(
            root=self.root, slug="feature", choice="all", repos_text="",
        )), 0)
        self.assertEqual(lld_repo_pool.cmd_workstreams(SimpleNamespace(
            root=self.root,
            slug="feature",
            workflow=".maestro/workflows/repo-lld.yaml",
            feature="Feature",
        )), 0)
        queue = self.queue()
        self.assertEqual(queue["generation"], 2)
        self.assertEqual(
            {item["slug"] for item in queue["workstreams"]},
            {"feature--lld--backend--v2", "feature--lld--frontend--v2"},
        )
        self.assertFalse(self.check()["ready"])

    def test_published_lld_tamper_blocks_parent_join(self):
        self.approve("backend")
        self.approve("frontend")
        published = os.path.join(
            statemod.feature_dir("feature", self.root), "lld", "backend.md",
        )
        with open(published, "a", encoding="utf-8") as fh:
            fh.write("Unapproved edit.\n")
        status = self.check()
        self.assertFalse(status["ready"])
        self.assertEqual(status["pending_csv"], "backend")


if __name__ == "__main__":
    unittest.main()
