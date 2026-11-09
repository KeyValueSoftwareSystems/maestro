#!/usr/bin/env python3
"""Domain rules and change scenarios: optional knowledge people write, checked against the code.

Nothing here is required. A workspace without rules runs exactly as before; when a person has
written them, Maestro uses them.

Where people write them (docs/functional is the build-knowledge domain doc):
  docs/functional/<domain>.md
      ## Rules that must never break
      - INV-PL-01 One active payment link per invoice.
      ## If you change… also check
      | CS-PL-01 | Disabling a link | Reminders, late webhooks |
  docs/impact/side-effects.yaml          the same scenarios, machine-readable (see docs/domain-rules.md)
  code, tests, local CLAUDE.md files      cite the ids: `// INV-PL-01: why`

  domain_rules.py status   [--root .]
      {present, rule_count, scenario_count, domains_csv, side_effects, summary}
  domain_rules.py check    [--root .] [--repo NAME --worktree PATH] [--out report.json]
      present false -> {present: false, valid: true, skipped: true}. Otherwise checks that every
      name a scenario relies on (file, symbol, table, queue, endpoint, test) still exists, every
      INV rule is cited in code or a test, and no code cites an id no doc defines.
      {present, valid, skipped, error_count, warning_count, rule_count, scenario_count,
       issues_summary, report_path, summary}. With --repo/--worktree the named repository is read
      from that worktree (the feature's code) instead of its main checkout.
  domain_rules.py scaffold [--root .]
      writes a starter docs/impact/side-effects.yaml (comments and an empty list) when there is
      none; never overwrites, never edits a domain page. {created, path}
  domain_rules.py next CODE [--root .]
      the next free INV and CS number for a domain code.

Every command prints one JSON line and exits 0 (the workflow routes on `valid`); argument errors
exit 2. A name "exists" when it appears as a whole word in the repository's source files: no
parsing, no network, no model.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import wf  # noqa: E402

FUNCTIONAL = os.path.join("docs", "functional")
SIDE_EFFECTS = os.path.join("docs", "impact", "side-effects.yaml")
RULE_RE = re.compile(r"\b(INV|CS)-([A-Z]{2,5})-(\d{2,3})\b")
ID_RE = re.compile(r"^(INV|CS)-([A-Z]{2,5})-(\d{2,3})$")
RULE_LINE = re.compile(r"^\s*[-*]\s+\**(INV-[A-Z]{2,5}-\d{2,3})\**[:\s—–-]+(.*)$")
RULES_HEADING = "rules that must never break"
SCENARIOS_HEADING = "if you change"
SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", ".next", "coverage", "__pycache__",
             ".venv", "venv", "target", ".gradle", "docs", ".maestro", "codebase", "sandbox"}
TEXT_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".java", ".kt", ".rs",
            ".rb", ".php", ".cs", ".swift", ".dart", ".sql", ".yaml", ".yml", ".json", ".md",
            ".sh", ".toml", ".proto", ".graphql", ".vue", ".svelte", ".html", ".prisma", ".scala"}
MAX_BYTES = 1_000_000
LOCAL_CLAUDE_MD_MAX_LINES = 30
NAME_KINDS = (("tables", "table"), ("queues", "queue"), ("endpoints", "endpoint"),
              ("files", "file"), ("symbols", "symbol"))

STARTER = """\
# Change scenarios: "if you change X, also check Y". Optional: Maestro uses them when present.
# Each scenario also has a row in its domain page, docs/functional/<domain>.md, under
# "## If you change… also check". Rules that must never break go in the same page under
# "## Rules that must never break" as "- INV-<CODE>-<NN> one sentence". See Maestro's
# docs/domain-rules.md. Maestro's engine checks every name below still exists in the code.
#
# - id: CS-PL-01                     # CS-<domain code>-<number>
#   domain: payments                 # the docs/functional page it belongs to
#   summary: Disabling a payment link
#   rules: [INV-PL-01]               # rules at risk
#   repo: backend                    # default repository for the names below ("repo:name" overrides)
#   when_changing: ["internal/links/disable.go", "links.Service.Disable"]
#   also_impacts:
#     domains: [reminders]
#     tables: [payment_links]
#     queues: [payment.succeeded]
#     endpoints: ["GET /v1/links/{id}"]
#     files: ["web:src/screens/Links.tsx"]
#     symbols: []
#   verify: ["TestWebhookAfterDisable"]
version: 1
scenarios: []
"""


def _out(obj):
    print(json.dumps(obj))
    return 0


# --------------------------------------------------------------------------- the docs

def _section(text, prefix):
    """Body of the first `## ` section whose title starts with prefix, or None."""
    body, on, found = [], False, False
    for line in text.splitlines():
        if line.startswith("## "):
            if on:
                break
            on = line[3:].strip().lower().startswith(prefix)
            found = found or on
            continue
        if on:
            body.append(line)
    return "\n".join(body) if found else None


def load_pages(root, errors, warnings):
    """-> {domain: {"rules": {id: text}, "scenarios": [ids], "path", "code"}}"""
    pages = {}
    base = os.path.join(root, FUNCTIONAL)
    if not os.path.isdir(base):
        return pages
    for name in sorted(os.listdir(base)):
        if not name.endswith(".md"):
            continue
        rel = f"docs/functional/{name}"
        try:
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        rules, scen, codes = {}, [], set()
        for line in (_section(text, RULES_HEADING) or "").splitlines():
            m = RULE_LINE.match(line)
            if m:
                rid = m.group(1)
                if rid in rules:
                    errors.append(f"{rel}: duplicate rule id {rid}")
                rules[rid] = m.group(2).strip()
                codes.add(ID_RE.match(rid).group(2))
            elif "INV-" in line:
                errors.append(f"{rel}: malformed rule line (want '- INV-XX-01 text'): {line.strip()[:80]}")
        for line in (_section(text, SCENARIOS_HEADING) or "").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if not cells or not cells[0].startswith("CS-"):
                continue
            if not ID_RE.match(cells[0]):
                errors.append(f"{rel}: malformed scenario id {cells[0]}")
                continue
            if cells[0] in scen:
                errors.append(f"{rel}: duplicate scenario id {cells[0]}")
            scen.append(cells[0])
            codes.add(ID_RE.match(cells[0]).group(2))
        if len(codes) > 1:
            errors.append(f"{rel}: ids use more than one domain code {sorted(codes)}; one page, one code")
        pages[name[:-3]] = {"rules": rules, "scenarios": scen, "path": rel,
                            "code": sorted(codes)[0] if codes else None}
    owner = {}
    for dom, page in pages.items():
        if page["code"]:
            if page["code"] in owner:
                errors.append(f"domain code {page['code']} is used by both {owner[page['code']]} and {dom}")
            owner[page["code"]] = dom
    return pages


def load_side_effects(root, errors):
    """-> list of scenario dicts, or None when the file does not exist."""
    path = os.path.join(root, SIDE_EFFECTS)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = wf.loads(fh.read())
    except (OSError, wf.WfError) as exc:
        errors.append(f"{SIDE_EFFECTS}: not readable YAML: {exc}")
        return []
    items = doc.get("scenarios") if isinstance(doc, dict) else doc
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        errors.append(f"{SIDE_EFFECTS}: expected a 'scenarios:' list")
        return []
    return items


# --------------------------------------------------------------------------- the code

def _source_files(path):
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                full = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(full) <= MAX_BYTES:
                        yield os.path.relpath(full, path), full
                except OSError:
                    continue


class Code:
    """Every repository's source, read once: whole-word lookups and where each id is cited."""

    def __init__(self, repos):
        self.repos = dict(repos)
        self.files, self.cited, self.local_md = {}, {}, {}
        for name, path in self.repos.items():
            files = {}
            for rel, full in _source_files(path):
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                except OSError:
                    continue
                files[rel] = content
                if os.path.basename(rel) == "CLAUDE.md" and os.path.dirname(rel):
                    self.local_md[(name, rel)] = content.count("\n") + 1
                for m in RULE_RE.finditer(content):
                    self.cited.setdefault(m.group(0), set()).add((name, rel))
            self.files[name] = files

    def has_path(self, repo, rel):
        return os.path.exists(os.path.join(self.repos[repo], rel.lstrip("./")))

    def has_word(self, repo, word, source_only=True):
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])")
        return any(pat.search(c) for rel, c in self.files.get(repo, {}).items()
                   if not (source_only and rel.endswith(".md")))

    def has_literal(self, repo, word):
        """word just after a quote or slash: route segments, table and queue names."""
        pat = re.compile(r"""["'`/]""" + re.escape(word) + r"(?![A-Za-z0-9_])")
        return any(pat.search(c) for rel, c in self.files.get(repo, {}).items() if not rel.endswith(".md"))


