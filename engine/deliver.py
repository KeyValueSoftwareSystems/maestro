#!/usr/bin/env python3
"""Deliver the released feature: report its verified branches, or push them and open pull requests.

  deliver.py [--root .] --slug S --manifest M [--pack P] [--trace T] [--assumptions A]
             [--release-by person|autopilot]

`--assumptions` is the decision log (its opening "Run mode: …" line is quoted in the pull
request body); `--trace` the acceptance-criteria trace.

`delivery.mode` in maestro.config.yaml decides (default `branch`):
  branch        nothing leaves the machine: report each repository's verified branch and commit.
  pull-request  per manifest repository: re-check the branch is still at the exact verified
                commit (refuse otherwise), push it to `delivery.remote` (default origin), and open
                a pull request against `delivery.base` (default: the remote's default branch)
                with the GitHub CLI — or reuse the open one for that branch. A release that
                autopilot approved (--release-by autopilot) opens as a draft: nobody reviewed it.
                A bug fix targets each repository's own base instead: the branch its sandbox
                was built from (`.engine/bug-bases.json`, else the manifest entry's `base`).

Writes `.maestro/runs/<slug>/release/delivery.json` and prints one JSON line:
{mode, delivered_csv, pr_urls_csv, draft, path, summary}. Exits 1 when a push or pull request
fails (the workflow asks a person); nothing is force-pushed, ever. MAESTRO_GH overrides the `gh`
executable (tests); MAESTRO_SIMULATION=1 delivers nothing.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import implementation_pool  # noqa: E402
import project_config  # noqa: E402
import run_layout  # noqa: E402
import state as statemod  # noqa: E402

BODY_LIMIT = 60000  # GitHub caps a pull request body at 65536 characters


def _read(root, path):
    if not path:
        return ""
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        with open(full, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _first_line(text, prefix=""):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("|"):
            return prefix + line
    return ""


def _run(argv, cwd):
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout.strip() or proc.stderr.strip())


def _verification_text(verification):
    """One line from the manifest's verification record (implementation_pool._verification:
    status, failed_checks, pre_existing, not_configured, test_changes, review, receipt)."""
    parts = []
    if verification.get("failed_checks"):
        parts.append("failed: " + ", ".join(verification["failed_checks"]))
    if verification.get("pre_existing"):
        parts.append("also failing on the base commit: " + ", ".join(verification["pre_existing"]))
    if verification.get("not_configured"):
        parts.append("not configured: " + ", ".join(verification["not_configured"]))
    if verification.get("test_changes"):
        parts.append(f"{len(verification['test_changes'])} existing test file(s) changed")
    review = verification.get("review")
    if review == "not-reviewed":
        parts.append("code review not run on this commit")
    elif review == "blocking":
        parts.append("code review left blocking findings")
    elif review == "reviewed":
        parts.append("code reviewed")
    if verification.get("receipt"):
        parts.append(f"receipt {verification['receipt']}")
    return "; ".join(parts) if parts else "no further detail"


def _remote_repo(remote, cwd):
    """`[HOST/]OWNER/REPO` for gh's --repo, from the remote's URL; "" when it is not a
    recognisable hosted URL (a local path), so gh then falls back to its own default."""
    code, url = _run(["git", "remote", "get-url", remote], cwd)
    if code or not url:
        return ""
    url = url.strip()
    match = (re.match(r"^[\w.+-]+://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+)$", url)
             or re.match(r"^(?:[^@/\s]+@)?(?P<host>[^/:\s]+):(?P<path>[^/].*)$", url))
    if not match:
        return ""
    path = re.sub(r"(\.git)?/*$", "", match.group("path"))
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", path):
        return ""
    host = match.group("host")
    return path if host.lower() == "github.com" else f"{host}/{path}"


def _body(entry, siblings, args, root):
    verification = entry.get("verification") or {}
    lines = [
        f"Feature `{args.slug}` — repository `{entry['repo']}`, commit `{entry['commit']}`.",
        "",
        f"- Engine verification: {verification.get('status', 'missing')} "
        f"({_verification_text(verification)})",
    ]
    trace = _first_line(_read(root, args.trace))
    if trace:
        lines.append(f"- Acceptance criteria: {trace}")
    assumptions = _read(root, args.assumptions)
    for line in assumptions.splitlines():
        if line.startswith("Run mode:"):
            lines.append(f"- {line.strip()}")
            break
    if siblings:
        lines.append("- Same feature in: " + ", ".join(siblings))
    if args.release_by == "autopilot":
        lines += ["", "> Opened as a draft: the release was approved on autopilot. Review it, "
                      "starting with the assumptions in the review pack."]
    pack = _read(root, args.pack)
    if pack:
        lines += ["", "<details><summary>Review pack</summary>", "", pack.strip(), "", "</details>"]
    body = "\n".join(lines) + "\n"
    return body if len(body) <= BODY_LIMIT else body[:BODY_LIMIT] + "\n\n… (truncated)\n"


def _bug_bases(slug, root):
    """{repo: base branch} a bug fix's sandbox was built from; {} for a feature."""
    try:
        with open(run_layout.path(slug, root, run_layout.BUG_BASES), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in doc.items() if isinstance(v, str) and v.strip()} \
        if isinstance(doc, dict) else {}


