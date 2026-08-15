"""Simulator safety guards, exit status, and a no-LLM full workflow walk."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resolver  # noqa: E402
import simulate  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="maestro-sim-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(os.path.join(REPO, "workflows"),
                        os.path.join(self.root, ".maestro", "workflows"))
        shutil.copytree(os.path.join(REPO, "engine"),
                        os.path.join(self.root, ".maestro", "engine"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        repo = os.path.join(self.root, "codebase", "mobile")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        with open(os.path.join(repo, "README.md"), "w") as fh:
            fh.write("mobile\n")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
        requirement = os.path.join(self.root, ".maestro", "runs", "sim", "requirement")
        os.makedirs(requirement)
        with open(os.path.join(requirement, "seed.md"), "w") as fh:
            fh.write("Build a simulated feature.\n")

    def argv(self, *extra):
        return ["simulate.py", "--root", self.root, "--workflow",
                ".maestro/workflows/sdlc-main.yaml", "--slug", "sim",
                "--input", "feature=Simulation", "--auto", *extra]

    def test_requires_explicit_script_side_effect_acknowledgement(self):
        with self.assertRaises(resolver.RunError) as ctx:
            simulate.main(self.argv())
        self.assertEqual(ctx.exception.code, 3)

    def test_max_steps_has_nonzero_exit_status(self):
        code = simulate.main(self.argv("--allow-script-side-effects", "--max-steps", "0"))
        self.assertEqual(code, 2)

    def test_refuses_existing_slug_without_force(self):
        simulate.main(self.argv("--allow-script-side-effects", "--max-steps", "0"))
        with self.assertRaises(resolver.RunError) as ctx:
            simulate.main(self.argv("--allow-script-side-effects", "--max-steps", "0"))
        self.assertEqual(ctx.exception.code, 3)

    def test_failed_workflow_has_nonzero_exit_status(self):
        workflow = os.path.join(self.root, ".maestro", "workflows", "fail.yaml")
        with open(workflow, "w") as fh:
            fh.write(
                "version: 1\nname: fail\nstart: fail\nnodes:\n"
                "  - id: fail\n    type: script\n    run: [\"false\"]\n"
                "    on_fail: abort\n"
            )
        argv = ["simulate.py", "--root", self.root, "--workflow",
                ".maestro/workflows/fail.yaml", "--slug", "failed-sim",
                "--auto", "--allow-script-side-effects"]
        self.assertEqual(simulate.main(argv), 1)

    def test_full_sdlc_happy_path_finishes_without_llm(self):
        code = simulate.main(self.argv("--allow-script-side-effects"))
        self.assertEqual(code, 0)
        manifest = os.path.join(self.root, ".maestro", "runs", "sim",
                                "implementation-manifest.json")
        self.assertTrue(os.path.isfile(manifest))


if __name__ == "__main__":
    unittest.main()
