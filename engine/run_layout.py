#!/usr/bin/env python3
"""Where a run keeps its files. One folder per kind, so a person finds a document without wading
through the engine's bookkeeping:

    .maestro/runs/<slug>/
      state.yaml      the ledger (engine only)
      requirement/    what was asked: the person's files, prd.md
      design/         what will be built: hld.md, openapi.yaml, lld/<repo>.md, test-cases.md,
                      impact.json + impact-trace.md, open-questions.json
      decisions/      what was decided: decision-log.md (unconfirmed decisions first), each
                      stage's interview record (prd.json, hld.json, lld.json), hld-brainstorm.md
      reviews/        what reviewers found: <name>.md + <name>.findings.json, and the author's
                      <name>.resolutions.json (architecture, lld-readiness, drift, code-<repo>)
      build/          what was built: manifest.json, <repo>/tasks.json + verify.json
      qa/             how it was tested: the suite, report.md, results.json
      release/        what ships: review-pack.md, ac-trace.md, delivery.json
      .engine/        the engine's working files: question queues, review baselines, sync plans,
                      snapshots, logs, replaced ledgers. Nothing here is written for reading.

A workflow names its paths on its nodes; the engine helpers that have a default take it from
here, and test_run_layout.py holds the shipped workflows to this layout, so the two cannot drift.

    run_layout.py migrate --slug S [--root .] [--dry-run] [--force]

moves a run written under the earlier flat layout (run_format 3) into this one: files are moved,
never rewritten (an approved document keeps its hash); the ledger and the engine's own JSON
records get their paths updated; the hidden review snapshot folders become one baseline file per
review; `decision-log.json` and `assumptions.md`, which only repeated the stage records, are
dropped and the decision log is rendered again. `maestroctl init` and `rebase` run it when the
ledger says format 3. Prints one JSON line {migrated, moved, removed, kept}.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state as statemod  # noqa: E402

ENGINE = statemod.ENGINE_DIR
FOLDERS = ("requirement", "design", "decisions", "reviews", "build", "qa", "release", ENGINE)

# -- documents a person reads or approves ------------------------------------------------
REQUIREMENT_DIR = "requirement"
PRD = "requirement/prd.md"
HLD = "design/hld.md"
OPEN_QUESTIONS = "design/open-questions.json"
CONTRACT = "design/openapi.yaml"
LLD_DIR = "design/lld"
TEST_CASES = "design/test-cases.md"
IMPACT = "design/impact.json"
IMPACT_TRACE = "design/impact-trace.md"
DECISIONS_DIR = "decisions"
DECISION_LOG = "decisions/decision-log.md"
MANIFEST = "build/manifest.json"
DELIVERY = "release/delivery.json"

# -- the engine's working files ------------------------------------------------------------
MEMORY_SNAPSHOT = f"{ENGINE}/memory-snapshot.json"
RUN_BRIEF = f"{ENGINE}/run-brief.md"
PROFILE_JSON = f"{ENGINE}/profile.json"
PROFILE_MD = f"{ENGINE}/profile.md"
LLD_SCOPE = f"{ENGINE}/lld-scope.json"
LLD_APPROVAL = f"{ENGINE}/lld-approval.json"
POOL = f"{ENGINE}/implementation-pool.json"
WORKTREES = f"{ENGINE}/worktrees.json"
WORKSPACE_LOCK = f"{ENGINE}/workspace-lock.json"
DESIGN_FACTS = f"{ENGINE}/facts/design.md"
QUEUES_DIR = f"{ENGINE}/queues"
LOGS_DIR = f"{ENGINE}/logs"
PR_BODIES_DIR = f"{ENGINE}/pr-bodies"


def lld(repo):
    return f"{LLD_DIR}/{repo}.md"


def stage_record(stage):
    """A design stage's interview record (every question, answer and source)."""
    return f"{DECISIONS_DIR}/{stage.lower()}.json"


def queue(stage):
    """The stage's latest question queue, written by its question step."""
    return f"{QUEUES_DIR}/{stage.lower()}.json"


def receipt(repo):
    """The engine's build/lint/test receipt for one repository (repo_checks.py --out)."""
    return f"build/{repo}/verify.json"


def reviewed(repo):
    """Which commit the code review's verdict covers (findings.py verdict --reviewed)."""
    return f"{ENGINE}/reviews/code-{repo}.reviewed.json"


def path(slug, root, rel):
    """A layout path (relative to the run folder, `/`-separated) on disk."""
    return os.path.join(statemod.feature_dir(slug, root), *rel.split("/"))