def _file_like(text):
    return "/" in text or "\\" in text or os.path.splitext(text)[1].lower() in TEXT_EXT


def _check_name(kind, entry, default_repo, code, where, errors):
    entry = str(entry).strip()
    repo, thing = default_repo, entry
    if ":" in entry and not re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s", entry, re.I):
        head, tail = entry.split(":", 1)
        if head in code.repos:
            repo, thing = head, tail.strip()
    if repo is None:
        if len(code.repos) != 1:
            errors.append(f"{where}: '{entry}' needs a repository ('repo:{entry}' or the scenario's repo:)")
            return
        repo = next(iter(code.repos))
    if repo not in code.repos:
        errors.append(f"{where}: repository '{repo}' is not in this workspace")
        return
    if kind == "auto":
        kind = "file" if _file_like(thing) else "symbol"
    if kind == "file":
        if not code.has_path(repo, thing):
            errors.append(f"{where}: file '{thing}' no longer exists in {repo}")
    elif kind == "symbol":
        for part in [re.sub(r"\(.*\)$", "", p) for p in re.split(r"::|[.#]", thing) if p]:
            if part and not code.has_word(repo, part):
                errors.append(f"{where}: symbol '{thing}' ('{part}') no longer exists in {repo}")
                break
    elif kind in ("table", "queue"):
        if not (code.has_literal(repo, thing) or code.has_word(repo, thing)):
            errors.append(f"{where}: {kind} '{thing}' no longer appears in {repo}")
    elif kind == "endpoint":
        m = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)$", thing, re.I)
        if not m:
            errors.append(f"{where}: endpoint '{thing}' should look like 'GET /v1/things/{{id}}'")
            return
        for seg in m.group(2).split("/"):
            if seg and not seg.startswith(("{", ":", "<")) and not code.has_literal(repo, seg):
                errors.append(f"{where}: endpoint '{thing}' (segment '{seg}') no longer exists in {repo}")
                break
    elif kind == "test":
        if not (code.has_word(repo, thing) or code.has_literal(repo, thing)):
            errors.append(f"{where}: test '{thing}' no longer exists in {repo}")


