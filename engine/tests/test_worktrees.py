"""The engine creates each feature's worktrees (its own, or the project's sandbox command), uses
only worktrees it created, and removes only those."""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import implementation_pool as pool  # noqa: E402
import project_config  # noqa: E402
import resolver  # noqa: E402
import state as statemod  # noqa: E402
import worktrees  # noqa: E402

SLUG = "fee-groups"

# A stand-in for the workspace template's sandbox script: one worktree per repository under
# sandbox/<slug>/codebase/<repo>, all on branch sandbox/<slug>; `rm` removes them and the branch.
SANDBOX = """#!/bin/sh
set -e
cmd="$1"; slug="$2"
for repo in codebase/*/; do
  name=$(basename "$repo")
  if [ "$cmd" = create ]; then
    git -C "$repo" worktree add -q -b "sandbox/$slug" "$PWD/sandbox/$slug/codebase/$name" HEAD
  else
    git -C "$repo" worktree remove "$PWD/sandbox/$slug/codebase/$name"
    git -C "$repo" branch -D "sandbox/$slug" >/dev/null
  fi
done
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def call(module, *argv):
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = module.main(list(argv))
    out = buf.getvalue().strip()
    return code, json.loads(out) if code == 0 and out else (out or err.getvalue())


class WorktreesTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="worktrees-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repos = {}
        for name in ("cofee-backend", "cofee-admin-app"):
            repo = os.path.join(self.root, "codebase", name)
            os.makedirs(repo)
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "T")
            with open(os.path.join(repo, "README.md"), "w") as fh:
                fh.write("one\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-q", "-m", "one")
            self.repos[name] = repo
        self.run_dir = statemod.feature_dir(SLUG, self.root)
        os.makedirs(os.path.join(self.run_dir, ".engine"))
        os.makedirs(os.path.join(self.run_dir, "release"))
        with open(os.path.join(self.run_dir, ".engine", "lld-scope.json"), "w") as fh:
            json.dump({"selected": list(self.repos)}, fh)
        self.assertEqual(call(pool, "init", "--root", self.root, "--slug", SLUG,
                              "--choice", "all", "--fresh")[0], 0)

    def pin(self):
        repos = [{"name": n, "path": os.path.relpath(p, self.root), "commit": git(p, "rev-parse", "HEAD")}
                 for n, p in self.repos.items()]
        with open(os.path.join(self.run_dir, ".engine", "workspace-lock.json"), "w") as fh:
            json.dump({"schema_version": 1, "repos": repos}, fh)
        return {r["name"]: r["commit"] for r in repos}

    def configure_sandbox(self, remove=True):
        scripts = os.path.join(self.root, "scripts")
        os.makedirs(scripts, exist_ok=True)
        script = os.path.join(scripts, "sandbox")
        with open(script, "w") as fh:
            fh.write(SANDBOX)
        os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
        section = ("worktree:\n  create: ./scripts/sandbox create {slug}\n"
                   "  path: sandbox/{slug}/codebase/{repo}\n  branch: sandbox/{slug}\n")
        if remove:
            section += "  remove: ./scripts/sandbox rm {slug}\n"
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\n" + section)

    def prepare(self):
        return call(worktrees, "prepare", "--root", self.root, "--slug", SLUG)

    def remove(self):
        return call(worktrees, "remove", "--root", self.root, "--slug", SLUG)

    def deliver(self, pushed):
        with open(os.path.join(self.run_dir, "release", "delivery.json"), "w") as fh:
            json.dump({"repositories": [{"repo": n, "pushed": pushed} for n in self.repos]}, fh)

    # --- the engine's own worktrees -------------------------------------------------------

    def stray_file_hook(self, repo):
        """A post-checkout hook that dirties every new worktree while `.git/hookon` exists."""
        hook = os.path.join(repo, ".git", "hooks", "post-checkout")
        with open(hook, "w") as fh:
            fh.write('#!/bin/sh\n[ -e "$(git rev-parse --git-common-dir)/hookon" ] && touch stray.txt\nexit 0\n')
        os.chmod(hook, 0o755)
        marker = os.path.join(repo, ".git", "hookon")
        open(marker, "w").close()
        return marker

    def test_a_failed_prepare_removes_what_it_made_so_the_retry_works(self):
        self.pin()
        backend = self.repos["cofee-backend"]
        marker = self.stray_file_hook(backend)
        code, out = self.prepare()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", out)
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        branch = f"feature/{SLUG}-cofee-backend"
        self.assertFalse(os.path.exists(path))                       # no worktree left behind
        self.assertEqual(git(backend, "branch", "--list", branch), "")  # nor its branch
        self.assertNotIn(os.path.realpath(path), worktrees._registered(backend))
        entries = (worktrees.load_record(self.root, SLUG) or {}).get("repos") or {}
        self.assertNotIn("cofee-backend", entries)
        os.remove(marker)
        code, out = self.prepare()                                   # the retry is not blocked
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out["created_csv"].split(",")), set(self.repos))

    def test_a_prepare_that_died_midway_is_cleaned_up_by_the_retry(self):
        self.pin()
        backend = self.repos["cofee-backend"]
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        branch = f"feature/{SLUG}-cofee-backend"
        # what a killed run leaves: the worktree and branch exist, the record says "pending"
        os.makedirs(os.path.dirname(path))
        git(backend, "worktree", "add", "-q", "-b", branch, path)
        worktrees._save_record(self.root, SLUG, {
            "schema_version": 1, "slug": SLUG, "mode": "default",
            "repos": {"cofee-backend": {"path": path, "branch": branch,
                                        "created_by_maestro": True, "pending": True}}})
        code, out = self.prepare()
        self.assertEqual(code, 0, out)
        self.assertIn("cofee-backend", out["created_csv"].split(","))
        entry = worktrees.load_record(self.root, SLUG)["repos"]["cofee-backend"]
        self.assertNotIn("pending", entry)
        self.assertEqual(entry["base_commit"], git(path, "rev-parse", "HEAD"))

    def test_default_creates_at_the_pinned_commit_and_claim_hands_it_out(self):
        pins = self.pin()
        # main moves on after the pin: the worktree must still start at the pinned commit
        backend = self.repos["cofee-backend"]
        with open(os.path.join(backend, "README.md"), "a") as fh:
            fh.write("two\n")
        git(backend, "commit", "-qam", "two")
        code, out = self.prepare()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["mode"], "default")
        self.assertEqual(set(out["created_csv"].split(",")), set(self.repos))
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        self.assertEqual(git(path, "rev-parse", "HEAD"), pins["cofee-backend"])
        self.assertEqual(git(path, "branch", "--show-current"), f"feature/{SLUG}-cofee-backend")
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".maestro", "worktrees", ".gitignore")))

        code, claim = call(pool, "claim", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0)
        self.assertEqual(claim["worktree"],
                         os.path.join(self.root, ".maestro", "worktrees", SLUG, claim["repo"]))
        self.assertEqual(claim["branch"], f"feature/{SLUG}-{claim['repo']}")

        code, again = self.prepare()  # resume or a later delivery pass
        self.assertEqual(code, 0)
        self.assertEqual(again["created_csv"], "")
        self.assertEqual(set(again["reused_csv"].split(",")), set(self.repos))

    def test_default_refuses_a_path_or_branch_it_did_not_create(self):
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        os.makedirs(path)
        code, err = self.prepare()
        self.assertEqual(code, 1)
        os.rmdir(path)
        git(self.repos["cofee-backend"], "branch", f"feature/{SLUG}-cofee-backend")
        code, err = self.prepare()
        self.assertEqual(code, 1)

    def test_default_restores_its_own_worktree_deleted_by_hand(self):
        self.assertEqual(self.prepare()[0], 0)
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        shutil.rmtree(path)
        code, out = self.prepare()
        self.assertEqual(code, 0, out)
        self.assertIn("cofee-backend", out["reused_csv"])
        self.assertEqual(git(path, "branch", "--show-current"), f"feature/{SLUG}-cofee-backend")

    def test_default_remove_keeps_the_branch_and_any_dirty_worktree(self):
        self.assertEqual(self.prepare()[0], 0)
        path = os.path.join(self.root, ".maestro", "worktrees", SLUG, "cofee-backend")
        with open(os.path.join(path, "scratch.txt"), "w") as fh:
            fh.write("unsaved\n")
        _, kept = self.remove()
        self.assertFalse(kept["removed"])
        self.assertTrue(os.path.isdir(path))
        os.remove(os.path.join(path, "scratch.txt"))
        _, out = self.remove()
        self.assertTrue(out["removed"], out)
        self.assertFalse(os.path.exists(path))
        git(self.repos["cofee-backend"], "rev-parse", "--verify", f"feature/{SLUG}-cofee-backend")
        self.assertTrue(self.remove()[1]["removed"])  # idempotent

    # --- the project's sandbox command ----------------------------------------------------

    def test_configured_sandbox_is_created_once_and_used(self):
        self.configure_sandbox()
        self.pin()
        code, out = self.prepare()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["mode"], "configured")
        _, claim = call(pool, "claim", "--root", self.root, "--slug", SLUG)
        self.assertEqual(claim["worktree"],
                         os.path.join(self.root, "sandbox", SLUG, "codebase", claim["repo"]))
        self.assertEqual(claim["branch"], f"sandbox/{SLUG}")
        code, again = self.prepare()  # running create twice would fail: the record prevents it
        self.assertEqual(code, 0, again)
        self.assertEqual(again["created_csv"], "")

    def test_configured_refuses_a_sandbox_that_already_exists(self):
        self.configure_sandbox()
        subprocess.run(["./scripts/sandbox", "create", SLUG], cwd=self.root, check=True)
        code, err = self.prepare()
        self.assertEqual(code, 1)
        self.assertIn("did not create", err)

    def test_configured_sandbox_must_start_at_the_pinned_commit(self):
        self.configure_sandbox()
        self.pin()
        backend = self.repos["cofee-backend"]
        with open(os.path.join(backend, "README.md"), "a") as fh:
            fh.write("two\n")
        git(backend, "commit", "-qam", "two")  # the sandbox command branches from the new HEAD
        code, err = self.prepare()
        self.assertEqual(code, 1)
        self.assertIn("pinned", err)

    def test_configured_remove_needs_pushed_branches(self):
        self.configure_sandbox()
        self.assertEqual(self.prepare()[0], 0)
        sandbox = os.path.join(self.root, "sandbox", SLUG)
        self.deliver(pushed=False)
        _, out = self.remove()
        self.assertFalse(out["removed"])
        self.assertIn("not pushed", out["summary"])
        self.assertTrue(os.path.isdir(sandbox))
        self.deliver(pushed=True)
        _, out = self.remove()
        self.assertTrue(out["removed"], out)
        self.assertFalse(os.path.isdir(os.path.join(sandbox, "codebase", "cofee-backend")))

    def test_configured_without_remove_keeps_the_sandbox(self):
        self.configure_sandbox(remove=False)
        self.assertEqual(self.prepare()[0], 0)
        self.deliver(pushed=True)
        _, out = self.remove()
        self.assertFalse(out["removed"])
        self.assertIn("no worktree.remove", out["summary"])

    def test_no_record_means_nothing_to_remove(self):
        _, out = self.remove()
        self.assertFalse(out["removed"])


class BugfixSandboxTest(unittest.TestCase):
    """A bug is fixed on the person's branch: check-base looks for it (locally or on origin),
    prepare --base-map builds one worktree per repository off its own base, all or nothing, and
    bugfix-start registers them so the QA bug-fix loop hands them out."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="sandbox-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repos = {}
        for name in ("api", "web"):
            repo = os.path.join(self.root, "codebase", name)
            os.makedirs(repo)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "T")
            with open(os.path.join(repo, "README.md"), "w") as fh:
                fh.write("one\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-q", "-m", "one")
            self.repos[name] = repo
        api, web = self.repos["api"], self.repos["web"]
        # api has release-1 locally, one commit ahead of main
        git(api, "checkout", "-q", "-b", "release-1")
        with open(os.path.join(api, "README.md"), "a") as fh:
            fh.write("release\n")
        git(api, "commit", "-qam", "release")
        git(api, "checkout", "-q", "main")
        # web has release-1 only on its remote
        origin = os.path.join(self.root, "origin-web.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
        git(web, "remote", "add", "origin", origin)
        git(web, "branch", "release-1")
        git(web, "push", "-q", "origin", "main", "release-1")
        git(web, "branch", "-q", "-D", "release-1")
        os.makedirs(statemod.feature_dir(SLUG, self.root))

    def check_base(self, branch, repos="api,web"):
        code, out = call(worktrees, "check-base", "--root", self.root, "--slug", SLUG,
                         "--branch", branch, "--repos", repos)
        self.assertEqual(code, 0, out)
        return out

    def prepare(self, bases):
        return call(worktrees, "prepare", "--root", self.root, "--slug", SLUG,
                    "--base-map", json.dumps(bases))

    def test_check_base_finds_local_and_remote_branches(self):
        out = self.check_base("release-1")
        self.assertTrue(out["all_present"], out)
        refs = {row["repo"]: row["ref"] for row in out["repos"]}
        self.assertEqual(refs, {"api": "release-1", "web": "origin/release-1"})
        self.assertEqual({row["default_branch"] for row in out["repos"]}, {"main"})
        out = self.check_base("hotfix-9")
        self.assertFalse(out["all_present"])
        self.assertEqual(out["missing_csv"], "api,web")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".maestro", "worktrees")))

    def test_prepare_builds_each_repo_off_its_base_and_bugfix_start_registers_it(self):
        path = os.path.join(statemod.engine_dir(SLUG, self.root), "bug-bases.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            json.dump({"api": "release-1", "web": "release-1"}, fh)
        code, out = call(worktrees, "prepare", "--root", self.root, "--slug", SLUG,
                         "--base-map", os.path.relpath(path, self.root))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["created_csv"], "api,web")
        with open(worktrees.sandbox_path(self.root, SLUG)) as fh:
            sandbox = json.load(fh)
        self.assertEqual(sandbox["feature_slug"], SLUG)
        rows = {row["repo"]: row for row in sandbox["repositories"]}
        self.assertEqual(rows["api"]["commit"], git(self.repos["api"], "rev-parse", "release-1"))
        self.assertEqual(rows["web"]["commit"],
                         git(self.repos["web"], "rev-parse", "origin/release-1"))
        self.assertEqual(rows["api"]["branch"], f"fix/{SLUG}-api")
        self.assertEqual(rows["api"]["base"], "release-1")
        self.assertEqual(git(rows["web"]["worktree"], "branch", "--show-current"),
                         f"fix/{SLUG}-web")
        # the QA bug-fix loop hands the sandbox out like implemented repositories
        code, out = call(pool, "bugfix-start", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["repos_csv"], "api,web")
        self.assertEqual(call(pool, "bugfix-init", "--root", self.root, "--slug", SLUG,
                              "--repos-text", "web")[0], 0)
        _, claim = call(pool, "bugfix-claim", "--root", self.root, "--slug", SLUG)
        self.assertEqual((claim["repo"], claim["branch"], claim["worktree"], claim["commit"]),
                         ("web", f"fix/{SLUG}-web", rows["web"]["worktree"],
                          rows["web"]["commit"]))
        # prepare again reuses the sandbox
        code, out = self.prepare({"api": "release-1", "web": "release-1"})
        self.assertEqual((code, out["reused_csv"]), (0, "api,web"))

    def test_prepare_is_all_or_nothing(self):
        code, err = self.prepare({"api": "release-1", "web": "no-such-branch"})
        self.assertEqual(code, 1)
        self.assertIn("web: base no-such-branch not found", err)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".maestro", "worktrees", SLUG,
                                                     "api")))
        self.assertEqual(git(self.repos["api"], "branch", "--list", f"fix/{SLUG}-api"), "")
        self.assertFalse(os.path.exists(worktrees.sandbox_path(self.root, SLUG)))

    def test_bugfix_start_refuses_a_worktree_that_moved(self):
        self.assertEqual(self.prepare({"api": "main"})[0], 0)
        with open(worktrees.sandbox_path(self.root, SLUG)) as fh:
            sandbox = json.load(fh)
        sandbox["repositories"][0]["commit"] = "0" * 40
        with open(worktrees.sandbox_path(self.root, SLUG), "w") as fh:
            json.dump(sandbox, fh)
        code, err = call(pool, "bugfix-start", "--root", self.root, "--slug", SLUG)
        self.assertEqual(code, 1)
        self.assertIn("api", err)

    def test_configured_create_gets_the_base_branch(self):
        scripts = os.path.join(self.root, "scripts")
        os.makedirs(scripts)
        script = os.path.join(scripts, "sandbox")
        with open(script, "w") as fh:
            fh.write('#!/bin/sh\nset -e\nslug="$1"; base="$2"\n'
                     'echo "$MAESTRO_BASE_BRANCH" > "$PWD/base-env.txt"\n'
                     'for repo in codebase/*/; do name=$(basename "$repo")\n'
                     '  git -C "$repo" worktree add -q -b "sandbox/$slug" '
                     '"$PWD/sandbox/$slug/codebase/$name" "$base"\ndone\n')
        os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
        with open(os.path.join(self.root, "maestro.config.yaml"), "w") as fh:
            fh.write("version: 1\nrepos: {}\nworktree:\n  create: ./scripts/sandbox {slug} {branch}\n"
                     "  path: sandbox/{slug}/codebase/{repo}\n  branch: sandbox/{slug}\n")
        code, err = self.prepare({"api": "release-1", "web": "main"})
        self.assertEqual(code, 1)
        self.assertIn("one base branch", err)
        code, out = self.prepare({"api": "main", "web": "main"})
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.root, "base-env.txt")) as fh:
            self.assertEqual(fh.read().strip(), "main")
        with open(worktrees.sandbox_path(self.root, SLUG)) as fh:
            rows = json.load(fh)["repositories"]
        self.assertEqual([row["branch"] for row in rows], [f"sandbox/{SLUG}"] * 2)


