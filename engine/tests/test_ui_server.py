"""ui_server endpoint + security tests.

Boots the real ThreadingHTTPServer on an ephemeral port against a temp repo and drives
every endpoint over HTTP. Guards the path-traversal rejections and the workflow-subset
validation on PUT — a server that serves /etc/passwd or writes junk is a regression.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import state as statemod  # noqa: E402
import ui_server  # noqa: E402
import wf as wfmod  # noqa: E402

WF = """\
version: 1
name: demo-flow
nodes:
  - id: plan
    type: agent
    instruction: Plan it.
"""


class UiServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "workflows"))
        with open(os.path.join(self.tmp, "workflows", "demo.yaml"), "w") as fh:
            fh.write(WF)
        # a builder file to serve at GET /
        self.builder = os.path.join(self.tmp, "builder.html")
        with open(self.builder, "w") as fh:
            fh.write("<!doctype html><title>b</title>")
        # a real run ledger under .maestro/<slug>/state.yaml
        st = statemod.new_state("my-feat", "workflows/demo.yaml", "abc", {})
        st["steps"]["plan"] = {"status": "done", "visits": 1, "outputs": {}}
        os.makedirs(os.path.join(self.tmp, ".maestro", "my-feat"))
        wfmod.dump_file(os.path.join(self.tmp, ".maestro", "my-feat", "state.yaml"), st)
        # a stray non-slug / non-run dir that must be ignored
        os.makedirs(os.path.join(self.tmp, ".maestro", "Bad Name"))

        ui_server.Handler.ROOT = os.path.abspath(self.tmp)
        ui_server.Handler.BUILDER = self.builder
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path):
        with urllib.request.urlopen(self._url(path)) as r:
            return r.status, r.read()

    def _get_json(self, path):
        code, body = self._get(path)
        return code, json.loads(body)

    def _req(self, method, path, body=None):
        data = body.encode() if isinstance(body, str) else body
        req = urllib.request.Request(self._url(path), data=data, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    # -- tests ------------------------------------------------------------
    def test_health(self):
        code, obj = self._get_json("/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(obj["ok"])
        self.assertEqual(obj["root"], os.path.abspath(self.tmp))

    def test_index_serves_builder(self):
        code, body = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<!doctype html>", body)

    def test_workflows_list(self):
        # seed a non-workflow yaml and a workflow outside workflows/ to exercise the scan
        with open(os.path.join(self.tmp, "config.yaml"), "w") as fh:
            fh.write("a: 1\nb: 2\n")
        os.makedirs(os.path.join(self.tmp, "extra"))
        with open(os.path.join(self.tmp, "extra", "other.yaml"), "w") as fh:
            fh.write(WF)
        code, obj = self._get_json("/api/workflows")
        self.assertEqual(code, 200)
        by_file = {e["file"]: e for e in obj}
        # recursive relative paths, workflows tagged
        self.assertIn(os.path.join("workflows", "demo.yaml"), by_file)
        self.assertTrue(by_file[os.path.join("workflows", "demo.yaml")]["workflow"])
        self.assertEqual(by_file[os.path.join("workflows", "demo.yaml")]["name"], "demo-flow")
        self.assertTrue(by_file[os.path.join("extra", "other.yaml")]["workflow"])
        # non-workflow yaml is listed but tagged workflow: false
        self.assertIn("config.yaml", by_file)
        self.assertFalse(by_file["config.yaml"]["workflow"])
        # workflows sort before non-workflows
        self.assertTrue(obj[0]["workflow"])

    def test_workflow_read(self):
        code, body = self._get("/api/workflow?file=workflows/demo.yaml")
        self.assertEqual(code, 200)
        self.assertEqual(body.decode(), WF)

    def test_workflow_put_roundtrip(self):
        new = "version: 1\nname: edited\nnodes:\n  - id: a\n    instruction: go\n"
        code, _ = self._req("PUT", "/api/workflow?file=workflows/demo.yaml", new)
        self.assertEqual(code, 200)
        code, body = self._get("/api/workflow?file=workflows/demo.yaml")
        self.assertEqual(body.decode(), new)

    def test_workflow_put_new_nested_file(self):
        # write anywhere under root (yaml only), creating dirs as needed
        code, _ = self._req("PUT", "/api/workflow?file=sub/dir/fresh.yaml", WF)
        self.assertEqual(code, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "sub", "dir", "fresh.yaml")))

    def test_put_into_maestro_rejected(self):
        code, _ = self._req("PUT", "/api/workflow?file=.maestro/my-feat/x.yaml", WF)
        self.assertIn(code, (400, 404))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, ".maestro", "my-feat", "x.yaml")))

    def test_runs_list(self):
        code, obj = self._get_json("/api/runs")
        self.assertEqual(code, 200)
        self.assertEqual(len(obj), 1)
        self.assertEqual(obj[0]["slug"], "my-feat")
        self.assertIn("run", obj[0]["state"])

    def test_traversal_get_rejected(self):
        for evil in ("../../etc/passwd", "/etc/passwd", "../state.py", "..%2f..%2fx"):
            code, _ = self._req("GET", "/api/workflow?file=" + evil)
            self.assertIn(code, (400, 404), f"{evil} not rejected")

    def test_traversal_put_rejected(self):
        code, _ = self._req("PUT", "/api/workflow?file=../evil.yaml", "version: 1\n")
        self.assertIn(code, (400, 404))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, "evil.yaml")))

    def test_put_non_yaml_suffix_rejected(self):
        code, _ = self._req("PUT", "/api/workflow?file=demo.txt", "hello")
        self.assertIn(code, (400, 404))

    def test_put_invalid_subset_rejected(self):
        # a YAML anchor is outside wf.py's accepted subset -> 400
        code, _ = self._req("PUT", "/api/workflow?file=demo.yaml", "a: &x 1\nb: *x\n")
        self.assertEqual(code, 400)

    def test_unknown_path_404(self):
        code, _ = self._req("GET", "/api/nope")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