# --------------------------------------------------------------------------- commands

def _repos(root, repo=None, worktree=None):
    repos = dict(codebase_scan.discover_repos(root))
    if repo:
        repos[repo] = os.path.abspath(worktree)
    return repos


def status(root):
    errors, warnings = [], []
    pages = load_pages(root, errors, warnings)
    items = load_side_effects(root, errors)
    rules = sum(len(p["rules"]) for p in pages.values())
    scen = len(items or [])
    present = bool(rules or scen)
    domains = sorted(d for d, p in pages.items() if p["rules"] or p["scenarios"])
    if present:
        summary = f"{rules} domain rules, {scen} change scenarios ({', '.join(domains) or 'no domain page'})"
    else:
        summary = ("no domain rules yet: add '## Rules that must never break' to docs/functional/<domain>.md "
                   "and scenarios to docs/impact/side-effects.yaml (optional)")
    return {"present": present, "rule_count": rules, "scenario_count": scen,
            "domains_csv": ",".join(domains), "side_effects": items is not None, "summary": summary}


def check(root, repo=None, worktree=None):
    errors, warnings = [], []
    pages = load_pages(root, errors, warnings)
    items = load_side_effects(root, errors)
    rules = {r: d for d, p in pages.items() for r in p["rules"]}
    in_pages = {s: d for d, p in pages.items() for s in p["scenarios"]}
    if not rules and not items and not in_pages:
        return {"present": False, "valid": True, "skipped": True, "error_count": 0, "warning_count": 0,
                "rule_count": 0, "scenario_count": 0, "issues_summary": "", "errors": [], "warnings": [],
                "summary": "no domain rules or change scenarios; skipped"}
    code = Code(_repos(root, repo, worktree))
    seen = set()
    for n, sc in enumerate(items or [], 1):
        sid = str(sc.get("id", "")) if isinstance(sc, dict) else ""
        where = f"{SIDE_EFFECTS} {sid or '#' + str(n)}"
        if not isinstance(sc, dict) or not sid.startswith("CS-") or not ID_RE.match(sid):
            errors.append(f"{where}: each scenario needs an id like CS-XX-01")
            continue
        if sid in seen:
            errors.append(f"{where}: duplicate scenario id")
        seen.add(sid)
        if sid not in in_pages:
            warnings.append(f"{where}: no row in a docs/functional page's 'If you change… also check' table")
        elif sc.get("domain") and sc.get("domain") != in_pages[sid]:
            errors.append(f"{where}: domain '{sc.get('domain')}' but its row is in docs/functional/{in_pages[sid]}.md")
        if not sc.get("when_changing"):
            errors.append(f"{where}: when_changing must name at least one file or symbol")
        for rid in sc.get("rules") or []:
            if rid not in rules:
                errors.append(f"{where}: cites rule {rid}, which no docs/functional page defines")
        also = sc.get("also_impacts") or {}
        if not isinstance(also, dict):
            errors.append(f"{where}: also_impacts must be a mapping")
            also = {}
        for dom in also.get("domains") or []:
            if dom not in pages:
                errors.append(f"{where}: also_impacts.domains '{dom}' has no docs/functional/{dom}.md")
        if not code.repos:
            continue
        default = sc.get("repo") or None
        for entry in sc.get("when_changing") or []:
            _check_name("auto", entry, default, code, where + " when_changing", errors)
        for key, kind in NAME_KINDS:
            for entry in also.get(key) or []:
                _check_name(kind, entry, default, code, f"{where} also_impacts.{key}", errors)
        for entry in sc.get("verify") or []:
            _check_name("test", entry, default, code, where + " verify", errors)
    for sid, dom in in_pages.items():
        if items is not None and sid not in seen:
            warnings.append(f"docs/functional/{dom}.md: {sid} has no entry in {SIDE_EFFECTS}")
    if code.repos:
        for rid, dom in sorted(rules.items()):
            locs = code.cited.get(rid, set())
            if not any(not rel.endswith(".md") for _r, rel in locs):
                errors.append(f"{pages[dom]['path']}: {rid} is not cited in any code or test; add "
                              f"'{rid}' as a comment where it is enforced, or remove the rule")
        for cid, locs in sorted(code.cited.items()):
            if cid not in rules and cid not in in_pages and cid not in seen:
                where = ", ".join(sorted(f"{r}:{p}" for r, p in locs)[:3])
                errors.append(f"{cid} is cited in {where}, but no doc defines it")
        for (name, rel), lines in sorted(code.local_md.items()):
            if lines > LOCAL_CLAUDE_MD_MAX_LINES:
                warnings.append(f"{name}:{rel} has {lines} lines; keep local CLAUDE.md files under "
                                f"{LOCAL_CLAUDE_MD_MAX_LINES}")
    else:
        warnings.append("no repositories found; checked the docs only")
    scen_count = len(seen | set(in_pages))
    summary = (f"{len(rules)} rules, {scen_count} scenarios: "
               + ("all names still exist" if not errors else f"{len(errors)} mismatch(es) with the code"))
    return {"present": True, "valid": not errors, "skipped": False, "error_count": len(errors),
            "warning_count": len(warnings), "rule_count": len(rules), "scenario_count": scen_count,
            "issues_summary": "; ".join(errors[:5]), "errors": errors, "warnings": warnings,
            "summary": summary}


