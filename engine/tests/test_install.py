"""Installer coverage for supported AI harness targets."""

import os
import subprocess
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALL = os.path.join(ROOT, "install.sh")


class InstallTest(unittest.TestCase):
    def install(self, destination, *args):
        env = os.environ.copy()
        env["DEST"] = destination
        return subprocess.run(
            ["bash", INSTALL, *args],
            cwd=destination,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_codex_installs_repo_scoped_skills_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.install(tmp, "codex", "--stack", "react")

            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "maestro", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "maestro-init", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "react-testing", "SKILL.md"
            )))
            self.assertFalse(os.path.exists(os.path.join(
                tmp, ".agents", "skills", "golang-testing"
            )))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".claude")))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".agents", "commands")))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".maestro", "engine", "maestroctl.py"
            )))
            self.assertIn("$maestro-init", result.stdout)
            self.assertIn("$maestro my-feature", result.stdout)

    def test_codex_can_be_installed_alongside_claude_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.install(tmp, "claude-code", "codex", "--stack", "react")

            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".claude", "skills", "maestro", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "maestro", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".claude", "agents", "implementer.md"
            )))
            self.assertIn("Claude Code / Cursor: run", result.stdout)
            self.assertIn("Codex: open the repo", result.stdout)


if __name__ == "__main__":
    unittest.main()
