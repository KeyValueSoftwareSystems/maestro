"""stack_skills: a repository's configured stack selects the installed skills tagged for it."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stack_skills  # noqa: E402


class StackSkillsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="stack-skills-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.skill(".claude/skills", "golang-patterns", "[stack:go, patterns]")
        self.skill(".claude/skills", "golang-testing", "[stack:go, testing]")
        self.skill(".agents/skills", "postgres-patterns", "[stack:db, patterns]")
        self.skill(".claude/skills", "react-patterns", "[stack:react]")
        self.skill(".claude/skills", "prd-writing", "[sdlc, requirement]")
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos:\n  api: {stack: \"go, db\"}\n  web: {stack: react}\n"
                     "  docs: {}\n")

    def skill(self, host, name, tags):
        path = os.path.join(self.root, host, name)
        os.makedirs(path)
        with open(os.path.join(path, "SKILL.md"), "w") as fh:
            fh.write(f"---\nname: {name}\ndescription: x\ntags: {tags}\n---\n\n# {name}\n")

    def test_repository_stacks_select_tagged_skills_across_hosts(self):
        self.assertEqual(stack_skills.for_repo(self.root, "api"),
                         (["go", "db"], ["golang-patterns", "golang-testing", "postgres-patterns"]))
        self.assertEqual(stack_skills.for_repo(self.root, "web"), (["react"], ["react-patterns"]))

    def test_no_stack_selects_nothing(self):
        self.assertEqual(stack_skills.for_repo(self.root, "docs"), ([], []))
        self.assertEqual(stack_skills.for_repo(self.root, "unknown"), ([], []))


if __name__ == "__main__":
    unittest.main()
