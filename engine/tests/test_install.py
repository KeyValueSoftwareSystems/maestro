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

    def test_reinstall_keeps_an_edited_skill_and_records_the_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.install(tmp, "claude-code", "--stack", "react")
            skills = os.path.join(tmp, ".claude", "skills")
            edited = os.path.join(skills, "prd-writing", "SKILL.md")
            stock = os.path.join(skills, "fix-loop", "SKILL.md")
            with open(edited, "a", encoding="utf-8") as fh:
                fh.write("\nOur house rule: every PRD names its product owner.\n")
            # simulate an older stock copy the user never touched
            manifest_path = os.path.join(tmp, ".maestro", "skill-manifest.json")
            import json
            import sys
            sys.path.insert(0, os.path.join(ROOT, "engine"))
            import install_skills
            with open(stock, "a", encoding="utf-8") as fh:
                fh.write("\nold upstream line\n")
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
            manifest["hosts"]["claude-code"]["fix-loop"] = install_skills.tree_hash(
                os.path.dirname(stock))
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)

            result = self.install(tmp, "claude-code", "--stack", "react")
            self.assertFalse(os.path.exists(os.path.join(tmp, "maestro.config.yaml")))
            with open(edited, encoding="utf-8") as fh:
                self.assertIn("Our house rule", fh.read())          # the edit survives
            self.assertTrue(os.path.isfile(edited + ".upstream"))   # the new version beside it
            with open(stock, encoding="utf-8") as fh:
                self.assertNotIn("old upstream line", fh.read())    # a stock copy is replaced
            self.assertIn("kept your edited skill prd-writing", result.stdout)
            with open(os.path.join(tmp, ".maestro", "install.json"), encoding="utf-8") as fh:
                record = json.load(fh)
            self.assertEqual(record["ref"], "main")
            self.assertEqual(record["hosts"], ["claude-code"])
            self.assertEqual(record["stacks"], ["react"])

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
            # every host gets the role definitions the engine names in each prompt
            self.assertTrue(os.path.isfile(os.path.join(tmp, ".maestro", "agents", "product.md")))
            # no per-stack agents: a stack's review checklist is a skill, filtered by --stack
            self.assertFalse(any(name.endswith("-reviewer.md") for name in os.listdir(
                os.path.join(tmp, ".maestro", "agents"))))
            self.assertTrue(os.path.isfile(os.path.join(
                tmp, ".agents", "skills", "react-review", "SKILL.md")))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".agents", "skills", "go-review")))
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

    def test_upgrade_removes_retired_stack_agents_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = os.path.join(tmp, ".claude", "agents")
            os.makedirs(agents)
            for name in ("go-reviewer.md", "my-own-agent.md"):
                with open(os.path.join(agents, name), "w", encoding="utf-8") as fh:
                    fh.write("---\nname: x\n---\n")
            self.install(tmp, "claude-code")
            self.assertFalse(os.path.exists(os.path.join(agents, "go-reviewer.md")))
            self.assertTrue(os.path.exists(os.path.join(agents, "my-own-agent.md")))
            self.assertTrue(os.path.exists(os.path.join(agents, "reviewer.md")))

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