def is_engine_file(rel_to_root):
    """True for a workspace-relative path inside some run's `.engine/` folder."""
    return f"/{ENGINE}/" in "/" + rel_to_root.replace(os.sep, "/")


# -- the flat layout of run_format 3, and where each of its files lives now -------------------
# First match wins. `{repo}` rules come last: a repository's folder was any top-level folder
# that was not one of the fixed ones.
_FIXED_TOP = {"qa", "requirement", "reviews", "lld", "logs", "delivery", "worktrees", *FOLDERS}
_DROPPED = "<dropped>"       # derived content: removed, nothing replaces the file
_CONVERTED = "<converted>"   # folded into another file by migrate()
LEGACY = [(re.compile(f"^(?:{old})$"), new) for old, new in (
    (r"state\.yaml\.lock", _DROPPED),
    (r"state\.yaml\.(?P<kind>replaced|unreadable)-(?P<stamp>[0-9A-Za-z-]+)",
     f"{ENGINE}/ledgers/{{kind}}-{{stamp}}.yaml"),
    (r"memory-snapshot\.json", MEMORY_SNAPSHOT),
    (r"run-brief\.md", RUN_BRIEF),
    (r"profile\.(?P<ext>md|json)", f"{ENGINE}/profile.{{ext}}"),
    (r"logs/(?P<name>.+)", f"{LOGS_DIR}/steps/{{name}}"),
    (r"workspace-lock\.json", WORKSPACE_LOCK),
    (r"infra-profile\.json", f"{ENGINE}/infra-profile.json"),
    (r"lld-repos\.json", LLD_SCOPE),
    (r"lld/approval\.json", LLD_APPROVAL),
    (r"implementation-repos\.json", POOL),
    (r"worktrees\.json", WORKTREES),
    (r"worktrees/(?P<name>.+)", f"{LOGS_DIR}/worktrees/{{name}}"),
    (r"implementation-manifest\.json", MANIFEST),
    (r"delivery\.json", DELIVERY),
    (r"delivery/(?P<repo>.+)-pr-body\.md", f"{PR_BODIES_DIR}/{{repo}}.md"),
    (r"scaffold\.json", "build/scaffold.json"),
    (r"greenfield-plan\.json", f"{ENGINE}/greenfield-plan.json"),
    # design
    (r"hld\.md", HLD),
    (r"open-questions\.json", OPEN_QUESTIONS),
    (r"openapi\.yaml", CONTRACT),
    (r"lld/(?P<repo>[^/]+)\.md", f"{LLD_DIR}/{{repo}}.md"),
    (r"lld", LLD_DIR),
    (r"test-cases\.md", TEST_CASES),
    (r"impact\.json", IMPACT),
    (r"impact-trace\.md", IMPACT_TRACE),
    (r"design-facts\.md", DESIGN_FACTS),
    # decisions
    (r"decision-log\.md", DECISION_LOG),
    (r"decision-log\.json", _DROPPED),
    (r"assumptions\.md", _DROPPED),
    (r"hld-brainstorm\.md", f"{DECISIONS_DIR}/hld-brainstorm.md"),
    (r"(?P<stage>[a-z0-9]+)-context\.json", f"{DECISIONS_DIR}/{{stage}}.json"),
    (r"(?P<stage>[a-z0-9]+)-post-questions\.json", f"{QUEUES_DIR}/{{stage}}-post.json"),
    (r"(?P<stage>[a-z0-9]+)-questions\.json", f"{QUEUES_DIR}/{{stage}}.json"),
    # reviews
    (r"reviews/\.(?P<name>[a-z0-9-]+)-snapshot(?:/.*)?", _CONVERTED),
    (r"reviews/(?P<name>[a-z0-9-]+)-findings\.previous\.json", _CONVERTED),
    (r"reviews/(?P<name>[a-z0-9-]+)-findings\.json", "reviews/{name}.findings.json"),
    (r"reviews/(?P<name>[a-z0-9-]+)-resolutions\.json", "reviews/{name}.resolutions.json"),
    (r"reviews/(?P<name>[a-z0-9-]+)\.diff", f"{ENGINE}/reviews/{{name}}.diff"),
    # release
    (r"review-pack\.md", "release/review-pack.md"),
    (r"ac-trace\.md", "release/ac-trace.md"),
    # QA logs
    (r"qa/e2e-receipt-logs/(?P<name>.+)", f"{LOGS_DIR}/qa/e2e/{{name}}"),
    (r"qa/environment/(?P<name>.+)", f"{LOGS_DIR}/qa/environment/{{name}}"),
    # workspace sync, knowledge build, retrospect
    (r"workspace-sync-(?P<cp>.+)-(?P<what>plan|result)\.json", f"{ENGINE}/sync/{{cp}}/{{what}}.json"),
    (r"workspace-sync-(?P<cp>.+)-(?P<what>docs|map)-snapshot\.json",
     f"{ENGINE}/sync/{{cp}}/{{what}}-snapshot.json"),
    (r"workspace-sync-(?P<cp>.+)-(?P<what>inventory|knowledge)\.md",
     f"{ENGINE}/sync/{{cp}}/{{what}}.md"),
    (r"knowledge-freshness-plan\.json", f"{ENGINE}/knowledge/plan.json"),
    (r"codebase-map-snapshot\.json", f"{ENGINE}/knowledge/map-snapshot.json"),
    (r"docs-snapshot\.json", f"{ENGINE}/knowledge/docs-snapshot.json"),
    (r"workspace-inventory\.md", f"{ENGINE}/knowledge/inventory.md"),
    (r"retrospect-(?P<what>docs|map)-snapshot\.json", f"{ENGINE}/retrospect/{{what}}-snapshot.json"),
    (r"retrospect-inventory\.md", f"{ENGINE}/retrospect/inventory.md"),
    # one repository's files
    (r"(?P<repo>[^/]+)/tasks\.json", "build/{repo}/tasks.json"),
    (r"(?P<repo>[^/]+)/verify\.json", "build/{repo}/verify.json"),
    (r"(?P<repo>[^/]+)/verify-logs/(?P<name>.+)", f"{LOGS_DIR}/verify/{{repo}}/{{name}}"),
    (r"(?P<repo>[^/]+)/domain-rules\.json", "build/{repo}/domain-rules.json"),
    (r"(?P<repo>[^/]+)/facts\.md", f"{ENGINE}/facts/{{repo}}.md"),
    (r"(?P<repo>[^/]+)/reviews/summary\.md", "reviews/code-{repo}.md"),
    (r"(?P<repo>[^/]+)/reviews/findings\.json", "reviews/code-{repo}.findings.json"),
    (r"(?P<repo>[^/]+)/reviews/resolutions\.json", "reviews/code-{repo}.resolutions.json"),
    (r"(?P<repo>[^/]+)/reviews/reviewed\.json", f"{ENGINE}/reviews/code-{{repo}}.reviewed.json"),
    (r"(?P<repo>[^/]+)/reviews/code-review-findings\.previous\.json", _CONVERTED),
)]


