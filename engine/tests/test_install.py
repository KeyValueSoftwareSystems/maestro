"""Installer coverage for supported AI harness targets."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALL = os.path.join(ROOT, "install.sh")
sys.path.insert(0, os.path.join(ROOT, "engine"))
import install_skills  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


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
            # a checkout records what it installed from (tag, else sha), not the default ref
            head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
            if head:
                tag = subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--exact-match", "HEAD"],
                                     text=True, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL).stdout.strip()
                self.assertEqual(record["ref"], tag or head)
                self.assertEqual(record["commit"], head)
            else:
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
            # cases that apply only sometimes are reference files installed beside the skill
            for reference in ("starting-a-run.md", "single-stage.md",
                              "interview-discussion.md", "inline-mode.md"):
                self.assertIn(f"`{reference}`", maestro_skill)
                self.assertTrue(os.path.isfile(os.path.join(
                    tmp, ".agents", "skills", "maestro", reference)), reference)
            with open(os.path.join(tmp, ".agents", "skills", "maestro", "starting-a-run.md"),
                      encoding="utf-8") as handle:
                starting = handle.read()
            self.assertIn("derive a concise kebab-case slug", starting)
            self.assertIn("print the same choices as a numbered", starting)
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
            for name, tags in (("go-reviewer.md", "tags: [stack:go, reviewer]\n"),
                               ("my-own-agent.md", "")):
                with open(os.path.join(agents, name), "w", encoding="utf-8") as fh:
                    fh.write("---\nname: x\n" + tags + "---\n")
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
                handle.write("---\nname: brainstorm\ntags: [sdlc, requirement]\n---\nold Maestro skill\n")
            with open(os.path.join(custom, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("user skill\n")

            self.install(tmp, "codex", "--stack", "react")

            self.assertFalse(os.path.exists(retired))
            self.assertTrue(os.path.isfile(os.path.join(custom, "SKILL.md")))

    def run_install(self, destination, *args, script=INSTALL):
        env = os.environ.copy()
        env["DEST"] = destination
        return subprocess.run(["bash", script, *args], cwd=destination, env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_install_into_the_pack_source_is_refused_and_deletes_nothing(self):
        # the pack repo mirrors the installed layout with `.maestro/engine -> ../engine`
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(INSTALL, os.path.join(tmp, "install.sh"))
            _write(os.path.join(tmp, "engine", "maestroctl.py"), "# stub\n")
            _write(os.path.join(tmp, "engine", "tests", "test_x.py"), "# keep me\n")
            os.makedirs(os.path.join(tmp, ".maestro"))
            os.symlink("../engine", os.path.join(tmp, ".maestro", "engine"))
            result = self.run_install(tmp, "claude-code", script=os.path.join(tmp, "install.sh"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pack source itself", result.stderr)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "engine", "tests", "test_x.py")))

    def test_symlinked_runtime_dir_is_never_written_through(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            _write(os.path.join(other, "tests", "test_x.py"), "# keep me\n")
            os.makedirs(os.path.join(tmp, ".maestro"))
            os.symlink(other, os.path.join(tmp, ".maestro", "engine"))
            result = self.run_install(tmp, "codex")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("is a symlink", result.stderr)
            self.assertEqual(os.listdir(other), ["tests"])
            self.assertTrue(os.path.isfile(os.path.join(other, "tests", "test_x.py")))

    def test_a_repos_own_install_sh_and_maestro_are_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "install.sh"), "#!/bin/sh\necho our product installer\n")
            _write(os.path.join(tmp, "maestro"), "#!/bin/sh\necho our product cli\n")
            self.install(tmp, "codex")
            self.assertIn("our product installer", _read(os.path.join(tmp, "install.sh.previous")))
            self.assertIn("our product cli", _read(os.path.join(tmp, "maestro.previous")))
            self.assertEqual(_read(os.path.join(tmp, "install.sh")), _read(INSTALL))
            # our own (older) copy is replaced on the next run without a new backup
            _write(os.path.join(tmp, "install.sh"), _read(INSTALL) + "\n# older copy\n")
            os.remove(os.path.join(tmp, "install.sh.previous"))
            self.install(tmp, "codex")
            self.assertFalse(os.path.exists(os.path.join(tmp, "install.sh.previous")))
            self.assertEqual(_read(os.path.join(tmp, "install.sh")), _read(INSTALL))

    def test_retired_names_only_remove_our_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = os.path.join(tmp, ".agents", "skills")
            agents = os.path.join(tmp, ".claude", "agents")
            _write(os.path.join(skills, "plan", "SKILL.md"),
                   "---\nname: plan\ndescription: my team's planning checklist\n---\n")
            _write(os.path.join(skills, "verify", "SKILL.md"),
                   "---\nname: verify\ndescription: Front door for /verify.\ntags: [sdlc, qa]\n---\n")
            _write(os.path.join(skills, "brainstorm", "SKILL.md"),
                   "---\nname: brainstorm\ntags: [sdlc, requirement]\n---\n")
            _write(os.path.join(agents, "go-reviewer.md"),
                   "---\nname: go-reviewer\ntags: [stack:go, reviewer]\n---\n")
            _write(os.path.join(agents, "python-reviewer.md"),
                   "---\nname: python-reviewer\ndescription: our own\n---\n")
            result = self.install(tmp, "codex", "claude-code", "--stack", "react")
            self.assertTrue(os.path.isfile(os.path.join(skills, "plan", "SKILL.md")))
            self.assertFalse(os.path.exists(os.path.join(skills, "verify")))
            self.assertFalse(os.path.exists(os.path.join(skills, "brainstorm")))
            self.assertFalse(os.path.exists(os.path.join(agents, "go-reviewer.md")))
            self.assertTrue(os.path.isfile(os.path.join(agents, "python-reviewer.md")))
            self.assertIn("kept", result.stdout)

    def test_retired_skill_edited_since_install_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = os.path.join(tmp, ".agents", "skills")
            body = "---\nname: plan\ntags: [sdlc, design]\n---\nstock\n"
            _write(os.path.join(skills, "plan", "SKILL.md"), body)
            manifest = os.path.join(tmp, ".maestro", "skill-manifest.json")
            _write(manifest, json.dumps({"hosts": {"codex": {
                "plan": install_skills.tree_hash(os.path.join(skills, "plan"))}}}))
            _write(os.path.join(skills, "plan", "SKILL.md"), body + "our edit\n")
            self.install(tmp, "codex", "--stack", "react")
            self.assertIn("our edit", _read(os.path.join(skills, "plan", "SKILL.md")))
            # an unedited recorded copy goes, even without the pack tag
            _write(os.path.join(skills, "plan", "SKILL.md"), "---\nname: plan\n---\nstock\n")
            _write(manifest, json.dumps({"hosts": {"codex": {
                "plan": install_skills.tree_hash(os.path.join(skills, "plan"))}}}))
            self.install(tmp, "codex", "--stack", "react")
            self.assertFalse(os.path.exists(os.path.join(skills, "plan")))

    def test_reinstall_reuses_the_recorded_stack_unless_told_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.install(tmp, "codex", "--stack", "react")
            record = os.path.join(tmp, ".maestro", "install.json")
            skills = os.path.join(tmp, ".agents", "skills")
            self.assertFalse(os.path.exists(os.path.join(skills, "go-review")))
            self.install(tmp, "codex")                      # no --stack: keep react
            self.assertEqual(json.loads(_read(record))["stacks"], ["react"])
            self.assertFalse(os.path.exists(os.path.join(skills, "go-review")))
            self.install(tmp, "codex", "--stack", "all")    # explicit all: everything
            self.assertEqual(json.loads(_read(record))["stacks"], [])
            self.assertTrue(os.path.isfile(os.path.join(skills, "go-review", "SKILL.md")))
            self.install(tmp, "codex")                      # and stays everything
            self.assertEqual(json.loads(_read(record))["stacks"], [])


class InstallSkillsBackupTest(unittest.TestCase):
    def test_previous_backups_survive_the_next_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src", "demo")
            _write(os.path.join(src, "SKILL.md"), "v1\n")
            dst_root = os.path.join(tmp, "skills")
            manifest = os.path.join(tmp, "manifest.json")
            _write(os.path.join(dst_root, "demo", "SKILL.md"), "user's pre-manifest copy\n")
            report = install_skills.install([src], dst_root, "h", manifest)
            self.assertEqual(report["replaced"], ["demo"])
            backup = os.path.join(dst_root, "demo", "SKILL.md.previous")
            self.assertEqual(_read(backup), "user's pre-manifest copy\n")
            _write(os.path.join(src, "SKILL.md"), "v2\n")
            report = install_skills.install([src], dst_root, "h", manifest)   # stock copy -> updated
            self.assertEqual(report["updated"], ["demo"])
            self.assertEqual(_read(os.path.join(dst_root, "demo", "SKILL.md")), "v2\n")
            self.assertEqual(_read(backup), "user's pre-manifest copy\n")

    def test_a_linked_skill_dir_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src", "demo")
            _write(os.path.join(src, "SKILL.md"), "ours\n")
            template = os.path.join(tmp, "template", "demo")
            _write(os.path.join(template, "SKILL.md"), "template skill\n")
            dst_root = os.path.join(tmp, "skills")
            os.makedirs(dst_root)
            os.symlink(template, os.path.join(dst_root, "demo"))
            install_skills.install([src], dst_root, "h", os.path.join(tmp, "m.json"))
            self.assertEqual(_read(os.path.join(template, "SKILL.md")), "template skill\n")


if __name__ == "__main__":
    unittest.main()