def scaffold(root):
    path = os.path.join(root, SIDE_EFFECTS)
    if os.path.exists(path):
        return {"created": False, "path": SIDE_EFFECTS}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(STARTER)
    return {"created": True, "path": SIDE_EFFECTS}


def next_ids(root, code):
    pages = load_pages(root, [], [])
    items = load_side_effects(root, []) or []
    top = {"INV": 0, "CS": 0}
    ids = [r for p in pages.values() for r in list(p["rules"]) + p["scenarios"]]
    ids += [str(sc.get("id", "")) for sc in items if isinstance(sc, dict)]
    for rid in ids:
        m = ID_RE.match(rid)
        if m and m.group(2) == code:
            top[m.group(1)] = max(top[m.group(1)], int(m.group(3)))
    return {"rule": f"INV-{code}-{top['INV'] + 1:02d}", "scenario": f"CS-{code}-{top['CS'] + 1:02d}"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="domain_rules.py")
    ap.add_argument("command", choices=["status", "check", "scaffold", "next"])
    ap.add_argument("code", nargs="?", help="domain code, for next")
    ap.add_argument("--root", default=".")
    ap.add_argument("--repo", help="read this repository from --worktree instead of its checkout")
    ap.add_argument("--worktree")
    ap.add_argument("--out", help="also write the full check report (JSON) here")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.command == "status":
        return _out(status(root))
    if a.command == "scaffold":
        return _out(scaffold(root))
    if a.command == "next":
        if not a.code or not re.match(r"^[A-Za-z]{2,5}$", a.code):
            ap.error("next needs a 2-5 letter domain code, e.g. 'next PL'")
        return _out(next_ids(root, a.code.upper()))
    if bool(a.repo) != bool(a.worktree):
        ap.error("--repo and --worktree go together")
    if a.worktree and not os.path.isdir(a.worktree):
        a.repo = a.worktree = None  # no worktree yet: read the main checkout
    result = check(root, a.repo, a.worktree)
    report_path = ""
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        report_path = a.out
    line = {k: v for k, v in result.items() if k not in ("errors", "warnings")}
    line["report_path"] = report_path
    return _out(line)


if __name__ == "__main__":
    sys.exit(main())
