#!/usr/bin/env python3
"""The feature's plan: one document in the workspace root that replaces the HLD, LLDs and API contract.

The plan lives at `docs/plans/active/<slug>.md` while the feature is built and moves to
`docs/plans/completed/<slug>.md` when it is archived. It is written by a swappable skill; this
helper owns everything deterministic about it: its structure per type (major or minor), which
repositories it scopes, a hash-bound approval (PRD, plan, test cases), whether that approval is
still current, the move to `completed/`, and committing the plan file and nothing else.

Commands
--------
  validate --root . --slug S --type major|minor [--prd PATH]
           {valid, issues, issues_summary, repos_csv, new_repos_csv}
  repos    --root . --slug S              {repos_csv, new_repos_csv, count}
  approve  --root . --slug S [--test-cases PATH] [--no-plan] [--repos a,b]
           write .engine/plan-scope.json ({"selected": [...]}) and .engine/plan-approval.json
  verify   --root . --slug S              {stale, reasons, reasons_summary}
  status   --root . --slug S              {active, completed, path}
  archive  --root . --slug S [--final PATH]
           move active -> completed (git mv when tracked), stamp `Status: completed`
  commit   --root . --slug S --event created|updated|completed|auto
           commit only the plan path(s); never pushes; {committed, commit, branch, reason, say}
           (auto: `created` while the plan was never committed, else `updated`)

Every command prints one JSON line. `validate`, `verify`, `status` and `commit` exit 0 so
workflows route on fields; `approve` and `archive` exit 1 (message on stderr) when they refuse.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import project_config  # noqa: E402
import run_layout  # noqa: E402
import state as statemod  # noqa: E402
import validate_prd  # noqa: E402

TYPES = ("major", "minor")
MAJOR_SECTIONS = ("Summary", "Decisions", "Repositories", "Design", "Interfaces", "Infrastructure",
                  "Risks and open points", "Acceptance coverage", "Out of scope")
MINOR_KEYS = ("Change", "Where", "Interface", "Data", "Tests", "Risk")
MINOR_MIN_LINES, MINOR_MAX_LINES = 5, 10
EVENTS = ("created", "updated", "completed")
_AC_RE = re.compile(r"\bAC-(\d+)\b", re.IGNORECASE)
_HEADER_SPLIT = re.compile(r"\s+[·|]\s+")
_NEW_MARK = re.compile(r"\s*\((?:new)\)\s*$", re.IGNORECASE)
_TRUE = {"yes", "y", "new", "true", "x"}


# -- paths ------------------------------------------------------------------------------------
def active_path(slug, root):
    return os.path.join(root, *run_layout.plan_active(slug).split("/"))


def completed_path(slug, root):
    return os.path.join(root, *run_layout.plan_completed(slug).split("/"))


def scope_path(slug, root):
    return run_layout.path(slug, root, run_layout.PLAN_SCOPE)


def approval_path(slug, root):
    return run_layout.path(slug, root, run_layout.PLAN_APPROVAL)


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _hash(path):
    return statemod.sha256_file(path) if path and os.path.isfile(path) else None


def _fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


# -- parsing ----------------------------------------------------------------------------------
def parse(text):
    """{title, header_line, header: {key: value}, body: [non-blank lines after the title],
    sections: {normalised heading: text}}. The header is the first non-blank line after the title."""
    lines = text.splitlines()
    title, rest = None, lines
    for index, line in enumerate(lines):
        if line.strip():
            if re.match(r"^#\s+\S", line):
                title, rest = line[2:].strip(), lines[index + 1:]
            break
    body = [line for line in rest if line.strip()]
    header_line = body[0].strip() if body else ""
    header = {}
    if header_line and not header_line.startswith(("#", "-", "*", "|")):
        for part in _HEADER_SPLIT.split(header_line):
            key, sep, value = part.partition(":")
            if sep and key.strip():
                header[key.strip().lower()] = value.strip()
    return {"title": title, "header_line": header_line, "header": header, "body": body,
            "sections": validate_prd._sections(text)}


def _clean_repo(name):
    return name.strip().strip("`*").strip()


def _table_rows(section_text):
    rows = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        rows.append(cells)
    return rows[1:] if rows else []   # the first row is the table's header


def repositories(text):
    """[(repo, is_new)] the plan names: a major plan's Repositories table (repo | role | new?),
    a minor plan's `Repositories: a, b` header (a repo marked `(new)` is new)."""
    doc = parse(text)
    found = []
    if doc["header"].get("type", "").lower() == "minor" or "repositories" in doc["header"]:
        for part in doc["header"].get("repositories", "").split(","):
            is_new = bool(_NEW_MARK.search(part))
            name = _clean_repo(_NEW_MARK.sub("", part))
            if name:
                found.append((name, is_new))
    else:
        for cells in _table_rows(doc["sections"].get("repositories", "")):
            if not cells or not _clean_repo(cells[0]):
                continue
            raw = cells[0]
            is_new = bool(_NEW_MARK.search(raw)) or (
                len(cells) >= 3 and cells[2].strip().strip("`*").lower() in _TRUE)
            found.append((_clean_repo(_NEW_MARK.sub("", raw)), is_new))
    seen, unique = set(), []
    for name, is_new in found:
        if name not in seen:
            seen.add(name)
            unique.append((name, is_new))
    return unique