def legacy_to_new(rel):
    """Where a run_format-3 path (relative to the run folder) lives now: the new relative path,
    `_DROPPED`, `_CONVERTED`, or None when the path is not one the flat layout used."""
    rel = rel.replace(os.sep, "/")
    for pattern, new in LEGACY:
        match = pattern.match(rel)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("repo") is not None and pattern.pattern.startswith("^(?:(?P<repo>") \
                and groups["repo"] in _FIXED_TOP:
            continue  # qa/tasks.json, reviews/..., not a repository's folder
        return new.format(**groups) if "{" in new else new
    return None


def legacy_paths(text):
    """[(old, new)] for every run path of the flat layout that `text` (a workflow) still names,
    whatever stands for the slug — so an edited workflow kept across an upgrade can be told
    exactly what to rename."""
    found = {}
    for match in re.finditer(r"\.maestro/runs/(?:\$\{[^}]+\}|<[^>]+>|[A-Za-z0-9._-]+)/"
                             r"((?:\$\{[^}]+\}|[A-Za-z0-9_.@+/-])+)", text):
        old = match.group(1).rstrip("./")
        new = legacy_to_new(old)
        if new and new not in (_DROPPED, _CONVERTED) and new != old:
            found[old] = new
        elif new in (_DROPPED, _CONVERTED):
            found[old] = "no longer written"
    return sorted(found.items())


# ------------------------------------------------------------------------------- migration

def needs_migration(slug, root="."):
    """True when the run's ledger was written under the flat layout."""
    data, _problem = statemod.inspect(slug, root)
    return bool(data) and (data.get("run_format") or 0) < statemod.RUN_FORMAT_VERSION


def _files(run_dir):
    out = []
    for base, dirs, files in os.walk(run_dir):
        dirs.sort()
        for name in sorted(files):
            out.append(os.path.relpath(os.path.join(base, name), run_dir).replace(os.sep, "/"))
    return out


def _sha(full):
    return statemod.sha256_file(full)


