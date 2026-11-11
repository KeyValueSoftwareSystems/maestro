"""e2e_check: a proposed E2E suite is recorded only when its list mode shows specs or the
command is wired up in a cited file; everything else is `none` with the reason."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import e2e_check  # noqa: E402


class CountSpecsTest(unittest.TestCase):
    def test_known_summaries_and_listings(self):
        self.assertEqual(e2e_check.count_specs("Listing tests:\n  [chromium] a.spec.ts\nTotal: 12 tests in 4 files\n"), 12)
        self.assertEqual(e2e_check.count_specs("Total: 0 tests in 0 files"), 0)
        self.assertEqual(e2e_check.count_specs("3 tests collected in 0.1s"), 3)
        self.assertEqual(e2e_check.count_specs("No tests found, exiting with code 1"), 0)
        self.assertEqual(e2e_check.count_specs("/r/e2e/login.spec.ts\n/r/e2e/cart.cy.js\n"), 2)
        self.assertEqual(e2e_check.count_specs("TestCheckout\nTestLogin\nok  \tx/e2e\t0.01s\n"), 2)
        self.assertIsNone(e2e_check.count_specs("Done in 0.2s\n"))
        self.assertIsNone(e2e_check.count_specs("Tests\nTesting the suite\n"))


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="e2e-check-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.log = os.path.join(self.repo, ".log", "web.log")

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def verify(self, **proposal):
        return e2e_check.verify(self.repo, proposal, self.log)

    def test_no_command_is_none_with_the_reason(self):
        self.assertEqual(self.verify(command=None, reason="no framework found"),
                         {"status": "none", "reason": "no framework found"})

    def test_list_mode_with_specs_confirms(self):
        result = self.verify(command="npx playwright test", framework="playwright",
                             list="echo 'Total: 5 tests in 2 files'")
        self.assertEqual(result, {"status": "verified", "command": "npx playwright test",
                                  "framework": "playwright", "method": "list", "specs": 5})

    def test_list_mode_with_zero_specs_is_none_even_with_evidence(self):
        self.write("package.json", json.dumps({"scripts": {"e2e": "playwright test"}}))
        result = self.verify(command="npm run e2e", list="echo 'Total: 0 tests in 0 files'",
                             evidence=["package.json"])
        self.assertEqual(result["status"], "none")
        self.assertIn("lists no specs", result["reason"])

    def test_list_that_cannot_run_falls_back_to_a_defined_script(self):
        self.write("package.json", json.dumps({"scripts": {"test:e2e": "cypress run"}}))
        result = self.verify(command="npm run test:e2e", list="exit 1", evidence=["package.json"])
        self.assertEqual((result["status"], result["method"], result["evidence"]),
                         ("verified", "evidence", "package.json"))

    def test_a_failing_list_that_reports_no_tests_is_none_despite_a_script(self):
        self.write("package.json", json.dumps({"scripts": {"test:e2e": "playwright test"}}))
        result = self.verify(command="npm run test:e2e", evidence=["package.json"],
                             list="echo 'Error: No tests found'; exit 1")
        self.assertEqual(result["status"], "none")

    def test_comments_configs_and_longer_commands_are_not_wiring(self):
        self.write("playwright.config.ts", "// run: npx playwright test\nexport default {}\n")
        self.assertEqual(self.verify(command="npx playwright test",
                                     evidence=["playwright.config.ts"])["status"], "none")
        self.write(".github/workflows/ci.yml", "steps:\n  # make e2e\n  - run: make e2e-smoke\n")
        self.assertEqual(self.verify(command="make e2e",
                                     evidence=[".github/workflows/ci.yml"])["status"], "none")

    def test_make_directory_flag_is_not_the_target(self):
        self.write("web/Makefile", "e2e:\n\tnpx playwright test\n")
        self.assertEqual(self.verify(command="make -C web e2e",
                                     evidence=["web/Makefile"])["status"], "verified")

    def test_make_target_and_ci_file_count_as_wiring(self):
        self.write("Makefile", "build:\n\tgo build ./...\ne2e:\n\tgo test -tags e2e ./e2e/...\n")
        self.assertEqual(self.verify(command="make e2e", evidence=["Makefile"])["status"], "verified")
        self.write(".github/workflows/e2e.yml", "steps:\n  - run: ./gradlew connectedCheck\n")
        result = self.verify(command="./gradlew connectedCheck",
                             evidence=["build.gradle", ".github/workflows/e2e.yml"])
        self.assertEqual(result["evidence"], ".github/workflows/e2e.yml")

    def test_a_config_file_alone_or_a_missing_script_is_none(self):
        self.write("playwright.config.ts", "export default {}\n")
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        result = self.verify(command="npm run e2e", evidence=["playwright.config.ts", "package.json"])
        self.assertEqual(result["status"], "none")
        self.assertIn("not run or defined", result["reason"])

    def test_evidence_outside_the_repo_is_ignored(self):
        outside = tempfile.mkdtemp(prefix="e2e-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with open(os.path.join(outside, "ci.yml"), "w") as fh:
            fh.write("run: make e2e\n")
        rel = os.path.relpath(os.path.join(outside, "ci.yml"), self.repo)
        self.assertEqual(self.verify(command="make e2e", evidence=[rel])["status"], "none")


if __name__ == "__main__":
    unittest.main()