def _plan_text(slug, root):
    for path in (active_path(slug, root), completed_path(slug, root)):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
    return None


def new_repositories(slug, root="."):
    """The repositories the plan marks new (greenfield): [] when there is no plan."""
    text = _plan_text(slug, root)
    return [name for name, is_new in repositories(text) if is_new] if text else []


def _known_repos(root):
    try:
        config = project_config.load(root)
    except project_config.ConfigError:
        config = None
    if config is not None:
        return set((config.get("repos") or {}).keys())
    return {name for name, _path in codebase_scan.discover_repos(root)}


def _prd_acs(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    acceptance = validate_prd._sections(text).get("acceptance criteria", "")
    ids = []
    for line in acceptance.splitlines():
        match = validate_prd.AC_LINE_RE.match(line)
        if match:
            ids.append(int(match.group(1)))
    return ids


def validate(slug, root=".", plan_type="major", prd=None, completed=False):
    """[issues] for the active plan ([] = valid); `completed` checks the archived one instead."""
    path = completed_path(slug, root) if completed else active_path(slug, root)
    rel = run_layout.plan_completed(slug) if completed else run_layout.plan_active(slug)
    if not os.path.isfile(path):
        return [f"the plan is missing at {rel}"]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    doc = parse(text)
    header = doc["header"]
    issues = []
    if not doc["title"]:
        issues.append("the plan must start with a `# <Feature> — plan` title line")
    if not header:
        issues.append(f"the line after the title must be the header (`Type: {plan_type} · "
                      f"Run: {slug} · …`)")
    else:
        if header.get("type", "").lower() != plan_type:
            issues.append(f"header: `Type: {plan_type}` expected, found "
                          f"`Type: {header.get('type') or '(none)'}`")
        run = header.get("run", "")
        if not run:
            issues.append(f"header: `Run: {slug}` is missing")
        elif run.strip("`") != slug:
            issues.append(f"this plan belongs to run {run.strip('`')!r}, not {slug!r}: "
                          "choose another slug or update that run's plan")
    if plan_type == "minor":
        count = len(doc["body"])
        if not MINOR_MIN_LINES <= count <= MINOR_MAX_LINES:
            issues.append(f"a minor plan has {MINOR_MIN_LINES}–{MINOR_MAX_LINES} non-blank lines "
                          f"after the title; this one has {count}")
        if header and not header.get("repositories", "").strip():
            issues.append("header: `Repositories: a, b` is missing")
        keys = {m.group(1).lower() for m in (
            re.match(r"^\s*[-*]\s+(?:\*\*)?([A-Za-z]+)(?:\*\*)?\s*:", line) for line in doc["body"])
            if m}
        for key in MINOR_KEYS:
            if key.lower() not in keys:
                issues.append(f"missing the `- {key}:` line")
    else:
        sections = doc["sections"]
        for name in MAJOR_SECTIONS:
            key = validate_prd._normalise_heading(name)
            if key not in sections:
                issues.append(f"missing section `## {name}`")
            elif not sections[key].strip():
                issues.append(f"section `## {name}` is empty (write None when nothing applies)")
    repos = repositories(text)
    if not repos:
        issues.append("the plan names no repositories")
    known = _known_repos(root)
    for name, is_new in repos:
        if not is_new and name not in known:
            issues.append(f"repository {name!r} is not in maestro.config.yaml; mark it new or "
                          "use a configured name")
    if plan_type == "major":
        prd_path = prd or run_layout.path(slug, root, run_layout.PRD)
        if not os.path.isfile(prd_path):
            issues.append("the PRD is missing, so acceptance coverage cannot be checked")
        else:
            covered = {int(n) for n in _AC_RE.findall(
                doc["sections"].get("acceptance coverage", ""))}
            missing = [f"AC-{n:02d}" for n in _prd_acs(prd_path) if n not in covered]
            if missing:
                issues.append(f"Acceptance coverage does not cover {', '.join(missing)}")
    return issues


# -- commands ---------------------------------------------------------------------------------
def cmd_validate(args):
    issues = validate(args.slug, args.root, args.type, args.prd or None)
    path = active_path(args.slug, args.root)
    repos = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            repos = repositories(fh.read())
    print(json.dumps({
        "valid": not issues,
        "issues": issues,
        "issues_summary": " | ".join(issues[:10]) if issues else "the plan is valid",
        "repos_csv": ",".join(name for name, _new in repos),
        "new_repos_csv": ",".join(name for name, is_new in repos if is_new),
    }))
    return 0


def cmd_repos(args):
    text = _plan_text(args.slug, args.root)
    repos = repositories(text) if text else []
    print(json.dumps({"repos_csv": ",".join(name for name, _new in repos),
                      "new_repos_csv": ",".join(name for name, is_new in repos if is_new),
                      "count": len(repos)}))
    return 0


def _test_cases_path(slug, root, given=None):
    return given or run_layout.path(slug, root, run_layout.TEST_CASES)


def _current_hashes(slug, root, with_plan, test_cases=None):
    return {
        "prd_sha256": _hash(run_layout.path(slug, root, run_layout.PRD)),
        "plan_sha256": _hash(active_path(slug, root)) if with_plan else None,
        "test_cases_sha256": _hash(_test_cases_path(slug, root, test_cases)),
    }


def selected(slug, root):
    doc = _read_json(scope_path(slug, root), {})
    repos = doc.get("selected") if isinstance(doc, dict) else None
    return repos if isinstance(repos, list) else []


def cmd_approve(args):
    with_plan = not args.no_plan
    if with_plan and not os.path.isfile(active_path(args.slug, args.root)):
        return _fail(f"cannot approve: no plan at {run_layout.plan_active(args.slug)}")
    if args.repos:
        repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    elif with_plan:
        repos = [name for name, _new in repositories(_plan_text(args.slug, args.root))]
    else:
        repos = []
    if with_plan and not repos:
        return _fail("cannot approve: the plan names no repositories")
    hashes = _current_hashes(args.slug, args.root, with_plan, args.test_cases or None)
    if hashes["prd_sha256"] is None:
        return _fail("cannot approve: the PRD is missing")
    if repos:
        _write_json(scope_path(args.slug, args.root), {"schema_version": 1, "selected": repos})
    path = approval_path(args.slug, args.root)
    _write_json(path, {"schema_version": 1, "approved_at": statemod.now_iso(), "plan": with_plan,
                       "plan_path": run_layout.plan_active(args.slug) if with_plan else None,
                       "test_cases_path": args.test_cases or None,
                       "repos": repos, **hashes})
    print(json.dumps({"approval_path": os.path.relpath(path, args.root),
                      "approval_sha256": statemod.sha256_file(path),
                      "repos_csv": ",".join(repos)}))
    return 0


def stale_reasons(slug, root):
    """Why the approved plan no longer matches what is on disk ([] = current)."""
    approval = _read_json(approval_path(slug, root))
    if not isinstance(approval, dict):
        return ["the plan has no approval record"]
    with_plan = bool(approval.get("plan"))
    if approval.get("repos") and sorted(selected(slug, root)) != sorted(approval["repos"]):
        return ["the repositories in scope changed after the plan was approved"]
    now = _current_hashes(slug, root, with_plan, approval.get("test_cases_path"))
    reasons = []
    if now["prd_sha256"] != approval.get("prd_sha256"):
        reasons.append("the PRD changed after the plan was approved")
    if with_plan and now["plan_sha256"] != approval.get("plan_sha256"):
        reasons.append("the plan changed after it was approved" if now["plan_sha256"]
                       else "the approved plan is no longer in docs/plans/active")
    # test cases not written at approval are not tracked; once recorded, any change is stale
    if approval.get("test_cases_sha256") and \
            now["test_cases_sha256"] != approval["test_cases_sha256"]:
        reasons.append("the test cases changed after the plan was approved")
    return reasons


def cmd_verify(args):
    if os.environ.get("MAESTRO_SIMULATION") == "1":
        print(json.dumps({"stale": False, "reasons": [],
                          "reasons_summary": "[simulated] the plan is current"}))
        return 0
    reasons = stale_reasons(args.slug, args.root)
    print(json.dumps({"stale": bool(reasons), "reasons": reasons,
                      "reasons_summary": "; ".join(reasons) or "the approved plan is current"}))
    return 0


def status(slug, root="."):
    active = os.path.isfile(active_path(slug, root))
    completed = os.path.isfile(completed_path(slug, root))
    path = run_layout.plan_active(slug) if active or not completed \
        else run_layout.plan_completed(slug)
    return {"active": active, "completed": completed, "path": path}


def cmd_status(args):
    print(json.dumps(status(args.slug, args.root)))
    return 0


# -- git --------------------------------------------------------------------------------------
def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def _in_git(root):
    result = _git(root, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _tracked(root, rel):
    return _git(root, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def stamp_completed(text):
    """The plan with its header's `Status:` set to completed (added when the header has none)."""
    lines = text.splitlines(keepends=True)
    seen_title = False
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if not seen_title and re.match(r"^#\s+\S", line):
            seen_title = True
            continue
        ending = "\n" if line.endswith("\n") else ""
        body = line.rstrip("\r\n")
        if re.search(r"\bStatus:\s*\S+", body):
            body = re.sub(r"\bStatus:\s*[^·|]*?(\s*(?:[·|]|$))", r"Status: completed\1", body,
                          count=1)
        else:
            body = f"{body} · Status: completed"
        lines[index] = body + ending
        break
    return "".join(lines)


def archive(slug, root=".", final=None):
    """Move the active plan to completed/. -> (moved_by, completed relative path). ValueError on
    refusal: no active plan, or a completed plan already exists under that slug."""
    source, target = active_path(slug, root), completed_path(slug, root)
    if os.path.exists(target):
        raise ValueError(f"{run_layout.plan_completed(slug)} already exists; a delivered "
                         "feature's plan is never overwritten")
    if not os.path.isfile(source):
        raise ValueError(f"no active plan at {run_layout.plan_active(slug)}")
    if final:
        with open(final, encoding="utf-8") as fh:
            text = fh.read()
    else:
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    moved_by = "move"
    if _in_git(root) and _tracked(root, run_layout.plan_active(slug)):
        result = _git(root, "mv", "--", run_layout.plan_active(slug), run_layout.plan_completed(slug))
        if result.returncode == 0:
            moved_by = "git-mv"
    if moved_by == "move":
        shutil.move(source, target)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(stamp_completed(text))
    return moved_by, run_layout.plan_completed(slug)


def cmd_archive(args):
    try:
        moved_by, rel = archive(args.slug, args.root, args.final or None)
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    print(json.dumps({"archived": True, "path": rel, "moved_by": moved_by}))
    return 0


def _operation_in_progress(root):
    result = _git(root, "rev-parse", "--git-dir")
    if result.returncode != 0:
        return None
    git_dir = result.stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(root, git_dir)
    for marker, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"),
                         ("rebase-apply", "a rebase"), ("CHERRY_PICK_HEAD", "a cherry-pick")):
        if os.path.exists(os.path.join(git_dir, marker)):
            return what
    return None


def commit(slug, root=".", event="updated"):
    """Commit only the plan path(s). -> {committed, commit, branch, paths, reason, say}."""
    out = {"committed": False, "commit": "", "branch": "", "event": event, "reason": "", "say": ""}
    if not _in_git(root):
        out["reason"] = "the workspace root is not a git repository"
        out["say"] = "Kept the plan without committing it: the workspace is not a git repository."
        return out
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    out["branch"] = branch
    busy = _operation_in_progress(root)
    if busy:
        out["reason"] = f"{busy} is in progress"
        out["say"] = f"Kept the plan without committing it: {busy} is in progress."
        return out
    candidates = [run_layout.plan_active(slug)]
    if event == "completed":
        candidates.append(run_layout.plan_completed(slug))
    paths = [rel for rel in candidates
             if _git(root, "status", "--porcelain", "--", rel).stdout.strip()]
    out["paths"] = paths
    if not paths:
        out["reason"] = "the plan has not changed"
        out["say"] = "The plan is already saved."
        return out
    present = [rel for rel in paths if os.path.exists(os.path.join(root, *rel.split("/")))]
    gone = [rel for rel in paths if rel not in present]
    added = _git(root, "add", "--", *present) if present else None
    if gone and (added is None or added.returncode == 0):
        added = _git(root, "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone)
    if added.returncode != 0:
        out["reason"] = f"git add failed: {added.stderr.strip()[:200]}"
        out["say"] = "Could not commit the plan; it is saved on disk."
        return out
    result = _git(root, "commit", "-q", "--only", "-m", f"plan({slug}): {event}", "--", *paths)
    if result.returncode != 0:
        _git(root, "reset", "-q", "--", *paths)
        out["reason"] = f"git commit failed: {(result.stderr or result.stdout).strip()[:200]}"
        out["say"] = "Could not commit the plan; it is saved on disk."
        return out
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    out.update(committed=True, commit=sha)
    out["say"] = (f"Moved the plan to completed and saved it to {branch}." if event == "completed"
                  else f"Saved the plan to {branch}.")
    record = run_layout.path(slug, root, run_layout.PLAN_COMMITS)
    history = _read_json(record, [])
    history = history if isinstance(history, list) else []
    history.append({"event": event, "commit": sha, "branch": branch, "at": statemod.now_iso()})
    _write_json(record, history)
    return out


def auto_event(slug, root="."):
    """`updated` once the active plan is tracked in git, else `created`."""
    rel = run_layout.plan_active(slug)
    return "updated" if _in_git(root) and _tracked(root, rel) else "created"


def cmd_commit(args):
    event = auto_event(args.slug, args.root) if args.event == "auto" else args.event
    print(json.dumps(commit(args.slug, args.root, event)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, fn):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--slug", required=True)
        p.set_defaults(fn=fn)
        return p

    p = add("validate", cmd_validate)
    p.add_argument("--type", choices=TYPES, required=True)
    p.add_argument("--prd", default="")
    add("repos", cmd_repos)
    p = add("approve", cmd_approve)
    p.add_argument("--test-cases", default="")
    p.add_argument("--no-plan", action="store_true",
                   help="a run without a plan (bugfix): bind the PRD and test cases only")
    p.add_argument("--repos", default="", help="the repositories in scope (default: the plan's)")
    add("verify", cmd_verify)
    add("status", cmd_status)
    p = add("archive", cmd_archive)
    p.add_argument("--final", default="", help="the reconciled plan to archive instead")
    p = add("commit", cmd_commit)
    p.add_argument("--event", choices=EVENTS + ("auto",), required=True)
    args = parser.parse_args(argv)
    if not statemod.valid_slug(args.slug):
        return _fail(f"invalid slug {args.slug!r}")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