# A dropped file something still refers to (a finished step's recorded output): what to read now.
_SUPERSEDED = {"assumptions.md": DECISION_LOG, "decision-log.json": DECISION_LOG}


def _rewriter(slug):
    """A function that swaps every flat-layout run path in a string for its new place."""
    pattern = re.compile(r"(\.maestro/runs/%s/)([A-Za-z0-9_.@+/-]+)" % re.escape(slug))

    def swap(match):
        rest, tail = match.group(2), ""
        while rest and rest[-1] in "./":  # sentence punctuation, or a folder's slash
            rest, tail = rest[:-1], rest[-1] + tail
        new = _SUPERSEDED.get(rest) or legacy_to_new(rest)
        if not new or new in (_DROPPED, _CONVERTED):
            return match.group(0)
        return match.group(1) + new + tail

    return lambda text: pattern.sub(swap, text)


def _walk_strings(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk_strings(item, fn) for item in value]
    if isinstance(value, dict):
        return {(fn(key) if isinstance(key, str) else key): _walk_strings(item, fn)
                for key, item in value.items()}
    return value


def _one_copy_of_an_accepted_answer(text):
    """A stage record kept an accepted recommendation twice (`proposal` and `answer`): keep the
    answer, as new records do, so a `proposal` in a record is always one the person did not take."""
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    decisions = doc.get("decisions") if isinstance(doc, dict) else None
    changed = False
    for item in decisions if isinstance(decisions, list) else []:
        if isinstance(item, dict) and item.get("proposal") and item["proposal"] == item.get("answer"):
            del item["proposal"]
            changed = True
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n" if changed else text


def _review_baselines(run_dir, rewrite, dry_run):
    """Fold each review's kept copies (`reviews/.<name>-snapshot/`, one file per reviewed
    document) and previous findings into `.engine/reviews/<name>.baseline.json`."""
    done = []
    reviews = os.path.join(run_dir, "reviews")
    names = set()
    if os.path.isdir(reviews):
        for entry in os.listdir(reviews):
            match = re.match(r"^\.(.+)-snapshot$", entry)
            if match and os.path.isdir(os.path.join(reviews, entry)):
                names.add(match.group(1))
            match = re.match(r"^(.+)-findings\.previous\.json$", entry)
            if match:
                names.add(match.group(1))
    sources = [(name, os.path.join(reviews, f".{name}-snapshot"),
                os.path.join(reviews, f"{name}-findings.previous.json"), name) for name in names]
    for entry in sorted(os.listdir(run_dir)) if os.path.isdir(run_dir) else []:
        previous = os.path.join(run_dir, entry, "reviews", "code-review-findings.previous.json")
        if entry not in _FIXED_TOP and os.path.isfile(previous):
            sources.append((f"code-{entry}", "", previous, entry))
    for name, snapshot_dir, previous, _owner in sorted(sources):
        target = os.path.join(run_dir, *f"{ENGINE}/reviews/{name}.baseline.json".split("/"))
        files, ids = {}, []
        if snapshot_dir and os.path.isdir(snapshot_dir):
            for kept in sorted(os.listdir(snapshot_dir)):
                with open(os.path.join(snapshot_dir, kept), encoding="utf-8") as fh:
                    files[rewrite(kept.replace("__", "/"))] = fh.read()
        if os.path.isfile(previous):
            try:
                with open(previous, encoding="utf-8") as fh:
                    doc = json.load(fh)
                ids = [item.get("id") for item in doc.get("findings") or []
                       if isinstance(item, dict) and isinstance(item.get("id"), str)]
            except (OSError, ValueError, AttributeError):
                ids = []
        done.append(os.path.relpath(target, run_dir).replace(os.sep, "/"))
        if dry_run or os.path.exists(target):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "files": files,
                       "finding_ids": ids if os.path.isfile(previous) else None}, fh, indent=2)
            fh.write("\n")
    return done


def _prune_empty(run_dir):
    """Remove the folders the moves emptied (children first), never requirement/."""
    for base, _dirs, _files in os.walk(run_dir, topdown=False):
        if base != run_dir and os.path.basename(base) != "requirement" and not os.listdir(base):
            os.rmdir(base)


