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
            with open(os.path.join(
                tmp, ".agents", "skills", "maestro", "SKILL.md"
            ), encoding="utf-8") as handle:
                maestro_skill = handle.read()
            self.assertIn("request_user_input", maestro_skill)
            self.assertIn("derive a concise kebab-case slug", maestro_skill)
            self.assertIn("print the same choices as a numbered", maestro_skill)
            self.assertIn("### Skill preflight", maestro_skill)
            self.assertIn("Do not use `locate`", maestro_skill)
            self.assertIn("cursor remains resumable", maestro_skill)
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "maestro-init", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "react-testing", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "prd-interview", "SKILL.md"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "prd-writing", "SKILL.md"
            )))
            self.assertFalse(os.path.exists(os.path.join(
                tmp, ".agents", "skills", "brainstorm"
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

    def test_upgrade_removes_only_retired_brainstorm_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            retired = os.path.join(tmp, ".agents", "skills", "brainstorm")
            custom = os.path.join(tmp, ".agents", "skills", "my-custom-skill")
            os.makedirs(retired)
            os.makedirs(custom)
            with open(os.path.join(retired, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("old Maestro skill\n")
            with open(os.path.join(custom, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("user skill\n")

            self.install(tmp, "codex", "--stack", "react")

            self.assertFalse(os.path.exists(retired))
            self.assertTrue(os.path.isfile(os.path.join(custom, "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
