"""domain_rules: optional rules and change scenarios people write, checked against the code."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import domain_rules  # noqa: E402

PAGE = """# Payments: Functional

## What it does
Collects fees.

## Rules that must never break
- INV-PL-01 One active link per invoice.
- INV-PL-02 Amounts are integer paise, never floats.

## If you change… also check
| ID | Change | Also check |
|----|--------|-----------|
| CS-PL-01 | Disabling a link | Reminders, late webhooks |
"""

SCENARIOS = """version: 1
scenarios:
  - id: CS-PL-01
    domain: payments
    summary: Disabling a payment link
    rules: [INV-PL-01]
    repo: backend
    when_changing:
      - links/disable.go
      - Service.Disable
    also_impacts:
      domains: [payments]
      tables: [payment_links]
      endpoints: ["GET /v1/links/{id}"]
      files:
        - web:src/Links.tsx
    verify: [TestWebhookAfterDisable]
"""

BACKEND = {
    "links/disable.go": (
        'package links\n\n// INV-PL-01: one active link per invoice\n'
        'func (s *Service) Disable(id string) error { return s.db.Exec("UPDATE payment_links") }\n'),
    "links/amount.go": "package links\n\n// INV-PL-02: paise, never float\ntype Paise int64\n",
    "links/routes.go": 'package links\n\nvar r = route("/v1", "links")\n',
    "links/disable_test.go": "package links\n\nfunc TestWebhookAfterDisable(t *T) {}\n",
}
WEB = {"src/Links.tsx": "export const Links = () => null;\n"}


class DomainRulesTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="domain-rules-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo("backend", BACKEND)
        self.repo("web", WEB)

    def repo(self, name, files):
        path = os.path.join(self.root, "codebase", name)
        os.makedirs(path, exist_ok=True)
        subprocess.run(["git", "init", "-q", path], check=True)
        for rel, text in files.items():
            self.write(os.path.join("codebase", name, rel), text)
        return path

    def write(self, rel, text):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    def with_rules(self):
        self.write("docs/functional/payments.md", PAGE)
        self.write("docs/impact/side-effects.yaml", SCENARIOS)

    # ---------------------------------------------------------------- optional

    def test_no_rules_is_skipped_not_failed(self):
        self.write("docs/functional/payments.md", "# Payments\n\n## Business rules\n- none\n")
        self.assertFalse(domain_rules.status(self.root)["present"])
        result = domain_rules.check(self.root)
        self.assertEqual((result["present"], result["valid"], result["skipped"]), (False, True, True))

    def test_scaffold_writes_an_empty_starter_once(self):
        first = domain_rules.scaffold(self.root)
        self.assertTrue(first["created"])
        self.assertFalse(domain_rules.status(self.root)["present"])  # comments + empty list only
        self.assertTrue(domain_rules.check(self.root)["valid"])
        self.write("docs/impact/side-effects.yaml", "scenarios: []\n# mine\n")
        self.assertFalse(domain_rules.scaffold(self.root)["created"])
        with open(os.path.join(self.root, "docs/impact/side-effects.yaml")) as fh:
            self.assertIn("# mine", fh.read())

    # ---------------------------------------------------------------- matching code

    def test_rules_that_match_the_code_pass(self):
        self.with_rules()
        status = domain_rules.status(self.root)
        self.assertEqual((status["present"], status["rule_count"], status["scenario_count"]), (True, 2, 1))
        result = domain_rules.check(self.root)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["warnings"], [])

    def test_renamed_symbol_file_table_endpoint_and_test_fail(self):
        self.with_rules()
        backend = os.path.join(self.root, "codebase", "backend")
        os.remove(os.path.join(backend, "links/routes.go"))
        os.remove(os.path.join(backend, "links/disable_test.go"))
        self.write("codebase/backend/links/disable.go",
                   "package links\n// INV-PL-01\nfunc (s *Service) Revoke() { s.db.Exec(\"x\") }\n")
        os.remove(os.path.join(self.root, "codebase/web/src/Links.tsx"))
        errors = " | ".join(domain_rules.check(self.root)["errors"])
        for needle in ("'Service.Disable'", "table 'payment_links'", "endpoint 'GET /v1/links/{id}'",
                       "test 'TestWebhookAfterDisable'", "file 'src/Links.tsx' no longer exists in web"):
            self.assertIn(needle, errors)

    def test_rule_not_cited_in_code_fails_and_markdown_does_not_count(self):
        self.with_rules()
        self.write("codebase/backend/links/amount.go", "package links\ntype Paise int64\n")
        self.write("codebase/backend/links/CLAUDE.md", "- INV-PL-02 paise\n")
        result = domain_rules.check(self.root)
        self.assertFalse(result["valid"])
        self.assertTrue(any("INV-PL-02 is not cited" in e for e in result["errors"]))

    def test_code_citing_an_undefined_id_fails(self):
        self.with_rules()
        self.write("codebase/backend/links/old.go", "package links\n// INV-PL-09 removed rule\n")
        errors = domain_rules.check(self.root)["errors"]
        self.assertTrue(any("INV-PL-09 is cited in backend:links/old.go" in e for e in errors))

    def test_scenario_citing_an_undefined_rule_fails(self):
        self.with_rules()
        self.write("docs/impact/side-effects.yaml", SCENARIOS.replace("[INV-PL-01]", "[INV-PL-07]"))
        errors = domain_rules.check(self.root)["errors"]
        self.assertTrue(any("cites rule INV-PL-07" in e for e in errors))

    def test_page_and_yaml_out_of_step_only_warns(self):
        self.with_rules()
        self.write("docs/functional/payments.md", PAGE.replace("| CS-PL-01 |", "| CS-PL-02 |"))
        result = domain_rules.check(self.root)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["warning_count"], 2)

    def test_malformed_and_mixed_domain_codes_fail(self):
        self.with_rules()
        self.write("docs/functional/payments.md",
                   PAGE.replace("- INV-PL-02 Amounts", "- INV-PAY-2 Amounts").replace(
                       "| CS-PL-01 |", "| CS-PY-01 |"))
        errors = " | ".join(domain_rules.check(self.root)["errors"])
        self.assertIn("malformed rule line", errors)
        self.assertIn("more than one domain code", errors)

    # ---------------------------------------------------------------- feature worktree

    def test_worktree_replaces_the_repository_checkout(self):
        self.with_rules()
        wt = tempfile.mkdtemp(prefix="wt-")
        self.addCleanup(shutil.rmtree, wt, ignore_errors=True)
        for rel, text in BACKEND.items():
            if rel != "links/amount.go":  # the feature dropped the rule's citation
                os.makedirs(os.path.dirname(os.path.join(wt, rel)), exist_ok=True)
                with open(os.path.join(wt, rel), "w") as fh:
                    fh.write(text)
        self.assertTrue(domain_rules.check(self.root)["valid"])
        result = domain_rules.check(self.root, repo="backend", worktree=wt)
        self.assertFalse(result["valid"])
        self.assertIn("INV-PL-02", result["issues_summary"])

    # ---------------------------------------------------------------- CLI

    def cli(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "domain_rules.py")
        proc = subprocess.run([sys.executable, script, *args, "--root", self.root],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def test_cli_prints_one_json_line_and_exits_zero_even_when_invalid(self):
        self.with_rules()
        self.write("codebase/backend/links/old.go", "// INV-PL-09\n")
        out = os.path.join(self.root, "report.json")
        code, stdout, _ = self.cli("check", "--out", out)
        line = json.loads(stdout)
        self.assertEqual((code, line["valid"], line["report_path"]), (0, False, out))
        self.assertNotIn("errors", line)
        with open(out) as fh:
            self.assertTrue(json.load(fh)["errors"])

    def test_cli_missing_worktree_falls_back_to_the_checkout(self):
        self.with_rules()
        code, stdout, _ = self.cli("check", "--repo", "backend", "--worktree", "/nonexistent/wt")
        self.assertEqual((code, json.loads(stdout)["valid"]), (0, True))

    def test_next_numbers_rules_and_scenarios_separately(self):
        self.with_rules()
        self.assertEqual(domain_rules.next_ids(self.root, "PL"),
                         {"rule": "INV-PL-03", "scenario": "CS-PL-02"})
        self.assertEqual(domain_rules.next_ids(self.root, "AU"),
                         {"rule": "INV-AU-01", "scenario": "CS-AU-01"})


if __name__ == "__main__":
    unittest.main()
