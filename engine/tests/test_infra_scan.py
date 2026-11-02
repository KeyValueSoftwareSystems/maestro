"""infra_scan: the workspace's infrastructure level decides which HLD infrastructure questions
are relevant at all."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import infra_scan  # noqa: E402

DEPLOYMENT = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n"


class InfraScanTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="infra-scan-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for repo in ("api", "web"):
            self.write(f"codebase/{repo}/README.md", "app\n")
            subprocess.run(["git", "init", "-q", os.path.join(self.root, "codebase", repo)],
                           check=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def scan(self, out=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(infra_scan.main(["--root", self.root]
                                             + (["--out", out] if out else [])), 0)
        return json.loads(buf.getvalue())

    def test_application_code_only_means_no_infrastructure_questions(self):
        self.write("codebase/api/src/app.py", "print('hi')\n")
        self.write("codebase/web/node_modules/pkg/Dockerfile", "FROM node\n")  # vendored: ignored
        result = self.scan()
        self.assertEqual((result["level"], result["platforms_csv"]), ("none", ""))
        self.assertIn("ask no infrastructure questions", result["summary"])

    def test_containers_only(self):
        self.write("codebase/api/Dockerfile", "FROM python:3.12\n")
        self.write("docker-compose.yml", "services: {}\n")  # umbrella root counts too
        result = self.scan()
        self.assertEqual(result["level"], "containers")
        self.assertEqual(result["container_repos_csv"], "api,(workspace root)")
        self.assertIn("only the runtime and configuration questions", result["summary"])

    def test_infrastructure_as_code_anywhere_in_the_workspace(self):
        self.write("codebase/web/Dockerfile", "FROM node\n")
        self.write("codebase/api/deploy/k8s/api.yaml", DEPLOYMENT)
        self.write("codebase/api/config/settings.yaml", "kind: Settings\n")  # not a manifest
        self.write("codebase/infra/envs/prod/main.tf", 'resource "aws_sqs_queue" "q" {}\n')
        subprocess.run(["git", "init", "-q", os.path.join(self.root, "codebase", "infra")], check=True)
        result = self.scan(out=".maestro/runs/demo/infra-profile.json")
        self.assertEqual(result["level"], "iac")
        self.assertEqual(result["iac_repos_csv"], "api,infra")
        self.assertEqual(result["platforms_csv"], "docker,kubernetes,terraform")
        self.assertIn("every material infrastructure decision", result["summary"])
        with open(os.path.join(self.root, result["profile_path"])) as fh:
            repos = {r["repo"]: r for r in json.load(fh)["repos"]}
        self.assertEqual(repos["api"]["evidence"]["kubernetes"], ["deploy/k8s/api.yaml"])
        self.assertEqual(repos["infra"]["role"], "infra")

    def test_config_overrides_level_and_role(self):
        self.write("codebase/infra/main.tf", "\n")
        subprocess.run(["git", "init", "-q", os.path.join(self.root, "codebase", "infra")], check=True)
        self.write("maestro.config.yaml", "version: 1\nrepos:\n  web: {role: infra}\n"
                                          "infrastructure: {level: none}\n")
        result = self.scan()
        self.assertEqual(result["level"], "none")  # another team owns the infrastructure
        self.assertIn("(set in maestro.config.yaml)", result["summary"])
        self.write("maestro.config.yaml", "version: 1\nrepos:\n  web: {role: infra}\n")
        self.assertIn("web", self.scan()["iac_repos_csv"].split(","))


if __name__ == "__main__":
    unittest.main()
