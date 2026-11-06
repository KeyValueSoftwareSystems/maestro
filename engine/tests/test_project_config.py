"""maestro.config.yaml loading and `preflight` checks against the repos on disk."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import project_config  # noqa: E402

VALID = """\
version: 1
repos:
  backend:
    stack: go
    commands:
      build: make build
      lint: golangci-lint run
      test: go test ./...
      security: gosec ./...
      e2e: make e2e
    timeout_s: 600
environment: {start: docker compose up -d, ready: curl -fsS localhost:8080/health, stop: docker compose down}
delivery: {mode: pull-request, base: main}
custom_value: workflows may read this through config placeholders
"""


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="maestro-config-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo("backend")

    def repo(self, name):
        path = os.path.join(self.root, "codebase", name)
        os.makedirs(path)
        subprocess.run(["git", "init", "-q", path], check=True)

    def write(self, text):
        with open(project_config.config_path(self.root), "w") as fh:
            fh.write(text)

    def codes(self, level):
        return [(i.code, i.where) for i in project_config.preflight(self.root) if i.level == level]

    def test_valid_config_passes(self):
        self.write(VALID)
        self.assertEqual(project_config.preflight(self.root), [])
        config = project_config.load(self.root)
        self.assertEqual(project_config.repo_commands(config, "backend")["test"], "go test ./...")
        self.assertEqual(project_config.repo_timeout(config, "backend"), 600)

    def test_an_environment_without_a_ready_probe_is_a_warning(self):
        self.write(VALID.replace(" ready: curl -fsS localhost:8080/health,", ""))
        self.assertEqual(self.codes("warning"), [("config-missing-command", "environment.ready")])
        self.assertEqual(self.codes("error"), [])

    def test_missing_file_is_an_error(self):
        self.assertEqual(self.codes("error"), [("config-missing", None)])

    def test_init_copies_registry_names_and_does_not_scan_commands(self):
        repo = os.path.join(self.root, "codebase", "backend")
        with open(os.path.join(repo, "go.mod"), "w", encoding="utf-8") as fh:
            fh.write("module example.com/backend\n\ngo 1.22\n")
        with open(os.path.join(self.root, "registry.yaml"), "w", encoding="utf-8") as fh:
            fh.write("repos:\n"
                     "  - name: backend\n    remote: https://example.com/backend.git\n"
                     "  - name: web\n    remote: https://example.com/web.git\n")
        self.assertEqual(project_config.init(self.root), "wrote")
        config = project_config.load(self.root)
        self.assertEqual(set(config["repos"]), {"backend", "web"})
        self.assertEqual(config["repos"]["backend"], {})
        self.assertEqual(project_config.init(self.root), "exists")

    def test_apply_fills_detect_stack_report_without_clobbering(self):
        self.write("version: 1\nrepos:\n  backend:\n    commands:\n      build: make build\n")
        result = project_config.apply_detected(self.root, {"repos": {"backend": {
            "stack": ["db", "go"],
            "commands": {"build": "go build ./...", "test": "go test ./...", "lint": "golangci-lint run"},
        }}})
        config = project_config.load(self.root)
        entry = config["repos"]["backend"]
        self.assertEqual(entry["stack"], "go, db")
        self.assertEqual(entry["commands"]["build"], "make build")
        self.assertEqual(entry["commands"]["test"], "go test ./...")
        self.assertEqual(entry["commands"]["lint"], "golangci-lint run")
        self.assertEqual(result["updated"], ["backend"])
        self.assertFalse(result["created"])

    def test_apply_includes_registry_names_missing_from_the_report(self):
        with open(os.path.join(self.root, "registry.yaml"), "w", encoding="utf-8") as fh:
            fh.write("repos:\n"
                     "  - name: backend\n    remote: https://example.com/backend.git\n"
                     "  - name: web\n    remote: https://example.com/web.git\n")
        project_config.apply_detected(self.root, {"repos": {"backend": {
            "stack": "go", "role": "app",
            "commands": {"build": "go build ./...", "test": "go test ./..."},
        }}})
        config = project_config.load(self.root)
        self.assertEqual(config["repos"]["backend"]["stack"], "go")
        self.assertEqual(config["repos"]["backend"]["role"], "app")
        self.assertEqual(config["repos"]["web"], {})

    def test_init_writes_empty_repos_when_nothing_is_discovered(self):
        empty = tempfile.mkdtemp(prefix="maestro-config-empty-")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(project_config.init(empty), "wrote")
        self.assertEqual(project_config.load(empty), {"version": 1, "repos": {}})

    def test_unparseable_file_is_an_error(self):
        self.write("version: 1\nrepos: &anchor {}\n")
        self.assertEqual(self.codes("error")[0][0], "config-unreadable")

    def test_every_discovered_repo_needs_an_entry(self):
        self.repo("web")
        self.write(VALID)
        self.assertIn(("config-missing-repo", "repos.web"), self.codes("error"))

    def test_build_and_test_are_required_lint_and_e2e_only_warn(self):
        self.write("version: 1\nrepos:\n  backend:\n    commands:\n      build: \"\"\n")
        errors = self.codes("error")
        self.assertIn(("config-missing-command", "repos.backend.commands.build"), errors)
        self.assertIn(("config-missing-command", "repos.backend.commands.test"), errors)
        warnings = self.codes("warning")
        self.assertIn(("config-missing-command", "repos.backend.commands.lint"), warnings)
        self.assertIn(("config-missing-command", "repos.backend.commands.e2e"), warnings)

    def test_typos_inside_known_sections_fail(self):
        self.write(VALID.replace("    stack: go\n", "    stak: go\n")
                   .replace("      lint:", "      lnt:"))
        errors = self.codes("error")
        self.assertIn(("config-unknown-key", "repos.backend.stak"), errors)
        self.assertIn(("config-unknown-key", "repos.backend.commands.lnt"), errors)

    def test_wrong_version_and_bad_values_fail(self):
        self.write(VALID.replace("version: 1", "version: 2")
                   .replace("timeout_s: 600", "timeout_s: -5")
                   .replace("mode: pull-request", "mode: email"))
        errors = {code_where[1] for code_where in self.codes("error")}
        self.assertIn(None, errors)  # version
        self.assertIn("repos.backend.timeout_s", errors)
        self.assertIn("delivery.mode", errors)

    def test_repo_role_and_infrastructure_level(self):
        self.write(VALID.replace("    stack: go\n", "    stack: go\n    role: infra\n")
                   + "infrastructure: {level: iac}\n")
        self.assertEqual(self.codes("error"), [])
        self.write(VALID.replace("    stack: go\n", "    stack: go\n    role: platform\n")
                   + "infrastructure: {level: lots, owner: ops}\n")
        errors = self.codes("error")
        self.assertIn(("config-shape", "repos.backend.role"), errors)
        self.assertIn(("config-shape", "infrastructure.level"), errors)
        self.assertIn(("config-unknown-key", "infrastructure.owner"), errors)

    def test_test_patterns_must_be_a_list_of_patterns(self):
        self.write(VALID.replace("    timeout_s: 600", "    timeout_s: 600\n    test_patterns: tests"))
        self.assertIn(("config-shape", "repos.backend.test_patterns"), self.codes("error"))
        self.write(VALID.replace("    timeout_s: 600", "    timeout_s: 600\n    test_patterns: [\"qa/*\"]"))
        self.assertEqual(self.codes("error"), [])
        config = project_config.load(self.root)
        self.assertEqual(project_config.repo_test_patterns(config, "backend"), ("qa/*",))

    def test_configured_repo_missing_on_disk_only_warns(self):
        ghost = "  ghost:\n    commands: {build: x, test: y, lint: z, e2e: w}\n"
        self.write(VALID.replace("environment:", ghost + "environment:"))
        self.assertIn(("config-unknown-repo", "repos.ghost"), self.codes("warning"))
        self.assertEqual(self.codes("error"), [])

    def test_cli_exit_code_and_json(self):
        maestroctl = os.path.join(HERE, "..", "maestroctl.py")
        proc = subprocess.run([sys.executable, maestroctl, "--root", self.root, "preflight"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["ok"])
        self.write(VALID)
        proc = subprocess.run([sys.executable, maestroctl, "--root", self.root, "preflight"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
