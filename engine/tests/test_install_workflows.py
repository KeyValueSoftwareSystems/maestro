"""Workflow upgrade on re-install: stock copies update, local edits are never overwritten."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))

import install_workflows as iw  # noqa: E402

V1 = "nodes:\n  - id: a\n    instruction: one\n"
V2 = "nodes:\n  - id: a\n    instruction: two\n"
V3 = "nodes:\n  - id: a\n    instruction: three\n"
MINE = "nodes:\n  - id: a\n    instruction: mine\n"


class WorkflowUpgradeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.src = os.path.join(self.tmp, "pack", "workflows")
        self.root = os.path.join(self.tmp, "repo")
        self.dest = os.path.join(self.root, ".maestro", "workflows")
        self.releases = os.path.join(self.tmp, "releases.json")
        os.makedirs(self.src)
        os.makedirs(self.dest)
        self.set_releases({})

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers -------------------------------------------------------------
    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def ship(self, name, text):
        self.write(os.path.join(self.src, name), text)

    def local(self, name, text=None):
        path = os.path.join(self.dest, name)
        if text is None:
            return self.read(path)
        self.write(path, text)
        return path

    def set_releases(self, files):
        hashes = {n: [iw.content_hash(t.encode(), n) for t in texts] for n, texts in files.items()}
        with open(self.releases, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "files": hashes}, fh)

    def install(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = iw.main(["--src", self.src, "--root", self.root,
                            "--releases", self.releases, *extra])
        self.assertEqual(code, 0)
        return buf.getvalue()

    def manifest(self):
        with open(os.path.join(self.root, iw.MANIFEST_REL), encoding="utf-8") as fh:
            return json.load(fh)

    def upstream_path(self, name):
        return os.path.join(self.dest, name + iw.UPSTREAM_SUFFIX)

    # -- cases ---------------------------------------------------------------
    def test_fresh_install_adds_and_writes_manifest(self):
        self.ship("a.yaml", V1)
        out = self.install()
        self.assertEqual(self.local("a.yaml"), V1)
        self.assertIn("added", out)
        manifest = self.manifest()
        self.assertEqual(manifest["files"]["a.yaml"], iw.content_hash(V1.encode(), "a.yaml"))

    def test_untouched_copy_updates_via_manifest(self):
        self.ship("a.yaml", V1)
        self.install()
        self.ship("a.yaml", V2)
        self.install()
        self.assertEqual(self.local("a.yaml"), V2)
        self.assertFalse(os.path.exists(self.upstream_path("a.yaml")))

    def test_edit_is_kept_and_upstream_written_beside_it(self):
        self.ship("a.yaml", V1)
        self.install()
        self.local("a.yaml", MINE)
        self.ship("a.yaml", V2)
        out = self.install()
        self.assertEqual(self.local("a.yaml"), MINE)
        self.assertEqual(self.read(self.upstream_path("a.yaml")), V2)
        self.assertIn("a.yaml.upstream", out)

    def test_edit_kept_silently_when_upstream_unchanged(self):
        self.ship("a.yaml", V1)
        self.install()
        self.local("a.yaml", MINE)
        out = self.install()
        self.assertEqual(self.local("a.yaml"), MINE)
        self.assertFalse(os.path.exists(self.upstream_path("a.yaml")))
        self.assertIn("kept your edits (no upstream change)", out)

    def test_pending_upstream_refreshes_to_latest(self):
        self.ship("a.yaml", V1)
        self.install()
        self.local("a.yaml", MINE)
        self.ship("a.yaml", V2)
        self.install()
        self.ship("a.yaml", V3)
        self.install()
        self.assertEqual(self.local("a.yaml"), MINE)
        self.assertEqual(self.read(self.upstream_path("a.yaml")), V3)

    def test_accepting_upstream_makes_file_auto_update_again(self):
        self.ship("a.yaml", V1)
        self.install()
        self.local("a.yaml", MINE)
        self.ship("a.yaml", V2)
        self.install()
        os.replace(self.upstream_path("a.yaml"), os.path.join(self.dest, "a.yaml"))
        self.ship("a.yaml", V3)
        self.install()
        self.assertEqual(self.local("a.yaml"), V3)

    def test_pre_manifest_stock_copy_recognised_from_releases(self):
        # Installed before the manifest existed: an old stock copy, never edited.
        self.local("a.yaml", V1)
        self.set_releases({"a.yaml": [V1, V2]})
        self.ship("a.yaml", V3)
        self.install()
        self.assertEqual(self.local("a.yaml"), V3)
        self.assertFalse(os.path.exists(self.upstream_path("a.yaml")))

    def test_pre_manifest_edit_is_kept(self):
        self.local("a.yaml", MINE)
        self.set_releases({"a.yaml": [V1]})
        self.ship("a.yaml", V2)
        self.install()
        self.assertEqual(self.local("a.yaml"), MINE)
        self.assertEqual(self.read(self.upstream_path("a.yaml")), V2)

    def test_ignored_upstream_self_heals_for_stock_copy(self):
        # Pre-manifest file wrongly flagged, user ignored the .upstream; still a past
        # release, so the next install replaces it and clears the stale .upstream.
        self.local("a.yaml", V1)
        self.write(self.upstream_path("a.yaml"), V2)
        self.set_releases({"a.yaml": [V1, V2]})
        self.ship("a.yaml", V3)
        self.install()
        self.assertEqual(self.local("a.yaml"), V3)
        self.assertFalse(os.path.exists(self.upstream_path("a.yaml")))

    def test_comment_or_formatting_change_counts_as_edit(self):
        self.ship("a.yaml", V1)
        self.install()
        reformatted = "# my note\nnodes:\n- id: a\n  instruction: 'one'\n"
        self.local("a.yaml", reformatted)
        self.ship("a.yaml", V2)
        self.install()
        self.assertEqual(self.local("a.yaml"), reformatted)
        self.assertEqual(self.read(self.upstream_path("a.yaml")), V2)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".maestro", "backups")))

    def test_crlf_checkout_is_not_an_edit(self):
        self.ship("a.yaml", V1)
        self.install()
        with open(os.path.join(self.dest, "a.yaml"), "wb") as fh:
            fh.write(V1.replace("\n", "\r\n").encode())
        self.ship("a.yaml", V2)
        self.install()
        self.assertEqual(self.local("a.yaml"), V2)

    def test_user_owned_workflow_untouched(self):
        self.ship("a.yaml", V1)
        mine = self.local("my-sdlc.yaml", MINE)
        self.install()
        self.assertEqual(self.read(mine), MINE)
        manifest = self.manifest()
        self.assertNotIn("my-sdlc.yaml", manifest["files"])

    def test_retired_upstream_file_reported_not_deleted(self):
        self.ship("a.yaml", V1)
        self.ship("old.yaml", V1)
        self.install()
        os.remove(os.path.join(self.src, "old.yaml"))
        out = self.install()
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "old.yaml")))
        self.assertIn("old.yaml", out)
        self.assertIn("no longer shipped", out)

    def test_dry_run_writes_nothing(self):
        self.ship("a.yaml", V1)
        self.install()
        self.local("a.yaml", MINE)
        self.ship("a.yaml", V2)
        self.ship("b.yaml", V1)
        out = self.install("--dry-run")
        self.assertIn("dry run", out)
        self.assertIn("upstream changed", out)
        self.assertEqual(self.local("a.yaml"), MINE)
        self.assertFalse(os.path.exists(self.upstream_path("a.yaml")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "b.yaml")))

    def test_invalid_workflow_reported_after_install(self):
        self.ship("a.yaml", "nodes:\n  - id: a\n    type: gate\n")
        out = self.install()
        self.assertIn("fails validation", out)


class InstallerWorkflowUpgradeTest(unittest.TestCase):
    """End to end through install.sh, using this checkout as the pack."""

    def install(self, dest, *args):
        env = dict(os.environ, DEST=dest)
        return subprocess.run(["bash", os.path.join(ROOT, "install.sh"), "codex", *args],
                              cwd=dest, env=env, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def test_reinstall_keeps_edited_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.install(tmp)
            path = os.path.join(tmp, ".maestro", "workflows", "sdlc-main.yaml")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("  - id: my_extra\n    instruction: mine\n")
            with open(path, encoding="utf-8") as fh:
                edited = fh.read()

            self.install(tmp)

            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), edited)
            self.assertTrue(os.path.isfile(os.path.join(tmp, iw.MANIFEST_REL)))

    def test_dry_run_installs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.install(tmp, "--dry-run")
            self.assertIn("dry run", out)
            self.assertEqual(os.listdir(tmp), [])


class ReleaseListTest(unittest.TestCase):
    def test_release_list_covers_current_workflows(self):
        with open(iw.RELEASES, encoding="utf-8") as fh:
            known = json.load(fh)["files"]
        src = os.path.join(ROOT, "workflows")
        for name in os.listdir(src):
            with open(os.path.join(src, name), "rb") as fh:
                digest = iw.content_hash(fh.read(), name)
            self.assertIn(digest, known.get(name, []),
                          f"{name} missing from workflow_releases.json — "
                          "run: python3 scripts/gen_workflow_releases.py")

    def test_release_list_covers_history(self):
        if not os.path.exists(os.path.join(ROOT, ".git")):
            self.skipTest("not a git checkout")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts",
                               "gen_workflow_releases.py"), "--check"],
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