def pr_base(entry, bases, delivery):
    """The branch a repository's pull request targets: a bug fix's recorded base for that
    repository, else `delivery.base` ("" lets gh use the remote's default branch)."""
    base = bases.get(entry["repo"]) or entry.get("base") or delivery.get("base") or ""
    remote = delivery.get("remote") or "origin"
    return base[len(remote) + 1:] if base.startswith(remote + "/") else base


def _pull_request(entry, args, root, delivery, gh, siblings, title, base=""):
    branch = entry["branch"]
    worktree = entry["worktree"]
    remote = delivery.get("remote") or "origin"
    code, out = _run(["git", "push", "--set-upstream", remote, f"{branch}:{branch}"], worktree)
    if code:
        raise RuntimeError(f"{entry['repo']}: git push {remote} {branch} failed: {out[-400:]}")
    # target the repository the branch was pushed to, not whatever gh guesses from the
    # worktree's remotes (a fork checkout has several)
    repo_flag = ["--repo", target] if (target := _remote_repo(remote, worktree)) else []
    code, out = _run([gh, "pr", "list", "--head", branch, "--state", "open",
                      "--json", "url", "--jq", ".[0].url", *repo_flag], worktree)
    if code:
        raise RuntimeError(f"{entry['repo']}: gh pr list failed (is gh installed and logged in?): "
                           f"{out[-400:]}")
    if out.strip():
        return {"pr_url": out.strip(), "pr": "existing"}
    body_path = run_layout.path(args.slug, root,
                                f"{run_layout.PR_BODIES_DIR}/{entry['repo']}.md")
    os.makedirs(os.path.dirname(body_path), exist_ok=True)
    with open(body_path, "w", encoding="utf-8") as fh:
        fh.write(_body(entry, siblings, args, root))
    argv = [gh, "pr", "create", "--head", branch, "--title", title, "--body-file", body_path,
            *repo_flag]
    if base:
        argv += ["--base", base]
    if args.release_by == "autopilot":
        argv.append("--draft")
    code, out = _run(argv, worktree)
    if code:
        raise RuntimeError(f"{entry['repo']}: gh pr create failed: {out[-400:]}")
    return {"pr_url": out.strip().splitlines()[-1] if out.strip() else "", "pr": "created"}


def deliver(args):
    root = args.root
    manifest = json.loads(_read(root, args.manifest) or "{}")
    entries = manifest.get("repositories") or []
    if not entries:
        raise RuntimeError(f"manifest {args.manifest} lists no repositories")
    config = project_config.load(root) or {}
    delivery = config.get("delivery") or {}
    mode = delivery.get("mode") or "branch"
    simulated = os.environ.get("MAESTRO_SIMULATION") == "1"
    prd = _read(root, run_layout.path(args.slug, root, run_layout.PRD))
    heading = next((line[2:].strip() for line in prd.splitlines() if line.startswith("# ")), "")
    title = heading.replace(" — PRD", "").replace(" - PRD", "") or args.slug
    gh = os.environ.get("MAESTRO_GH") or "gh"
    results = []
    bases = _bug_bases(args.slug, root)
    if mode == "pull-request" and not simulated:
        discovered = dict(implementation_pool.codebase_scan.discover_repos(root))
        for entry in entries:
            repo_path = discovered.get(entry["repo"])
            if not repo_path:
                raise RuntimeError(f"{entry['repo']}: repository is no longer discoverable")
            check = argparse.Namespace(root=root, repo=entry["repo"], branch=entry["branch"],
                                       worktree=entry["worktree"], commit=entry["commit"])
            try:
                implementation_pool._verify_entry(check, repo_path)
            except ValueError as exc:
                raise RuntimeError(f"{entry['repo']}: refusing to deliver: {exc}") from None
        for entry in entries:
            siblings = [f"`{e['repo']}` ({e['branch']})" for e in entries if e is not entry]
            base = pr_base(entry, bases, delivery)
            outcome = _pull_request(entry, args, root, delivery, gh, siblings,
                                    f"{title} ({entry['repo']})", base)
            results.append({"repo": entry["repo"], "branch": entry["branch"],
                            "commit": entry["commit"], "pushed": True, "base": base,
                            **outcome})
    else:
        results = [{"repo": e["repo"], "branch": e["branch"], "commit": e["commit"],
                    "pushed": False, "base": pr_base(e, bases, delivery), "pr_url": "",
                    "pr": "none"} for e in entries]
    draft = mode == "pull-request" and args.release_by == "autopilot"
    record = {"schema_version": 1, "mode": mode, "delivered_at": statemod.now_iso(),
              "simulated": simulated, "draft": draft, "repositories": results}
    path = run_layout.path(args.slug, root, run_layout.DELIVERY)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
        fh.write("\n")
    urls = [r["pr_url"] for r in results if r["pr_url"]]
    if mode == "pull-request" and not simulated:
        summary = (f"{len(urls)} pull request(s){' (draft)' if draft else ''}: " + ", ".join(urls))
    else:
        summary = ("Verified branches ready to merge (nothing pushed): " + ", ".join(
            f"{r['repo']} {r['branch']} @ {r['commit'][:12]}" for r in results))
    return {"mode": mode, "delivered_csv": ",".join(r["repo"] for r in results),
            "pr_urls_csv": ",".join(urls), "draft": draft,
            "path": os.path.relpath(path, root), "summary": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pack", default="")
    parser.add_argument("--trace", default="")
    parser.add_argument("--assumptions", default="")
    parser.add_argument("--release-by", default="person")
    args = parser.parse_args(argv)
    try:
        result = deliver(args)
    except RuntimeError as exc:
        print(f"cannot deliver: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