class WorktreeConfigTest(unittest.TestCase):
    def issues(self, section):
        return [i.code for i in project_config._check_worktree(section)]

    def test_valid_section(self):
        self.assertEqual(self.issues({"create": "./scripts/sandbox create {slug} -y",
                                      "path": "sandbox/{slug}/codebase/{repo}",
                                      "remove": "rm -rf \"${HOME}/x\" {slug}"}), [])
        # a bugfix sandbox's base branch
        self.assertEqual(self.issues({"create": "./scripts/sandbox create {slug} --base {branch}",
                                      "path": "sandbox/{slug}/codebase/{repo}"}), [])

    def test_create_and_path_go_together_and_path_is_per_feature_and_repo(self):
        self.assertIn("config-missing-command", self.issues({"path": "w/{slug}/{repo}"}))
        self.assertIn("config-shape", self.issues({"create": "x", "path": "sandbox/{repo}"}))
        self.assertIn("config-shape", self.issues({"create": "x", "path": "../{slug}/{repo}"}))
        self.assertIn("config-shape", self.issues({"create": "x {repo}", "path": "w/{slug}/{repo}"}))
        self.assertIn("config-unknown-key", self.issues({"create": "x", "path": "w/{slug}/{repo}",
                                                         "base": "main"}))

    def test_apply_adds_a_reported_section_only_when_the_file_has_none(self):
        root = tempfile.mkdtemp(prefix="wt-config-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        report = {"repos": {}, "worktree": {"create": "./scripts/sandbox create {slug} -y",
                                            "path": "sandbox/{slug}/codebase/{repo}"}}
        self.assertTrue(project_config.apply_detected(root, report)["worktree_added"])
        report["worktree"]["create"] = "something else {slug}"
        self.assertFalse(project_config.apply_detected(root, report)["worktree_added"])
        self.assertEqual(project_config.load(root)["worktree"]["create"],
                         "./scripts/sandbox create {slug} -y")

    def test_apply_adds_a_reported_environment_only_with_start_and_stop_and_only_once(self):
        root = tempfile.mkdtemp(prefix="env-config-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        report = {"repos": {}, "environment": {"start": './scripts/infra up "$MAESTRO_SLUG"'}}
        self.assertFalse(project_config.apply_detected(root, report)["environment_added"])
        report["environment"]["stop"] = './scripts/infra down "$MAESTRO_SLUG"'
        self.assertTrue(project_config.apply_detected(root, report)["environment_added"])
        report["environment"]["start"] = "something else"
        self.assertFalse(project_config.apply_detected(root, report)["environment_added"])
        self.assertEqual(project_config.load(root)["environment"],
                         {"start": './scripts/infra up "$MAESTRO_SLUG"',
                          "stop": './scripts/infra down "$MAESTRO_SLUG"'})


class WorktreePromptTest(unittest.TestCase):
    WF = """\
version: 1
name: one
inputs:
  slug: {type: string, required: true}
  worktree: {type: string, default: ""}
start: implement
nodes:
  - id: implement
    type: agent
    instruction: Build it.
    isolate: worktree
    inputs: {repo_path: codebase/api, worktree: "${inputs.worktree}", branch: feature/x-api}
    outputs: [branch, worktree, commit]
"""

    def prompt(self, inputs):
        root = tempfile.mkdtemp(prefix="wt-prompt-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "workflows"))
        with open(os.path.join(root, "workflows", "one.yaml"), "w") as fh:
            fh.write(self.WF)
        with statemod.locked("x", root):
            resolver.init_run("x", "workflows/one.yaml", inputs, root)
        action = resolver.next_action(resolver.Run("x", root))
        self.assertNotIn("env", action)
        return action["prompt"]

    def test_supplied_worktree_is_used_not_created(self):
        text = self.prompt({"worktree": "/ws/sandbox/x/codebase/api"})
        self.assertIn("The engine created this feature's worktree", text)
        self.assertIn("/ws/sandbox/x/codebase/api", text)
        self.assertNotIn("worktree add", text)

    def test_without_one_the_agent_creates_it(self):
        self.assertIn("worktree add -b feature/x-api", self.prompt({}))


if __name__ == "__main__":
    unittest.main()