def migrate(slug, root=".", dry_run=False, force=False):
    """Move a flat-layout run into this layout. Idempotent; call it holding the run's lock.
    -> {migrated, moved: [[old, new]], removed: [old], kept: [old]} (paths relative to the run
    folder; `kept` are files whose new place was already taken, left where they were)."""
    report = {"migrated": False, "moved": [], "removed": [], "kept": []}
    run_dir = statemod.feature_dir(slug, root)
    if not os.path.isdir(run_dir) or not (force or needs_migration(slug, root)):
        return report
    rewrite = _rewriter(slug)
    converted = _review_baselines(run_dir, rewrite, dry_run)
    for rel in _files(run_dir):
        new = legacy_to_new(rel)
        if new is None or new == rel:
            continue
        source = os.path.join(run_dir, *rel.split("/"))
        if new in (_DROPPED, _CONVERTED):
            report["removed"].append(rel)
            if not dry_run:
                os.remove(source)
            continue
        target = os.path.join(run_dir, *new.split("/"))
        if os.path.exists(target):
            report["kept"].append(rel)
            continue
        report["moved"].append([rel, new])
        if not dry_run:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(source, target)
    report["migrated"] = True
    report["baselines"] = converted
    if dry_run:
        return report
    # an impact report written with no assessment lists nothing (it is no longer written at all)
    trace = os.path.join(run_dir, *IMPACT_TRACE.split("/"))
    try:
        with open(trace, encoding="utf-8") as fh:
            if "| — | no impacted items listed |" in fh.read():
                os.remove(trace)
                report["removed"].append(IMPACT_TRACE)
    except OSError:
        pass
    _prune_empty(run_dir)

    # The engine's own records name run paths: point them at the new places. Documents are
    # never touched, so every approved hash still matches.
    records = [rel for rel in _files(run_dir) if rel == MANIFEST or rel == "qa/e2e-receipt.json"
               or re.match(r"^build/[^/]+/verify\.json$", rel)
               or re.match(r"^decisions/[^/]+\.json$", rel) or rel in (POOL, WORKTREES)]
    before = {}
    for rel in records:
        full = os.path.join(run_dir, *rel.split("/"))
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
        changed = rewrite(text)
        if rel.startswith(DECISIONS_DIR + "/"):
            changed = _one_copy_of_an_accepted_answer(changed)
        if changed != text:
            before[full] = _sha(full)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(changed)
    # A record whose content changed has a new hash; whatever recorded the old one follows
    # (a receipt's hash in the manifest, the manifest's hash in the ledger).
    renames = {}
    for _ in range(4):
        renames = {old: _sha(full) for full, old in before.items() if old != _sha(full)}
        progressed = False
        for rel in records:
            full = os.path.join(run_dir, *rel.split("/"))
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
            changed = text
            for old, now in renames.items():
                changed = changed.replace(old, now)
            if changed != text:
                before.setdefault(full, _sha(full))
                with open(full, "w", encoding="utf-8") as fh:
                    fh.write(changed)
                progressed = True
        if not progressed:
            break

    data, _problem = statemod.inspect(slug, root)
    if data:
        def fix(text):
            text = rewrite(text)
            for old, now in renames.items():
                text = text.replace(old, now)
            return text

        data = _walk_strings(data, fix)
        memory = data.get("memory") or {}
        if memory.get("snapshot") == "memory-snapshot.json":
            memory["snapshot"] = MEMORY_SNAPSHOT
        # a snapshot that froze no lessons is not kept (new runs write none)
        snapshot = os.path.join(run_dir, *MEMORY_SNAPSHOT.split("/"))
        try:
            with open(snapshot, encoding="utf-8") as fh:
                empty = not (json.load(fh) or {}).get("knowledge")
        except (OSError, ValueError, AttributeError):
            empty = False
        if empty:
            os.remove(snapshot)
            data["memory"] = {}
        data["run_format"] = statemod.RUN_FORMAT_VERSION
        statemod.save(slug, data, root)
    try:
        import decision_log
        decision_log.sync_run(slug, root)
    except Exception as exc:  # noqa: BLE001 — the log is rendered again at the next stage sync
        report["decision_log"] = f"not rendered: {exc}"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("migrate")
    p.add_argument("--root", default=".")
    p.add_argument("--slug", required=True)
    p.add_argument("--dry-run", action="store_true", help="report what would move; change nothing")
    p.add_argument("--force", action="store_true",
                   help="also when the ledger is missing or already says the current format")
    args = parser.parse_args(argv)
    if not statemod.valid_slug(args.slug):
        print(f"invalid slug {args.slug!r}", file=sys.stderr)
        return 3
    if args.dry_run:
        print(json.dumps(migrate(args.slug, args.root, dry_run=True, force=args.force)))
        return 0
    with statemod.locked(args.slug, args.root):
        print(json.dumps(migrate(args.slug, args.root, force=args.force)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
