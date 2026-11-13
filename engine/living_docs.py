#!/usr/bin/env python3
"""Living docs, the deterministic half: check the format, generate what code already says.

The skills (build-knowledge, retrospect) write the JUDGEMENT in docs/ — business rules, invariants,
change scenarios, gotchas. This module owns everything a workflow relies on: the format rules,
the ID and anchor checks, the inventories extracted from code and contracts, the per-doc
`verified_at` stamp, and the cited-fact snippets steps load. Swapping a skill cannot change any
of it. Format: skills/core/bootstrap/build-knowledge/docs-format.md.

Commands (all take --root, default .):
  check    [--write] [--nightly] [--today YYYY-MM-DD] [--report]
           Rules R1–R8 below. --write first regenerates every generated file and block.
  extract  --out PATH        workspace-wide inventory (Markdown) for the writer to read
  snippet  IDS               one line per ID, as steps receive it (comma-separated IDs)
  cited    --from PATH... --out PATH [--repos a,b]   the rows behind every ID the given files
           cite (missing files are skipped); with --repos, also those repos' domain doc paths
  domains  [--repos a,b] [--impact impact.json]   the domains (and their doc paths) whose Domain
           map row names one of the repos; every domain when none is named or none matches
  snapshot --out PATH        hash every doc, and keep the team-owned content, before a writer runs
  stamp    [--snapshot PATH] set verified_at (and status: draft) on docs new or changed since
  status                     are there team-owned invariants and change scenarios?
  rules    [--repo R --worktree W] [--out F]   the team's rules and scenarios against the code
           (a feature's worktree for R); never blocks: a review step reads it
  scaffold                   write a starter docs/impact/side-effects.yaml (never overwrites)
  next     PREFIX            the next free BR, INV and CS number for a domain

Rules: R1 ID format, prefix, kind, uniqueness · R2 every cited ID is defined · R3 every
`repo · path · symbol` anchor resolves · R4 generated output is current and not hand-edited ·
R5 anchored code changed since verified_at (warning; error after 30 days with --nightly) ·
R6 every app call reaches a served route · R7 structure: front-matter, headings, table columns,
owned unknowns, rows that stand alone, Domain map ↔ files · R8 token budgets (warning) ·
R9 (with --locked-from) a writer changed team-owned content: the engine restores it.

Team-owned: invariants (INV) and change scenarios (CS) — technical docs' "Invariants and
consistency" and "Change scenarios", architecture's "Platform-wide invariants", and
docs/impact/side-effects.yaml. People write them; a model only proposes, under "Proposed rules
and scenarios". In a writer's check, a problem inside team-owned content is a warning for the team.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codebase_scan  # noqa: E402
import wf  # noqa: E402

FORMAT_VERSION = "2.3"
ID_KINDS = ("BR", "INV", "CS")
ARCH_PREFIX = "ARCH"
PREFIX_RE = r"[A-Z][A-Z0-9]{1,5}"
ANY_ID_RE = re.compile(rf"\b({PREFIX_RE})-([A-Z]{{2,4}})-(\d+)\b")
ANCHOR_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9][\w.-]*) · ([^\s·|`]+) · ([A-Za-z_$][\w.$-]*)")
UNKNOWN_OK = re.compile(r"Unknown\. \(ask: [^,()]+, since \d{4}-\d{2}-\d{2}\)")
PRONOUN_RE = re.compile(r"^(It|This|They|That|These|Those|Its|Their)\b")
RETIRED_RE = re.compile(r"^Retired\b", re.I)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LINK_RE = re.compile(r"\]\(([^)#\s]+)")

FORMAT = {
    "architecture": {
        "required": ["System context and repos", "Domain map", "Cross-repo flows and contracts",
                     "Platform-wide invariants"],
        "order": ["System context and repos", "Domain map", "Cross-repo flows and contracts",
                  "Platform-wide invariants", "Proposed rules and scenarios",
                  "Conventions and boundaries", "Glossary and aliases"],
    },
    "functional": {
        "required": ["Purpose and actors", "Business rules", "Open questions and owned unknowns"],
        "order": ["Purpose and actors", "Glossary and aliases", "Business rules", "States and flows",
                  "Open questions and owned unknowns"],
    },
    "technical": {
        "required": ["Invariants and consistency", "Change scenarios", "Cross-repo connections",
                     "Known gaps and tech debt"],
        "order": ["Invariants and consistency", "Change scenarios", "Proposed rules and scenarios",
                  "Cross-repo connections", "Failure, concurrency and idempotency", "Gotchas",
                  "Known gaps and tech debt"],
    },
}
# The first table of these sections must carry exactly these columns (case-insensitive).
TABLE_COLUMNS = {
    ("architecture", "System context and repos"):
        ["Repo or provider", "Kind", "Purpose", "Owns data", "Runs on"],
    ("architecture", "Domain map"): ["Domain", "Purpose", "Repos", "Owner", "Technical", "Functional"],
    ("architecture", "Cross-repo flows and contracts"):
        ["From", "To", "Operation / event", "Protocol", "Sync", "Auth", "Contract"],
    ("architecture", "Platform-wide invariants"):
        ["ID", "Invariant", "Where (repo · path · symbol)", "Consistency"],
    ("architecture", "Glossary and aliases"):
        ["Term", "Meaning", "Code names and aliases", "Not to be confused with"],
    ("functional", "Glossary and aliases"):
        ["Term", "Meaning", "Code names and aliases", "Not to be confused with"],
    ("functional", "Business rules"): ["ID", "Rule", "Edge", "Why / source"],
    ("functional", "States and flows"): ["From", "To", "Trigger", "Actor", "Guard"],
    ("technical", "Invariants and consistency"):
        ["ID", "Invariant", "Enforces", "Where (repo · path · symbol)", "Consistency", "Tested by"],
    ("technical", "Change scenarios"): ["ID", "When changing", "Also affects", "Verify with", "Source"],
    ("architecture", "Proposed rules and scenarios"):
        ["Kind", "Proposal", "Where (repo · path · symbol)", "Evidence"],
    ("technical", "Proposed rules and scenarios"):
        ["Kind", "Proposal", "Where (repo · path · symbol)", "Evidence"],
}
# Owned by the project's people, never by a model: invariants and change scenarios. A writer step
# that changes them fails its check (R9) and the engine puts the snapshot text back; a model
# writes what it finds under "Proposed rules and scenarios" for the team to accept.
TEAM_SECTIONS = {
    "architecture": ("Platform-wide invariants",),
    "functional": (),
    "technical": ("Invariants and consistency", "Change scenarios"),
}
PROPOSALS = "Proposed rules and scenarios"
PROPOSAL_KINDS = ("invariant", "change scenario")
SIDE_EFFECTS = os.path.join("docs", "impact", "side-effects.yaml")
SOURCE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".java", ".kt", ".rs",
              ".rb", ".php", ".cs", ".swift", ".dart", ".sql", ".yaml", ".yml", ".json", ".sh",
              ".toml", ".proto", ".graphql", ".vue", ".svelte", ".html", ".prisma", ".scala", ".tf"}
SIDE_EFFECT_NAMES = (("tables", "table"), ("queues", "queue"), ("endpoints", "endpoint"),
                     ("files", "file"), ("symbols", "symbol"))
# Which ID kinds each doc may define, and in which section.
DEFINES = {
    "architecture": {"INV": "Platform-wide invariants"},
    "functional": {"BR": "Business rules"},
    "technical": {"INV": "Invariants and consistency", "CS": "Change scenarios"},
}
FM_KEYS = {
    "architecture": ["doc", "id_prefix", "owner", "repos", "verified_at", "reviewed", "status"],
    "functional": ["doc", "domain", "id_prefix", "owner", "repos", "verified_at", "reviewed", "status"],
    "technical": ["doc", "domain", "id_prefix", "owner", "repos", "code_roots", "verified_at",
                  "reviewed", "status"],
}
STATUSES = ("draft", "verified")
BUDGET = {"architecture": 3000, "functional": 2000, "technical": 2500}
STALE_DAYS = 30

GEN_DIR = "_generated"
INDEX_DIR = "_index"
CONNECTIONS = "connections"
FACTS = "facts"
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
INVENTORY_SECTIONS = ("APIs", "Events", "Jobs", "Data", "Config")


def block_markers(name, source):
    return (f"<!-- generated:{name} begin; from {source} by living_docs.py; do not edit -->",
            f"<!-- generated:{name} end -->")


def block_re(name):
    return re.compile(rf"<!-- generated:{name} begin[^>]*-->\n(.*?)<!-- generated:{name} end -->",
                      re.S)


class Report:
    """Errors and warnings. With `locked` (a writer's check), a problem inside team-owned content
    is a warning for the team: the writer may not edit that content, so it cannot fix it."""

    def __init__(self, locked=False):
        self.errors, self.warnings, self.locked = [], [], locked

    def err(self, rule, where, msg, fix, team=False):
        if team and self.locked:
            self.warnings.append(f"{rule} {where}: {msg} (team-owned; the team should: {fix})")
        else:
            self.errors.append(f"{rule} {where}: {msg}. Fix: {fix}")

    def warn(self, rule, where, msg):
        self.warnings.append(f"{rule} {where}: {msg}")


# --------------------------------------------------------------------------- git and files

def _git(repo, *args, timeout=60):
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              timeout=timeout)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _head(repo, short=12):
    rc, out = _git(repo, "rev-parse", f"--short={short}", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


SKIP_DIRS = {"node_modules", "vendor", "third_party", "dist", "build", ".git", ".dart_tool",
             "__pycache__", ".venv", "venv", "target", ".next", "Pods", ".maestro"}
MAX_FILE_BYTES = 512 * 1024


def repo_files(repo):
    """Tracked and new (not ignored) files of a repo, repo-relative, sorted; vendored dirs skipped."""
    rc, out = _git(repo, "ls-files", "-co", "--exclude-standard", "-z")
    if rc != 0:
        names = []
        for base, dirs, files in os.walk(repo):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            names += [os.path.relpath(os.path.join(base, f), repo) for f in files]
    else:
        names = [n for n in out.split("\0") if n]
    keep = []
    for name in sorted(set(names)):
        if any(part in SKIP_DIRS for part in name.split("/")[:-1]):
            continue
        keep.append(name)
    return keep


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- docs

class Doc:
    """One living doc: front-matter, sections (ignoring fenced code), tables and bullets."""

    def __init__(self, path, root, kind):
        self.path = path
        self.rel = os.path.relpath(path, os.path.join(root, "docs"))
        self.kind = kind
        with open(path, encoding="utf-8") as fh:
            self.text = fh.read()
        self.fm, self.fm_error, self.body = {}, None, self.text
        match = re.match(r"---\n(.*?)\n---\n", self.text, re.S)
        if match:
            try:
                loaded = wf.loads(match.group(1))
                self.fm = loaded if isinstance(loaded, dict) else {}
            except Exception as exc:  # wf raises its own error types
                self.fm_error = str(exc)
            self.body = self.text[match.end():]
        self.domain = self.fm.get("domain") if kind != "architecture" else None
        self.prefix = str(self.fm.get("id_prefix") or "")
        self.sections, self.headings, self.line_section = {}, [], []
        current, fenced = None, False
        offset = self.text[:len(self.text) - len(self.body)].count("\n")
        self.line_section = [None] * offset
        for line in self.body.split("\n"):
            if FENCE_RE.match(line):
                fenced = not fenced
            if not fenced and line.startswith("## "):
                current = line[3:].strip()
                self.headings.append(current)
                self.sections.setdefault(current, [])
            elif current is not None:
                self.sections[current].append("" if fenced else line)
            self.line_section.append(current)

    def is_team(self, section):
        return section in TEAM_SECTIONS.get(self.kind, ())

    def team_line(self, number):
        """True when 1-based line `number` lies in a team-owned section."""
        index = number - 1
        return 0 <= index < len(self.line_section) and self.is_team(self.line_section[index])

    def section_text(self, section):
        """The section's body as written (fences kept), trimmed; None when the heading is absent."""
        if section not in self.sections:
            return None
        lines, on, fenced = [], False, False
        for line in self.body.split("\n"):
            if FENCE_RE.match(line):
                fenced = not fenced
            if not fenced and line.startswith("## "):
                on = line[3:].strip() == section
                continue
            if on:
                lines.append(line.rstrip())
        return "\n".join(lines).strip("\n")

    def tables(self, section):
        out, lines, i = [], self.sections.get(section, []), 0
        while i < len(lines):
            if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"\|\s*:?-", lines[i + 1]):
                header = _cells(lines[i])
                i += 2
                rows = []
                while i < len(lines) and lines[i].startswith("|"):
                    rows.append(_cells(lines[i]))
                    i += 1
                out.append((header, rows))
            else:
                i += 1
        return out

    def items(self):
        """(section, header|None, row cells | bullet text) for every table row and bullet."""
        for section in self.headings:
            for header, rows in self.tables(section):
                for row in rows:
                    yield section, header, row
            for line in self.sections.get(section, []):
                if line.startswith("- "):
                    yield section, None, line[2:]


def _cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def load_docs(root):
    docs = []
    arch = os.path.join(root, "docs", "architecture.md")
    if os.path.isfile(arch):
        docs.append(Doc(arch, root, "architecture"))
    for kind in ("functional", "technical"):
        folder = os.path.join(root, "docs", kind)
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".md"):
                    docs.append(Doc(os.path.join(folder, name), root, kind))
    return docs


def current_format(root):
    """True when every written doc carries v2.3 front-matter (a `doc:` key)."""
    docs = load_docs(root)
    return bool(docs) and all(d.fm.get("doc") == d.kind for d in docs)


def known_prefixes(docs):
    return {ARCH_PREFIX} | {d.prefix for d in docs if d.prefix}


def id_re(prefixes):
    alt = "|".join(sorted((re.escape(p) for p in prefixes), key=len, reverse=True)) or ARCH_PREFIX
    return re.compile(rf"\b(?:{alt})-(?:{'|'.join(ID_KINDS)})-\d{{3}}\b")


# --------------------------------------------------------------------------- R7 structure, R8

def check_structure(doc, repos, report):
    kind = doc.kind
    if doc.fm_error:
        report.err("R7", doc.rel, f"front-matter does not parse ({doc.fm_error})",
                   "write the front-matter as plain YAML between the --- lines")
    for key in FM_KEYS[kind]:
        if key not in doc.fm:
            report.err("R7", doc.rel, f"front-matter has no '{key}'",
                       f"add '{key}:' (see docs-format.md)")
    if doc.fm.get("doc") not in (None, kind):
        report.err("R7", doc.rel, f"front-matter says doc: {doc.fm.get('doc')} but the file is a "
                   f"{kind} doc", f"set doc: {kind}")
    if "status" in doc.fm and doc.fm.get("status") not in STATUSES:
        report.err("R7", doc.rel, f"status must be one of {', '.join(STATUSES)}",
                   "write draft; a person sets verified after reviewing the doc")
    stem = os.path.splitext(os.path.basename(doc.path))[0]
    if kind != "architecture" and doc.domain and doc.domain != stem:
        report.err("R7", doc.rel, f"domain: {doc.domain} does not match the file name",
                   f"name the file {doc.domain}.md or fix domain:")
    if kind == "architecture" and doc.prefix and doc.prefix != ARCH_PREFIX:
        report.err("R7", doc.rel, f"architecture's id_prefix must be {ARCH_PREFIX}",
                   f"set id_prefix: {ARCH_PREFIX}")
    if kind != "architecture" and doc.prefix and not re.fullmatch(PREFIX_RE, doc.prefix):
        report.err("R7", doc.rel, f"id_prefix {doc.prefix} is not 2–6 capitals",
                   "use a short capital prefix such as PL")
    listed = doc.fm.get("repos") or []
    if not isinstance(listed, list):
        report.err("R7", doc.rel, "repos must be a list", "write repos: [name, …]")
        listed = []
    for name in listed:
        if name not in repos:
            report.err("R7", doc.rel, f"repos lists {name}, which is not a repository in this "
                       "workspace", f"use one of: {', '.join(sorted(repos)) or 'none found'}")
    for code_root in doc.fm.get("code_roots") or []:
        if str(code_root).split("/")[0] not in repos:
            report.err("R7", doc.rel, f"code_roots entry {code_root} does not start with a repository",
                       "write <repo>/<path>")
    fmt = FORMAT[kind]
    allowed = fmt["order"]
    for heading in fmt["required"]:
        if heading not in doc.sections:
            report.err("R7", doc.rel, f"required section '{heading}' is missing",
                       f"add '## {heading}'; write None. if there is nothing to say")
    for heading in doc.headings:
        if heading not in allowed:
            report.err("R7", doc.rel, f"section '{heading}' is not in the format",
                       f"move its content into one of: {', '.join(allowed)}")
    present = [h for h in doc.headings if h in allowed]
    if present != [h for h in allowed if h in present]:
        report.err("R7", doc.rel, "sections are out of order", "use the order " + " · ".join(allowed))
    if len(present) != len(set(present)):
        report.err("R7", doc.rel, "a section heading appears twice", "merge the two sections")
    for section in doc.headings:
        expected = TABLE_COLUMNS.get((kind, section))
        tables = doc.tables(section)
        if expected and tables:
            header = tables[0][0]
            if [h.lower() for h in header] != [h.lower() for h in expected]:
                report.err("R7", f"{doc.rel} §{section}", "table columns are "
                           f"{' | '.join(header)}", "use the columns " + " | ".join(expected),
                           team=doc.is_team(section))
        if section in fmt["required"] and not tables and not any(
                line.strip() for line in doc.sections.get(section, [])):
            report.err("R7", f"{doc.rel} §{section}", "section is empty",
                       "write the content, or None. when there is nothing to say")
    for number, line in enumerate(doc.text.split("\n"), 1):
        if "Unknown." in line and line.count("Unknown.") != len(UNKNOWN_OK.findall(line)):
            report.err("R7", f"{doc.rel}:{number}", "an Unknown. has no owner or date",
                       "write Unknown. (ask: <who>, since <YYYY-MM-DD>)", team=doc.team_line(number))
    for section, header, item in doc.items():
        first = item[0] if header else item
        if (header and not first) or PRONOUN_RE.match(first or ""):
            report.err("R7", f"{doc.rel} §{section}", f"row does not name its subject: "
                       f"{(' | '.join(item) if header else item)[:70]}",
                       "start the row with the thing it is about, so it reads on its own",
                       team=doc.is_team(section))
        if section == PROPOSALS and header and first.lower() not in PROPOSAL_KINDS:
            report.err("R7", f"{doc.rel} §{section}", f"proposal kind '{first}'",
                       f"write one of: {', '.join(PROPOSAL_KINDS)}")
    tokens = len(doc.text) // 4
    if tokens > BUDGET[kind]:
        report.warn("R8", doc.rel, f"about {tokens} tokens, budget {BUDGET[kind]}; cut anything an "
                    "agent can find in code, or split the domain")
    return tokens


def domain_map(arch):
    """[{domain, repos[], technical, functional}] from architecture's Domain map table."""
    rows = []
    if not arch:
        return rows
    for header, table_rows in arch.tables("Domain map")[:1]:
        names = [h.lower() for h in header]
        for row in table_rows:
            cell = dict(zip(names, row + [""] * (len(names) - len(row))))
            links = {key: (LINK_RE.search(cell.get(key, "")) or [None, None])[1]
                     for key in ("technical", "functional")}
            rows.append({
                "domain": cell.get("domain", ""),
                "repos": [r.strip() for r in re.split(r"[,;]", cell.get("repos", "")) if r.strip()],
                "technical": links["technical"],
                "functional": links["functional"],
            })
    return rows


def check_domain_map(root, docs, report):
    arch = next((d for d in docs if d.kind == "architecture"), None)
    if not arch:
        report.err("R7", "architecture.md", "docs/architecture.md is missing",
                   "write it; every other doc is reached from its Domain map")
        return
    listed = set()
    for row in domain_map(arch):
        for kind in ("technical", "functional"):
            link = row[kind]
            if not link:
                report.err("R7", "architecture.md §Domain map", f"{row['domain']} has no {kind} link",
                           f"link {kind}/{row['domain']}.md")
                continue
            target = os.path.normpath(os.path.join(root, "docs", link))
            listed.add(target)
            if not os.path.isfile(target):
                report.err("R7", "architecture.md §Domain map", f"{row['domain']} links {link}, "
                           "which does not exist", "write the doc, or fix the link")
    for doc in docs:
        if doc.kind != "architecture" and os.path.normpath(doc.path) not in listed:
            report.err("R7", doc.rel, "this doc has no row in architecture's Domain map",
                       "add a Domain map row linking both of the domain's docs")
    names = {(d.kind, os.path.basename(d.path)) for d in docs if d.kind != "architecture"}
    for kind, other in (("functional", "technical"), ("technical", "functional")):
        for k, name in sorted(names):
            if k == kind and (other, name) not in names:
                report.err("R7", f"{kind}/{name}", f"the domain has no {other} doc",
                           f"write {other}/{name}; every domain has both")
    prefixes = {}
    for doc in docs:
        if doc.kind != "architecture" and doc.prefix and doc.domain:
            owner = prefixes.setdefault(doc.prefix, doc.domain)
            if owner != doc.domain:
                report.err("R7", doc.rel, f"id_prefix {doc.prefix} is also used by domain {owner}",
                           "give each domain its own prefix")


# --------------------------------------------------------------------------- R1 IDs, R2 citations

def collect_ids(docs, report):
    """{id: (doc, section, header, row)} for every ID a doc defines."""
    prefixes = known_prefixes(docs)
    defs = {}
    for doc in docs:
        for number, line in enumerate(doc.text.split("\n"), 1):
            for prefix, kind, digits in ANY_ID_RE.findall(line):
                if prefix not in prefixes:
                    continue
                token = f"{prefix}-{kind}-{digits}"
                team = doc.team_line(number)
                if kind not in ID_KINDS:
                    report.err("R1", f"{doc.rel}:{number}", f"{token} uses an ID kind that does not "
                               "exist", "only BR, INV and CS take IDs; make it a plain bullet",
                               team=team)
                elif len(digits) != 3:
                    report.err("R1", f"{doc.rel}:{number}", f"{token} is not three digits",
                               f"write {prefix}-{kind}-{int(digits):03d}", team=team)
        for section, header, row in doc.items():
            if not header or not re.fullmatch(rf"{PREFIX_RE}-(?:{'|'.join(ID_KINDS)})-\d{{3}}", row[0]):
                continue
            ident = row[0]
            prefix, kind, _ = ident.split("-")
            team = doc.is_team(section)
            if section == PROPOSALS:
                report.err("R1", f"{doc.rel} §{section}", f"{ident} gives a proposal an ID",
                           "leave proposals without an ID; the team numbers a rule when it accepts it")
                continue
            if ident in defs:
                report.err("R1", doc.rel, f"{ident} is defined twice (also in {defs[ident][0].rel})",
                           "give the new fact the next free number; never reuse an ID", team=team)
                continue
            if prefix != doc.prefix:
                report.err("R1", doc.rel, f"{ident} does not use this doc's prefix {doc.prefix}",
                           "define it in the doc that owns that prefix", team=team)
            allowed = DEFINES[doc.kind]
            if kind not in allowed or allowed[kind] != section:
                where = ", ".join(f"{k} in §{s}" for k, s in allowed.items())
                report.err("R1", f"{doc.rel} §{section}", f"{ident} is defined in the wrong place",
                           f"a {doc.kind} doc defines {where}", team=team)
            defs[ident] = (doc, section, header, row)
    return defs


def code_citations(repos, pattern):
    """[(repo, path, line number, line)] for every line of code or tests that cites an ID.
    Markdown and anything under docs/ do not count: a rule is cited where code enforces it."""
    grep = pattern.pattern.replace(r"\b", "").replace("(?:", "(").replace(r"\d{3}", "[0-9]{3}")
    hits = []
    for name, path in sorted(repos.items()):
        rc, out = _git(path, "grep", "-n", "-I", "-E", "--untracked", grep)
        if rc not in (0, 1):
            continue
        for hit in out.splitlines():
            file_part, _, rest = hit.partition(":")
            number, _, line = rest.partition(":")
            parts = file_part.split("/")
            if any(part in SKIP_DIRS for part in parts) or parts[0] == "docs" or file_part.endswith(".md"):
                continue
            hits.append((name, file_part, number, line))
    return hits


def check_citations(root, repos, docs, defs, report):
    pattern = id_re(known_prefixes(docs))
    sources = [(d.path, d.rel) for d in docs]
    runs = os.path.join(root, ".maestro", "runs")
    if os.path.isdir(runs):
        for base, dirs, files in os.walk(runs):
            # a run's .engine/ holds generated copies (cited facts, briefs), not documents
            dirs[:] = sorted(d for d in dirs if d != ".engine")
            for name in sorted(files):
                if name.endswith(".md"):
                    path = os.path.join(base, name)
                    sources.append((path, os.path.relpath(path, root)))
    for path, label in sources:
        text = read_text(path) or ""
        for number, line in enumerate(text.split("\n"), 1):
            for ident in pattern.findall(line):
                if ident not in defs:
                    report.err("R2", f"{label}:{number}", f"{ident} is cited but never defined",
                               "define it, or correct the citation")
    cited_in_code = set()
    for name, file_part, number, line in code_citations(repos, pattern):
        for ident in pattern.findall(line):
            cited_in_code.add(ident)
            if ident not in defs:
                report.err("R2", f"{name}/{file_part}:{number}", f"{ident} is cited but never "
                           "defined", "define it in the docs, or correct the comment")
    check_rules_cited(defs, cited_in_code, report)
    return cited_in_code


def check_rules_cited(defs, cited_in_code, report):
    """Every live invariant is cited where code or a test enforces it (`// PL-INV-001: why`)."""
    for ident, (doc, _section, _header, _row) in sorted(defs.items()):
        if "-INV-" in ident and not is_retired(defs, ident) and ident not in cited_in_code:
            report.warn("R2", doc.rel, f"{ident} is cited in no code or test; the team should add "
                        f"`{ident}: why` as a comment where it is enforced, or in its test's name")


def is_retired(defs, ident):
    _doc, _section, _header, row = defs[ident]
    return len(row) > 1 and bool(RETIRED_RE.match(row[1]))


def snippet(defs, ident):
    doc, section, header, row = defs[ident]
    parts = [f"{h}: {v}" for h, v in zip(header[1:], row[1:]) if v and v != "None."]
    return f"{ident} ({doc.rel} · {section}) " + " · ".join(parts)


# --------------------------------------------------------------------------- R3 anchors

def anchors_in(text, repos):
    """(repo, path, symbol) triples that look like anchors: a known repo, or a path-like middle."""
    found = []
    for repo, path, symbol in ANCHOR_RE.findall(text):
        if repo in repos or "/" in path or "." in path:
            found.append((repo, path.rstrip(".,;:"), symbol.rstrip(".,;:")))
    return found


def resolve_anchor(repos, repo, path, symbol, cache):
    if repo not in repos:
        return f"unknown repository {repo}"
    full = os.path.join(repos[repo], path)
    key = (repo, path)
    if key not in cache:
        if os.path.isdir(full):
            prefix = path.rstrip("/") + "/"
            blob = []
            for name in repo_files(repos[repo]):
                if name.startswith(prefix):
                    blob.append(read_text(os.path.join(repos[repo], name)) or "")
                    if len(blob) > 2000:
                        break
            cache[key] = "\n".join(blob)
        elif os.path.isfile(full):
            cache[key] = read_text(full) or ""
        else:
            cache[key] = None
    blob = cache[key]
    if blob is None:
        return f"{path} does not exist"
    for part in [p for p in symbol.split(".") if p]:
        if not re.search(rf"(?<![\w$]){re.escape(part)}(?![\w$])", blob):
            return f"symbol {part} not found in {path}"
    return None


def collect_anchors(repos, docs, defs, report):
    """{anchor key: {IDs}}, {doc rel: {anchor keys}}; reports R3 for anchors that do not resolve."""
    anchors, by_doc, cache = {}, {}, {}
    for doc in docs:
        by_doc.setdefault(doc.rel, set())
        for section, header, item in doc.items():
            text = " | ".join(item) if header else item
            label = item[0] if header and item and item[0] in defs else None
            cited = set(re.findall(rf"\b{PREFIX_RE}-(?:{'|'.join(ID_KINDS)})-\d{{3}}\b", text))
            ids = ({label} if label else set()) | {i for i in cited if i in defs}
            for repo, path, symbol in anchors_in(text, repos):
                key = f"{repo} · {path} · {symbol}"
                problem = resolve_anchor(repos, repo, path, symbol, cache)
                if problem:
                    report.err("R3", f"{doc.rel} §{section}", f"{key}: {problem}",
                               "point the anchor at the symbol's current repo, path and name",
                               team=doc.is_team(section))
                anchors.setdefault(key, set()).update(ids)
                by_doc[doc.rel].add(key)
    return anchors, by_doc


# --------------------------------------------------------------------------- extraction

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
LANG_BY_EXT = {
    ".go": "go", ".py": "python", ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".mjs": "js", ".cjs": "js", ".vue": "js", ".dart": "dart", ".java": "java", ".kt": "java",
}
_M = "GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete|get|post|put|patch|delete"
# Built-in, best-effort patterns per language. Named groups: method, path, symbol, name,
# schedule, key, default. A project adds its own in maestro.config.yaml `docs.extract`.
BUILTIN_PATTERNS = {
    "go": [
        ("route", r'\.(?:Handle|HandleFunc)\(\s*"(?P<method>GET|POST|PUT|PATCH|DELETE) (?P<path>/[^"]*)"\s*,\s*(?:\w+\.)*(?P<symbol>\w+)'),
        ("route", rf'\b\w+\.(?P<method>{_M})\(\s*"(?P<path>/[^"]*)"\s*,\s*(?:\w+\.)*(?P<symbol>\w+)'),
        ("event_out", r'\bPublish\(\s*\w+\s*,\s*"(?P<name>[\w.:/-]+)"'),
        ("event_in", r'\bSubscribe\(\s*\w+\s*,\s*"(?P<name>[\w.:/-]+)"'),
        ("job", r'\bRegister\(\s*"(?P<name>[\w.-]+)"\s*,\s*"(?P<schedule>[^"]+)"\s*,\s*[\w.{}()]*?(?P<symbol>\w+)\s*\)'),
        ("job", r'\bAddFunc\(\s*"(?P<schedule>[^"]+)"\s*,\s*(?:\w+\.)*(?P<symbol>\w+)'),
        ("config", r'(?P<symbol>\w+)\s+[\w.\[\]*]+\s+`[^`]*\benv:"(?P<key>[A-Z][A-Z0-9_]*)[^"]*"(?:[^`]*\b(?:envDefault|default):"(?P<default>[^"]*)")?'),
        ("config", r'\bos\.(?:Getenv|LookupEnv)\(\s*"(?P<key>[A-Z][A-Z0-9_]*)"'),
    ],
    "python": [
        ("route", r'^[ \t]*@\w+(?:\.\w+)*\.(?P<method>get|post|put|patch|delete)\(\s*[rf]?["\'](?P<path>/[^"\']*)'),
        ("route", r'^[ \t]*@\w+(?:\.\w+)*\.route\(\s*[rf]?["\'](?P<path>/[^"\']*)["\'](?:[^)]*methods\s*=\s*[\[(]\s*["\'](?P<method>\w+))?'),
        ("call", r'\b(?:requests|httpx|client|session|self\.client|self\.session)\.(?P<method>get|post|put|patch|delete)\(\s*f?["\'][^"\'/]*?(?P<path>/[^"\']*)'),
        ("config", r'\bos\.(?:environ\.get|getenv)\(\s*["\'](?P<key>[A-Z][A-Z0-9_]*)["\'](?:\s*,\s*["\'](?P<default>[^"\']*))?'),
        ("config", r'\bos\.environ\[\s*["\'](?P<key>[A-Z][A-Z0-9_]*)["\']\s*\]'),
    ],
    "js": [
        ("route", r'\b(?:app|router|server|api|fastify)\.(?P<method>get|post|put|patch|delete)\(\s*[`\'"](?P<path>/[^`\'"]*)[`\'"]\s*,\s*(?:[\w$]+\.)*(?P<symbol>[\w$]+)?'),
        ("call", r'\b(?:axios|api|client|http|this\.http)\.(?P<method>get|post|put|patch|delete)\(\s*[`\'"](?:\$\{[^}]+\})?(?P<path>/[^`\'"]*)'),
        ("call", r'\bfetch\(\s*[`\'"](?:\$\{[^}]+\})?(?P<path>/[^`\'"]*)[`\'"](?:\s*,\s*\{[^}]*?method:\s*[\'"](?P<method>\w+))?'),
        ("config", r'\bprocess\.env\.(?P<key>[A-Z][A-Z0-9_]*)'),
        ("config", r'\bimport\.meta\.env\.(?P<key>[A-Z][A-Z0-9_]*)'),
    ],
    "dart": [
        ("call", r'\b(?:http|dio|client|_client|_http|_dio|api|_api)\.(?P<method>get|post|put|patch|delete)\(\s*(?:Uri\.parse\(\s*)?[\'"](?:\$\{?\w+\}?)?(?P<path>/[^\'"]*)'),
    ],
    "java": [
        ("route", r'@(?P<method>Get|Post|Put|Patch|Delete)Mapping\(\s*(?:(?:value|path)\s*=\s*)?\{?\s*"(?P<path>/[^"]*)"'),
        ("config", r'@Value\(\s*"\$\{(?P<key>[\w.-]+)(?::(?P<default>[^}]*))?\}"'),
    ],
}
CUSTOM_KINDS = {
    "route": {"path"}, "call": {"path"}, "event_out": {"name"}, "event_in": {"name"},
    "job": {"schedule"}, "config": {"key"}, "table": {"name"},
}
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "async", "await", "new",
            "else", "try", "do", "with", "elif", "and", "or", "not", "lambda"}
DECLS = {
    "go": [re.compile(r"^func (?:\(\w+ \*?(?P<owner>\w+)(?:\[[^\]]*\])?\) )?(?P<name>\w+)\s*[\[(]"),
           re.compile(r"^type (?P<name>\w+) struct\b")],
    "python": [re.compile(r"^(?P<indent>\s*)(?:async\s+)?def (?P<name>\w+)\s*\("),
               re.compile(r"^(?P<indent>\s*)class (?P<name>\w+)\b")],
    "js": [re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>[\w$]+)\s*\("),
           re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[\w$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>"),
           re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*(?P<name>[\w$]+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{")],
    "dart": [re.compile(r"^\s*(?:static\s+)?(?:[\w<>?,\[\]]+\s+)+(?P<name>\w+)\s*\([^)]*\)\s*(?:async\s*)?(?:=>|\{)"),
             re.compile(r"^\s*(?:abstract\s+)?class (?P<name>\w+)\b")],
    "java": [re.compile(r"^\s*(?:@\w+\s+)*(?:public|private|protected|static|final|override|suspend|open|\s)*\s*(?:fun\s+(?P<kname>\w+)|[\w<>\[\],? ]+\s+(?P<name>\w+))\s*\([^)]*\)[^;]*$")],
}


def _decl_name(lang, line):
    for pattern in DECLS.get(lang, []):
        match = pattern.match(line)
        if match:
            groups = match.groupdict()
            name = groups.get("name") or groups.get("kname")
            if not name or name in KEYWORDS:
                continue
            owner = groups.get("owner")
            return f"{owner}.{name}" if owner else name, pattern
    return None, None


def enclosing_symbol(lang, lines, index, forward=False):
    """The function (or struct, for a Go field) around line `index`; forward for decorators."""
    if forward:
        for line in lines[index + 1:index + 10]:
            name, _ = _decl_name(lang, line)
            if name:
                return name
        return None
    for i in range(index, -1, -1):
        name, pattern = _decl_name(lang, lines[i])
        if name:
            if lang == "python":
                indent = len(re.match(r"\s*", lines[i]).group(0))
                for j in range(i - 1, -1, -1):
                    cls = re.match(r"^(\s*)class (\w+)\b", lines[j])
                    if cls and len(cls.group(1)) < indent:
                        return f"{cls.group(2)}.{name}"
            return name
    return None


def _anchor(repo, path, symbol):
    return f"{repo} · {path} · {symbol}"


def norm_path(path):
    """Route matching key: params as {}, no trailing slash, no query."""
    path = path.split("?")[0].rstrip("/") or "/"
    segments = []
    for seg in path.split("/"):
        if re.fullmatch(r"\{[^}]*\}|:\w+|<[^>]*>|\$\{?\w+\}?|\*", seg):
            seg = "{}"
        segments.append(seg)
    return "/".join(segments)


def path_matches(call, route):
    """A call reaches a route when the route's segments end the call's (a base prefix is allowed)."""
    c, r = call.strip("/").split("/"), route.strip("/").split("/")
    if len(r) > len(c):
        return False
    tail = c[len(c) - len(r):]
    return all(a == b or "{}" in (a, b) for a, b in zip(tail, r))


class Inventory:
    def __init__(self):
        self.routes, self.calls, self.ops, self.events = [], [], [], []
        self.jobs, self.tables, self.config, self.warnings = [], [], {}, []

    def add_config(self, repo, key, default, anchor):
        entry = self.config.setdefault((repo, key), {"default": None, "anchors": set()})
        if default not in (None, "") and entry["default"] is None:
            entry["default"] = default
        if anchor:
            entry["anchors"].add(anchor)


SECRET_RE = re.compile(r"SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|API_?KEY|CREDENTIAL", re.I)


def _safe_default(key, value):
    value = (value or "").strip().strip("\"'")
    if not value:
        return None
    if SECRET_RE.search(key):
        return "(secret)"
    return value.replace("|", "/")[:60]


def _find_definition(repo_path, files, lang, name, reg_file, reg_text):
    """Where `name` (a route's handler) is defined: Type.Name for Go methods when it can tell."""
    exts = [e for e, l in LANG_BY_EXT.items() if l == lang]
    candidates = []
    if lang == "go":
        receiver_types = set()
        for var in re.findall(rf"\b(\w+)\.{re.escape(name)}\b", reg_text):
            receiver_types |= set(re.findall(rf"\b{re.escape(var)}\s+\*?(?:\w+\.)?(\w+)\b", reg_text))
        pattern = re.compile(rf"^func (?:\(\w+ \*?(\w+)\) )?{re.escape(name)}\(", re.M)
        for rel in files:
            if os.path.splitext(rel)[1] != ".go":
                continue
            text = read_text(os.path.join(repo_path, rel)) or ""
            for owner in pattern.findall(text):
                candidates.append((rel, f"{owner}.{name}" if owner else name, owner))
        typed = [c for c in candidates if c[2] in receiver_types]
        pick = typed if typed else candidates
        if len(pick) == 1 or (pick and len({c[0] for c in pick}) == 1):
            return pick[0][0], pick[0][1]
        return None
    pattern = re.compile(rf"(?:\bdef|\bfunction|\bfun|\bfunc)\s+{re.escape(name)}\b|"
                         rf"\b{re.escape(name)}\s*[:=]\s*(?:async\s*)?(?:function|\()")
    for rel in files:
        if os.path.splitext(rel)[1] in exts:
            text = read_text(os.path.join(repo_path, rel)) or ""
            if pattern.search(text):
                candidates.append(rel)
    if reg_file in candidates:
        return reg_file, name
    if len(candidates) == 1:
        return candidates[0], name
    return None


def _scan_openapi(repo, rel, text, inv):
    ops = []
    if rel.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            inv.warnings.append(f"{repo} · {rel}: OpenAPI JSON does not parse")
            return
        for path, methods in (data.get("paths") or {}).items():
            for method, op in (methods or {}).items():
                if method.upper() in METHODS:
                    ops.append((method.upper(), path, (op or {}).get("operationId")))
    else:
        lines = text.split("\n")
        in_paths, paths_indent, path_indent = False, None, None
        current_path, current_method, method_indent = None, None, None
        for line in lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()
            if re.match(r"^paths\s*:", stripped) and indent == 0:
                in_paths, paths_indent = True, indent
                continue
            if not in_paths:
                continue
            if indent <= paths_indent:
                break
            key = re.match(r"""^["']?(/[^"':]*)["']?\s*:\s*(.*)$""", stripped)
            if key and (path_indent is None or indent == path_indent):
                path_indent, current_path, current_method = indent, key.group(1), None
                rest = key.group(2)
                if rest.startswith("{"):
                    for method, body in re.findall(r"\b(get|put|post|delete|patch)\s*:\s*(\{[^{}]*\}?)", rest):
                        op = re.search(r"operationId\s*:\s*['\"]?([\w.-]+)", body)
                        ops.append((method.upper(), current_path, op.group(1) if op else None))
                continue
            method = re.match(r"^(get|put|post|delete|patch)\s*:", stripped)
            if current_path and method and indent > path_indent:
                current_method, method_indent = method.group(1).upper(), indent
                ops.append((current_method, current_path, None))
                continue
            op = re.match(r"""^operationId\s*:\s*['"]?([\w.-]+)""", stripped)
            if op and current_method and indent > method_indent and ops and ops[-1][2] is None:
                ops[-1] = (ops[-1][0], ops[-1][1], op.group(1))
    for method, path, op_id in ops:
        symbol = op_id or method.lower()
        inv.ops.append({"repo": repo, "method": method, "path": path, "op": op_id,
                        "anchor": _anchor(repo, rel, symbol)})


def _scan_asyncapi(repo, rel, text, inv):
    try:
        data = json.loads(text) if rel.endswith(".json") else wf.loads(text)
    except Exception:
        inv.warnings.append(f"{repo} · {rel}: AsyncAPI file does not parse with the engine's YAML "
                            "subset; add its events with docs.extract patterns")
        return
    if not isinstance(data, dict):
        return
    version = str(data.get("asyncapi", ""))
    channels = data.get("channels") or {}
    if version.startswith("2"):
        for name, channel in channels.items():
            channel = channel or {}
            for key, role in (("subscribe", "out"), ("publish", "in")):
                if key in channel:
                    op = (channel.get(key) or {}).get("operationId")
                    _add_event(inv, repo, rel, str(name), role, op)
    else:
        for op_name, op in (data.get("operations") or {}).items():
            op = op or {}
            ref = str(((op.get("channel") or {}).get("$ref")) or "")
            channel_key = ref.rsplit("/", 1)[-1] if ref else ""
            channel = channels.get(channel_key) or {}
            name = str(channel.get("address") or channel_key or op_name)
            role = "out" if op.get("action") == "send" else "in"
            _add_event(inv, repo, rel, name, role, op_name)


def _add_event(inv, repo, rel, name, role, op):
    symbol = op if op and re.fullmatch(r"[A-Za-z_$][\w.$-]*", op) else name.split("/")[-1]
    if not re.fullmatch(r"[A-Za-z_$][\w.$-]*", symbol or ""):
        symbol = None
    inv.events.append({"repo": repo, "name": name, "role": role,
                       "anchor": _anchor(repo, rel, symbol) if symbol else f"{repo} · {rel}"})


def _scan_contracts(repo, rel, text, inv):
    lower = rel.lower()
    head = text[:2000]
    if lower.endswith((".yaml", ".yml", ".json")):
        if re.search(r"(?:^|/)[^/]*(openapi|swagger)[^/]*$", lower) or re.search(
                r"""^\s*["']?(openapi|swagger)["']?\s*:""", head, re.M):
            _scan_openapi(repo, rel, text, inv)
        elif "asyncapi" in os.path.basename(lower) or re.search(r"""^\s*["']?asyncapi["']?\s*:""",
                                                                 head, re.M):
            _scan_asyncapi(repo, rel, text, inv)
        elif lower.endswith((".yaml", ".yml")) and re.search(r"^kind:\s*CronJob\b", text, re.M):
            name = re.search(r"^metadata:\s*\n(?:\s+.*\n)*?\s+name:\s*['\"]?([\w.-]+)", text, re.M)
            schedule = re.search(r"^\s*schedule:\s*['\"]?([^'\"\n]+)", text, re.M)
            if name and schedule:
                inv.jobs.append({"repo": repo, "name": name.group(1),
                                 "trigger": f"cron {schedule.group(1).strip()}",
                                 "anchor": _anchor(repo, rel, name.group(1))})
    if lower.endswith(".sql"):
        for table in re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:["`]?\w+["`]?\.)?["`]?(\w+)["`]?',
                                text, re.I):
            inv.tables.append({"repo": repo, "name": table, "anchor": _anchor(repo, rel, table)})
    base = os.path.basename(lower)
    if base in (".env.example", ".env.sample", ".env.template", "env.example", ".env.dist"):
        for key, value in re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", text, re.M):
            inv.add_config(repo, key, _safe_default(key, value), _anchor(repo, rel, key))


def _apply_pattern(repo, repo_path, files, rel, lang, lines, text, kind, regex, inv, deferred):
    for match in regex.finditer(text):
        groups = {k: v for k, v in match.groupdict().items() if v is not None}
        start = match.start()
        while start < match.end() and text[start] in " \t\r\n":
            start += 1
        index = text.count("\n", 0, start)
        line = lines[index] if index < len(lines) else ""
        symbol = groups.get("symbol")
        if kind == "route":
            method = (groups.get("method") or "GET").upper()
            deferred.append((repo, rel, lang, index, method, groups["path"], symbol, line.lstrip()))
        elif kind == "call":
            caller = enclosing_symbol(lang, lines, index) or symbol
            if not caller:
                continue
            inv.calls.append({"repo": repo, "method": (groups.get("method") or "GET").upper(),
                              "path": groups["path"], "anchor": _anchor(repo, rel, caller)})
        elif kind in ("event_out", "event_in"):
            where = symbol or enclosing_symbol(lang, lines, index)
            inv.events.append({"repo": repo, "name": groups["name"], "role": kind[-3:].strip("_"),
                               "anchor": _anchor(repo, rel, where) if where else f"{repo} · {rel}"})
        elif kind == "job":
            runs = symbol or enclosing_symbol(lang, lines, index)
            found = _find_definition(repo_path, files, lang, runs, rel, text) if runs else None
            anchor = _anchor(repo, found[0], found[1]) if found else (
                _anchor(repo, rel, runs) if runs else f"{repo} · {rel}")
            inv.jobs.append({"repo": repo, "name": groups.get("name") or runs or "?",
                             "trigger": f"cron {groups['schedule']}", "anchor": anchor})
        elif kind == "config":
            owner = symbol
            if lang == "go" and symbol:
                struct = enclosing_symbol(lang, lines, index)
                owner = f"{struct}.{symbol}" if struct and struct != symbol else symbol
            owner = owner or enclosing_symbol(lang, lines, index)
            inv.add_config(repo, groups["key"], _safe_default(groups["key"], groups.get("default")),
                           _anchor(repo, rel, owner) if owner else None)
        elif kind == "table":
            inv.tables.append({"repo": repo, "name": groups["name"],
                               "anchor": _anchor(repo, rel, groups["name"])})


def extract(repos, custom=None):
    """Read every repo's contracts and code into an Inventory. Deterministic; no LLM."""
    inv = Inventory()
    compiled = {lang: [(k, re.compile(p, re.M)) for k, p in pats] for lang, pats in BUILTIN_PATTERNS.items()}
    custom_rules = []
    for rule in custom or []:
        custom_rules.append((rule.get("repo"), rule.get("glob") or "*", rule["kind"],
                             re.compile(rule["pattern"], re.M)))
    for repo, repo_path in sorted(repos.items()):
        files = repo_files(repo_path)
        deferred = []
        for rel in files:
            ext = os.path.splitext(rel)[1].lower()
            lang = LANG_BY_EXT.get(ext)
            wanted = lang or ext in (".yaml", ".yml", ".json", ".sql") or rel.lower().endswith(
                ("env.example", ".env.sample", ".env.template", ".env.dist"))
            rules = [r for r in custom_rules if (not r[0] or r[0] == repo) and fnmatch.fnmatch(rel, r[1])]
            if not wanted and not rules:
                continue
            if lang and TEST_PATH_RE.search(rel):
                continue  # tests call routes and read config too; they are not the system's surface
            text = read_text(os.path.join(repo_path, rel))
            if text is None:
                continue
            _scan_contracts(repo, rel, text, inv)
            lines = text.split("\n")
            for kind, regex in (compiled.get(lang, []) if lang else []):
                _apply_pattern(repo, repo_path, files, rel, lang, lines, text, kind, regex, inv, deferred)
            for _r, _g, kind, regex in rules:
                _apply_pattern(repo, repo_path, files, rel, lang or "go", lines, text, kind, regex,
                               inv, deferred)
        for _repo, rel, lang, index, method, path, symbol, line in deferred:
            text = read_text(os.path.join(repo_path, rel)) or ""
            lines = text.split("\n")
            handler = None
            if symbol and symbol not in KEYWORDS:
                found = _find_definition(repo_path, files, lang, symbol, rel, text)
                handler = _anchor(repo, *found) if found else _anchor(repo, rel, symbol)
            elif line.startswith("@"):
                name = enclosing_symbol(lang, lines, index, forward=True)
                handler = _anchor(repo, rel, name) if name else None
            if not handler:
                name = enclosing_symbol(lang, lines, index)
                handler = _anchor(repo, rel, name) if name else f"{repo} · {rel}"
            inv.routes.append({"repo": repo, "method": method, "path": path, "anchor": handler})
    _dedupe(inv)
    return inv


def _dedupe(inv):
    def unique(rows, key):
        seen, out = set(), []
        for row in sorted(rows, key=lambda r: (key(r), r.get("anchor", ""))):
            if key(row) not in seen:
                seen.add(key(row))
                out.append(row)
        return out
    inv.routes = unique(inv.routes, lambda r: (r["repo"], r["method"], norm_path(r["path"])))
    inv.ops = unique(inv.ops, lambda r: (r["repo"], r["method"], norm_path(r["path"])))
    inv.calls = unique(inv.calls, lambda r: (r["anchor"], r["method"], norm_path(r["path"])))
    inv.events = unique(inv.events, lambda r: (r["name"], r["role"], r["anchor"]))
    inv.jobs = unique(inv.jobs, lambda r: (r["repo"], r["name"]))
    inv.tables = unique(inv.tables, lambda r: (r["repo"], r["name"]))


def serving_route(inv, call):
    """The route a call reaches, preferring an exact path; None when no repo serves it."""
    key = norm_path(call["path"])
    exact = [r for r in inv.routes if r["method"] == call["method"] and norm_path(r["path"]) == key]
    if exact:
        return exact[0]
    loose = [r for r in inv.routes if r["method"] == call["method"]
             and path_matches(key, norm_path(r["path"]))]
    return loose[0] if len(loose) == 1 else None


def api_rows(inv):
    """One row per served operation (code routes, then contract-only operations)."""
    rows = []
    for route in inv.routes:
        key = (route["method"], norm_path(route["path"]))
        callers = sorted(c["anchor"] for c in inv.calls if serving_route(inv, c) is route)
        contract = next((o["anchor"] for o in inv.ops if (o["method"], norm_path(o["path"])) == key), None)
        rows.append({"op": f"{route['method']} {route['path']}", "repo": route["repo"],
                     "handler": route["anchor"], "callers": callers, "contract": contract,
                     "names": [route["path"]] + ([contract.split(" · ")[-1]] if contract else [])})
    served = {(r["method"], norm_path(r["path"])) for r in inv.routes}
    for op in inv.ops:
        if (op["method"], norm_path(op["path"])) not in served:
            rows.append({"op": f"{op['method']} {op['path']}", "repo": op["repo"], "handler": None,
                         "callers": [], "contract": op["anchor"],
                         "names": [op["path"]] + ([op["op"]] if op["op"] else [])})
    return sorted(rows, key=lambda r: (r["op"], r["repo"]))


def event_rows(inv):
    names = sorted({e["name"] for e in inv.events})
    rows = []
    for name in names:
        rows.append({"name": name,
                     "producers": sorted({e["anchor"] for e in inv.events if e["name"] == name and e["role"] == "out"}),
                     "consumers": sorted({e["anchor"] for e in inv.events if e["name"] == name and e["role"] == "in"})})
    return rows


# --------------------------------------------------------------------------- generators

def _cell(value):
    return (value or "None.").replace("|", "/").replace("\n", " ")


def _table(header, rows):
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out if rows else out[:0] + ["None."]


def _in_roots(anchor, roots):
    parts = (anchor or "").split(" · ")
    if len(parts) < 2:
        return False
    target = f"{parts[0]}/{parts[1]}".rstrip("/")
    for root in roots:
        root = str(root).rstrip("/")
        if target == root or target.startswith(root + "/"):
            return True
    return False


def _mentioned(names, text):
    return any(n and re.search(rf"(?<![\w/]){re.escape(n)}(?![\w])", text) for n in names)


def inventory_sections(inv, roots=None, domain_text=None):
    """{section: [markdown lines]}; scoped when roots is given (anchor under a root, or named in docs)."""
    def keep(anchors, names):
        if roots is None:
            return True
        return any(_in_roots(a, roots) for a in anchors if a) or _mentioned(names, domain_text or "")
    apis = [r for r in api_rows(inv) if keep([r["handler"], r["contract"], *r["callers"]], r["names"])]
    events = [e for e in event_rows(inv) if keep(e["producers"] + e["consumers"], [e["name"]])]
    jobs = [j for j in inv.jobs if keep([j["anchor"]], [j["name"]])]
    tables = [t for t in inv.tables if keep([t["anchor"]], [t["name"]])]
    config = [(repo, key, v) for (repo, key), v in sorted(inv.config.items())
              if keep(sorted(v["anchors"]), [key])]
    return {
        "APIs": _table(["Operation", "Owner repo", "Handler", "Called by", "Contract"],
                       [[r["op"], r["repo"], r["handler"], "; ".join(r["callers"]) or None, r["contract"]]
                        for r in apis]),
        "Events": _table(["Event", "Producers", "Consumers"],
                         [[e["name"], "; ".join(e["producers"]) or None, "; ".join(e["consumers"]) or None]
                          for e in events]),
        "Jobs": _table(["Job", "Trigger", "Owner repo", "Runs"],
                       [[j["name"], j["trigger"], j["repo"], j["anchor"]]
                        for j in sorted(jobs, key=lambda j: (j["name"], j["repo"]))]),
        "Data": _table(["Table", "Owner repo", "Schema"],
                       [[t["name"], t["repo"], t["anchor"]]
                        for t in sorted(tables, key=lambda t: (t["name"], t["repo"]))]),
        "Config": _table(["Key", "Default", "Owner repo", "Read in"],
                         [[key, v["default"], repo, "; ".join(sorted(v["anchors"])) or None]
                          for repo, key, v in config]),
    }


def gen_inventory(domain, inv, roots, domain_text):
    out = [f"# {domain}: generated inventory",
           "> Generated by living_docs.py from code and contracts. Never edit by hand. "
           "Read one section at a time.", ""]
    for name, lines in inventory_sections(inv, roots, domain_text).items():
        out += [f"## {name}", *lines, ""]
    return "\n".join(out)


def gen_workspace_inventory(inv):
    out = ["# Workspace inventory",
           "> Extracted by living_docs.py from every repository's code and contracts. "
           "Use it to choose domains and code_roots; do not copy it into the docs.", ""]
    for name, lines in inventory_sections(inv).items():
        out += [f"## {name}", *lines, ""]
    calls = []
    for call in inv.calls:
        route = serving_route(inv, call)
        calls.append([call["anchor"], f"{call['method']} {call['path']}",
                      route["repo"] if route else None, route["anchor"] if route else None])
    out += ["## Calls between repositories",
            *_table(["From (repo · path · function)", "Operation", "To", "Handler"], calls), ""]
    if inv.warnings:
        out += ["## Not extracted", *[f"- {w}" for w in inv.warnings], ""]
    return "\n".join(out)


def gen_connections(inv, roots):
    rows = []
    for call in sorted(inv.calls, key=lambda c: (c["anchor"], c["method"], c["path"])):
        route = serving_route(inv, call)
        if not (_in_roots(call["anchor"], roots) or (route and _in_roots(route["anchor"], roots))):
            continue
        rows.append([call["anchor"], route["repo"] if route else None,
                     f"{call['method']} {route['path'] if route else call['path']}",
                     route["anchor"] if route else None])
    return "\n".join(_table(["From (repo · path · function)", "To", "Operation", "Handler"], rows)) + "\n"


def gen_diagram(arch):
    lines = ["graph LR"]
    if arch:
        for header, rows in arch.tables("Cross-repo flows and contracts")[:1]:
            names = [h.lower() for h in header]
            for row in rows:
                cell = dict(zip(names, row))
                src, dst = cell.get("from", ""), cell.get("to", "")
                if not src or not dst:
                    continue
                node = lambda s: re.sub(r"\W", "_", s)
                label = re.sub(r"[|\"]", "", cell.get("protocol", "")) or "calls"
                lines.append(f"  {node(src)}[\"{src}\"] -->|{label}| {node(dst)}[\"{dst}\"]")
    return "\n".join(lines) + "\n"


def gen_index(anchors):
    out = ["# Code to facts", "> Generated by living_docs.py for the checker. Never loaded into a prompt.",
           "", "| Path · symbol | Facts |", "| --- | --- |"]
    out += [f"| {key} | {', '.join(sorted(ids))} |" for key, ids in sorted(anchors.items()) if ids]
    return "\n".join(out) + "\n"


TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|_test\.|\.test\.|\.spec\.|(^|/)test_[^/]*$")


def gen_facts_blocks(repos, anchors, defs, opted_in):
    """{instruction file path: block} for folders of opted-in repos that hold anchored facts."""
    per_dir = {}
    for key, ids in anchors.items():
        parts = key.split(" · ")
        if len(parts) != 3:
            continue
        repo, path, _ = parts
        if repo not in opted_in or repo not in repos or TEST_PATH_RE.search(path) or path.endswith("/"):
            continue
        per_dir.setdefault((repo, os.path.dirname(path)), set()).update(
            i for i in ids if i in defs and not is_retired(defs, i))
    begin, end = block_markers(FACTS, "docs/")
    blocks = {}
    for (repo, folder), ids in sorted(per_dir.items()):
        if not ids:
            continue
        lines = [begin, "Facts enforced in this folder (full row: living_docs.py snippet <ID>):"]
        for ident in sorted(ids):
            _doc, section, header, row = defs[ident]
            text = row[1] if len(row) > 1 else ""
            if section == "Change scenarios" and len(row) > 2:
                text = f"if you change this, also check: {row[2]}"
            lines.append(f"- {ident}: {text}")
        lines.append(end)
        for name in INSTRUCTION_FILES:
            target = os.path.join(repos[repo], folder, name)
            if os.path.isfile(target):
                blocks[target] = "\n".join(lines)
    return blocks


def strip_generated(text):
    for name in (FACTS, CONNECTIONS):
        text = re.sub(rf"\n*<!-- generated:{name} begin[^>]*-->.*?<!-- generated:{name} end -->\n?",
                      "\n", text, flags=re.S)
    return text.rstrip("\n")


def only_generated_changes(repo_path, rel):
    """True when an instruction file differs from HEAD only inside its generated facts block."""
    if os.path.basename(rel) not in INSTRUCTION_FILES:
        return False
    current = read_text(os.path.join(repo_path, rel))
    rc, committed = _git(repo_path, "show", f"HEAD:{rel}")
    if current is None or rc != 0:
        return False
    return strip_generated(current) == strip_generated(committed)


def _sync_file(path, content, write, label, report):
    current = read_text(path) if os.path.exists(path) else None
    if current == content:
        return
    if write:
        write_text(path, content)
    else:
        report.err("R4", label, "generated output is out of date or was edited by hand",
                   "run living_docs.py check --write; never edit generated files")


def _sync_block(path, name, content, write, label, report, heading=None):
    text = read_text(path) or ""
    begin, end = block_markers(name, "code" if name == CONNECTIONS else "docs/")
    match = block_re(name).search(text)
    if not match:
        if not write:
            report.err("R4", label, f"generated:{name} block is missing", "run living_docs.py check --write")
            return
        if name == FACTS:
            new_text = text.rstrip("\n") + "\n\n" + content + "\n"
        else:
            block = f"{begin}\n{content}{end}"
            pattern = re.compile(rf"^## {re.escape(heading)}\n(?:(?:None\.)?\s*\n)*", re.M)
            if pattern.search(text):
                new_text = pattern.sub(lambda m: f"## {heading}\n{block}\n\n", text, count=1)
            else:
                report.err("R4", label, f"no '## {heading}' section to hold the generated block",
                           f"add '## {heading}'")
                return
    elif name == FACTS:
        new_text = text[:match.start()] + content + text[match.end():]
    else:
        new_text = text[:match.start(1)] + content + text[match.end(1):]
    if new_text != text:
        if write:
            write_text(path, new_text)
        else:
            report.err("R4", label, f"generated:{name} block is out of date or was edited by hand",
                       "run living_docs.py check --write")


def remove_stale_facts(repos, opted_in, keep):
    """Drop facts blocks no longer generated (a folder lost its last anchored fact)."""
    for repo in opted_in:
        if repo not in repos:
            continue
        for rel in repo_files(repos[repo]):
            if os.path.basename(rel) in INSTRUCTION_FILES:
                path = os.path.join(repos[repo], rel)
                if path in keep:
                    continue
                text = read_text(path) or ""
                if block_re(FACTS).search(text):
                    write_text(path, strip_generated(text) + "\n")


# --------------------------------------------------------------------------- R5 staleness

def check_staleness(repos, docs, by_doc, nightly, today, report):
    drafts = [d.rel for d in docs if d.fm.get("status") == "draft"]
    if drafts:
        report.warn("R5", ", ".join(drafts), f"{len(drafts)} doc(s) are draft: no person has "
                    "reviewed them; set status: verified after review")
    for doc in docs:
        stamps = doc.fm.get("verified_at") or {}
        if not isinstance(stamps, dict):
            report.err("R7", doc.rel, "verified_at must be a mapping of repo to commit",
                       "let living_docs.py stamp write it")
            continue
        for repo, commit in stamps.items():
            if repo not in repos:
                continue
            path = repos[repo]
            rc, changed = _git(path, "diff", "--name-only", str(commit), "HEAD")
            rc2, when = _git(path, "show", "-s", "--format=%cs", str(commit))
            if rc != 0 or rc2 != 0:
                report.err("R5", doc.rel, f"{repo} commit {commit} not found",
                           "run living_docs.py stamp after re-checking the doc")
                continue
            changed = set(changed.split())
            hits = sorted(k for k in by_doc.get(doc.rel, ()) if k.startswith(repo + " · ") and (
                k.split(" · ")[1] in changed or any(c.startswith(k.split(" · ")[1].rstrip("/") + "/")
                                                     for c in changed)))
            if not hits:
                continue
            try:
                age = (today - datetime.date.fromisoformat(when.strip())).days
            except ValueError:
                age = 0
            msg = f"{len(hits)} anchor(s) changed in {repo} since {commit} ({age} days): " + "; ".join(hits[:5])
            if nightly and age > STALE_DAYS:
                report.err("R5", doc.rel, msg, "re-check the rows that cite these anchors, then stamp")
            else:
                report.warn("R5", doc.rel, msg)


# --------------------------------------------------------------------------- team-owned content

def team_snapshot(root):
    """The text of every team-owned section, and side-effects.yaml, as a writer step starts."""
    locked = {}
    for doc in load_docs(root):
        sections = TEAM_SECTIONS.get(doc.kind, ())
        if sections:
            locked[doc.rel] = {name: doc.section_text(name) for name in sections}
    side = os.path.join(root, SIDE_EFFECTS)
    return {"locked": locked, "side_effects": read_text(side) if os.path.isfile(side) else None}


def _empty(text):
    return (text or "").strip() in ("", "None.")


def _replace_section(path, kind, section, body):
    """Put `body` back as the section's content, re-adding the heading in format order if gone."""
    text = read_text(path) or ""
    lines = text.split("\n")
    start, end, fenced = None, None, False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
        if fenced or not line.startswith("## "):
            continue
        if start is not None:
            end = i
            break
        if line[3:].strip() == section:
            start = i
    new = [f"## {section}", *(body or "None.").split("\n"), ""]
    if start is not None:
        lines[start:end if end is not None else len(lines)] = new
    else:
        order = FORMAT[kind]["order"]
        later = order[order.index(section) + 1:]
        at = next((i for i, line in enumerate(lines)
                   if line.startswith("## ") and line[3:].strip() in later), len(lines))
        lines[at:at] = new
    write_text(path, "\n".join(lines).rstrip("\n") + "\n")


def enforce_lock(root, snapshot, write, report):
    """R9: a writer step may not change team-owned content. With --write the engine puts the
    snapshot text back, so the guarantee holds even when the writer ignores the report."""
    before = snapshot.get("locked") or {}
    for doc in load_docs(root):
        for section in TEAM_SECTIONS.get(doc.kind, ()):
            now = doc.section_text(section)
            if doc.rel in before:
                was = before[doc.rel].get(section)
                if (now or "").strip() == (was or "").strip():
                    continue
                restore = was
            else:
                if _empty(now):
                    continue
                restore = "None."
            report.err("R9", f"{doc.rel} §{section}", "team-owned content was changed by this step"
                       + (" and has been restored" if write else ""),
                       f"leave §{section} exactly as the team wrote it; write what you found as rows "
                       f"under '## {PROPOSALS}' instead")
            if write:
                _replace_section(doc.path, doc.kind, section, restore)
    present = {d.rel for d in load_docs(root)}
    for rel, sections in sorted(before.items()):
        if rel not in present and any(not _empty(t) for t in sections.values()):
            report.err("R9", rel, "a doc holding team-owned rules was removed",
                       f"restore docs/{rel}; only the team may retire its rules")
    side = os.path.join(root, SIDE_EFFECTS)
    now = read_text(side) if os.path.isfile(side) else None
    was = snapshot.get("side_effects")
    if now != was:
        report.err("R9", SIDE_EFFECTS, "team-owned change scenarios were changed by this step"
                   + (" and have been restored" if write else ""),
                   f"leave {SIDE_EFFECTS} to the team; propose scenarios under '## {PROPOSALS}'")
        if write:
            if was is None:
                os.remove(side)
            else:
                write_text(side, was)


SIDE_EFFECTS_STARTER = """\
# Change scenarios, machine-readable: "if you change X, also check Y". Written by the team, never by
# a model. Each scenario is also a row in the domain's docs/technical/<domain>.md under
# "## Change scenarios", with the same ID. Maestro's engine checks every name below still exists.
#
# - id: PL-CS-001                    # <PREFIX>-CS-NNN, defined in docs/technical/<domain>.md
#   domain: payment-links            # the technical doc whose table lists it
#   summary: Disabling a payment link
#   rules: [PL-INV-004]              # invariants at risk (<PREFIX>-INV-NNN or ARCH-INV-NNN)
#   repo: backend                    # default repository for the names below ("repo:name" overrides)
#   when_changing: ["internal/links/disable.go", "Service.Disable"]
#   also_impacts:
#     domains: [reminders]
#     tables: [payment_links]
#     queues: [link.disabled]
#     endpoints: ["GET /v1/links/{id}"]
#     files: ["web:src/screens/Links.tsx"]
#     symbols: []
#   verify: ["TestDisablePublishesEvent"]
version: 1
scenarios: []
"""


def load_side_effects(root, report):
    """The scenarios list, [] when empty, None when the file does not exist."""
    path = os.path.join(root, SIDE_EFFECTS)
    if not os.path.isfile(path):
        return None
    try:
        doc = wf.loads(read_text(path) or "")
    except Exception as exc:  # wf raises its own error types
        report.err("R7", SIDE_EFFECTS, f"not readable YAML ({exc})", "use Maestro's YAML subset",
                   team=True)
        return []
    items = doc.get("scenarios") if isinstance(doc, dict) else doc
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        report.err("R7", SIDE_EFFECTS, "expected a 'scenarios:' list", "write scenarios: [...]",
                   team=True)
        return []
    return items


class Code:
    """Each repository's source text (not docs, not markdown), for whole-word name lookups."""

    def __init__(self, repos):
        self.repos, self._files = dict(repos), {}

    def files(self, repo):
        if repo not in self._files:
            texts = {}
            for rel in repo_files(self.repos[repo]):
                if rel.split("/")[0] == "docs" or rel.endswith(".md"):
                    continue
                text = read_text(os.path.join(self.repos[repo], rel))
                if text is not None:
                    texts[rel] = text
            self._files[repo] = texts
        return self._files[repo]

    def has_path(self, repo, rel):
        return os.path.exists(os.path.join(self.repos[repo], rel.lstrip("./")))

    def has_word(self, repo, word):
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])")
        return any(pattern.search(text) for text in self.files(repo).values())

    def has_literal(self, repo, word):
        """`word` right after a quote or slash: route segments, table and queue names."""
        pattern = re.compile(r"""["'`/]""" + re.escape(word) + r"(?![A-Za-z0-9_])")
        return any(pattern.search(text) for text in self.files(repo).values())


def _check_name(kind, entry, default_repo, code, where, report):
    entry = str(entry).strip()
    repo, thing = default_repo, entry
    if ":" in entry and not re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s", entry, re.I):
        head, tail = entry.split(":", 1)
        if head in code.repos:
            repo, thing = head, tail.strip()
    if repo is None:
        if len(code.repos) != 1:
            report.err("R3", where, f"'{entry}' names no repository",
                       f"write 'repo:{entry}' or set the scenario's repo:", team=True)
            return
        repo = next(iter(code.repos))
    if repo not in code.repos:
        report.err("R3", where, f"repository '{repo}' is not in this workspace",
                   "name a repository the workspace has", team=True)
        return
    if kind == "auto":
        file_like = "/" in thing or os.path.splitext(thing)[1].lower() in SOURCE_EXT
        kind = "file" if file_like else "symbol"
    problem = None
    if kind == "file" and not code.has_path(repo, thing):
        problem = f"file '{thing}' no longer exists in {repo}"
    elif kind == "symbol":
        for part in [re.sub(r"\(.*\)$", "", p) for p in re.split(r"::|[.#]", thing) if p]:
            if part and not code.has_word(repo, part):
                problem = f"symbol '{thing}' ('{part}') no longer exists in {repo}"
                break
    elif kind in ("table", "queue") and not (code.has_literal(repo, thing) or code.has_word(repo, thing)):
        problem = f"{kind} '{thing}' no longer appears in {repo}"
    elif kind == "endpoint":
        match = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)$", thing, re.I)
        if not match:
            problem = f"endpoint '{thing}' should look like 'GET /v1/things/{{id}}'"
        else:
            for seg in match.group(2).split("/"):
                if seg and not seg.startswith(("{", ":", "<")) and not code.has_literal(repo, seg):
                    problem = f"endpoint '{thing}' (segment '{seg}') no longer exists in {repo}"
                    break
    elif kind == "test" and not (code.has_word(repo, thing) or code.has_literal(repo, thing)):
        problem = f"test '{thing}' no longer exists in {repo}"
    if problem:
        report.err("R3", where, problem, "update the scenario to the code's current names", team=True)


def check_side_effects(root, repos, docs, defs, report):
    """docs/impact/side-effects.yaml against the docs (IDs, domains) and the code (every name)."""
    items = load_side_effects(root, report)
    if items is None:
        return 0
    domains = {d.domain for d in docs if d.domain}
    in_tables = {i: d for i, (d, section, _h, _r) in defs.items() if section == "Change scenarios"}
    code, seen = Code(repos), set()
    for number, scenario in enumerate(items, 1):
        sid = str(scenario.get("id", "")) if isinstance(scenario, dict) else ""
        where = f"{SIDE_EFFECTS} {sid or '#' + str(number)}"
        if not re.fullmatch(rf"{PREFIX_RE}-CS-\d{{3}}", sid):
            report.err("R1", where, "each scenario needs an ID like PL-CS-001",
                       "use the ID of its row in the technical doc's Change scenarios", team=True)
            continue
        if sid in seen:
            report.err("R1", where, "duplicate scenario ID", "give each scenario its own ID", team=True)
        seen.add(sid)
        if sid not in in_tables:
            report.warn("R2", where, "no row in any technical doc's Change scenarios table")
        elif scenario.get("domain") and scenario.get("domain") != in_tables[sid].domain:
            report.err("R2", where, f"domain '{scenario.get('domain')}' but its row is in "
                       f"{in_tables[sid].rel}", "make the two agree", team=True)
        if not scenario.get("when_changing"):
            report.err("R7", where, "when_changing names nothing", "name at least one file or symbol",
                       team=True)
        for rule in scenario.get("rules") or []:
            if rule not in defs or "-INV-" not in rule:
                report.err("R2", where, f"cites rule {rule}, which no doc defines as an invariant",
                           "cite a defined <PREFIX>-INV-NNN or ARCH-INV-NNN", team=True)
        also = scenario.get("also_impacts") or {}
        if not isinstance(also, dict):
            report.err("R7", where, "also_impacts must be a mapping", "write also_impacts: {...}",
                       team=True)
            also = {}
        for domain in also.get("domains") or []:
            if domain not in domains:
                report.err("R2", where, f"also_impacts.domains '{domain}' has no docs",
                           "name a domain from the Domain map", team=True)
        if not repos:
            continue
        default = scenario.get("repo") or None
        for entry in scenario.get("when_changing") or []:
            _check_name("auto", entry, default, code, where + " when_changing", report)
        for key, kind in SIDE_EFFECT_NAMES:
            for entry in also.get(key) or []:
                _check_name(kind, entry, default, code, f"{where} also_impacts.{key}", report)
        for entry in scenario.get("verify") or []:
            _check_name("test", entry, default, code, where + " verify", report)
    for sid, doc in sorted(in_tables.items()):
        if sid not in seen and not is_retired(defs, sid):
            report.warn("R2", doc.rel, f"{sid} has no entry in {SIDE_EFFECTS}")
    return len(seen)


def rules_status(root):
    docs = load_docs(root)
    defs = collect_ids(docs, Report())
    items = load_side_effects(root, Report())
    rules = sorted(i for i in defs if "-INV-" in i and not is_retired(defs, i))
    scenarios = sorted(i for i in defs if "-CS-" in i and not is_retired(defs, i))
    present = bool(rules or scenarios or items)
    domains = sorted({defs[i][0].domain or "architecture" for i in rules + scenarios})
    if present:
        summary = f"{len(rules)} invariants, {len(scenarios)} change scenarios ({', '.join(domains)})"
    else:
        summary = ("no team-owned rules yet: the team writes invariants and change scenarios in "
                   "docs/technical/<domain>.md and docs/impact/side-effects.yaml (optional)")
    return {"present": present, "rule_count": len(rules), "scenario_count": len(scenarios),
            "domains_csv": ",".join(domains), "side_effects": items is not None, "summary": summary}


def rules_check(root, repo=None, worktree=None):
    """The team's rules and scenarios against the code (a feature's worktree for `repo`).
    Never blocks: a review step reads the result."""
    root = os.path.abspath(root)
    status = rules_status(root)
    if not status["present"]:
        return {"present": False, "valid": True, "skipped": True, "error_count": 0,
                "warning_count": 0, "rule_count": 0, "scenario_count": 0, "issues_summary": "",
                "errors": [], "warnings": [], "summary": "no team-owned rules or scenarios; skipped"}
    repos = workspace_repos(root)
    if repo and worktree and os.path.isdir(worktree):
        repos[repo] = os.path.abspath(worktree)
    report = Report()
    docs = load_docs(root)
    defs = collect_ids(docs, Report())
    team_docs = [d for d in docs if TEAM_SECTIONS.get(d.kind)]
    cache = {}
    for doc in team_docs:
        for section, header, item in doc.items():
            if not doc.is_team(section):
                continue
            text = " | ".join(item) if header else item
            for r, path, symbol in anchors_in(text, repos):
                problem = resolve_anchor(repos, r, path, symbol, cache)
                if problem:
                    report.err("R3", f"{doc.rel} §{section}", f"{r} · {path} · {symbol}: {problem}",
                               "the branch must keep what the rule relies on, or the team updates it")
    scenario_count = check_side_effects(root, repos, docs, defs, report)
    pattern = id_re(known_prefixes(docs))
    cited = set()
    for name, file_part, number, line in code_citations(repos, pattern):
        for ident in pattern.findall(line):
            cited.add(ident)
            if ident not in defs:
                report.err("R2", f"{name}/{file_part}:{number}", f"{ident} is cited but never defined",
                           "correct the comment, or ask the team to define it")
    check_rules_cited(defs, cited, report)
    errors = list(dict.fromkeys(report.errors))
    warnings = list(dict.fromkeys(report.warnings))
    summary = (f"{status['rule_count']} invariants, {status['scenario_count']} scenarios: "
               + ("all names still exist" if not errors else f"{len(errors)} mismatch(es) with the code"))
    return {"present": True, "valid": not errors, "skipped": False, "error_count": len(errors),
            "warning_count": len(warnings), "rule_count": status["rule_count"],
            "scenario_count": max(status["scenario_count"], scenario_count),
            "issues_summary": " | ".join(errors[:5]), "errors": errors, "warnings": warnings,
            "summary": summary}


def scaffold_side_effects(root):
    path = os.path.join(root, SIDE_EFFECTS)
    if os.path.exists(path):
        return {"created": False, "path": SIDE_EFFECTS}
    write_text(path, SIDE_EFFECTS_STARTER)
    return {"created": True, "path": SIDE_EFFECTS}


def next_ids(root, prefix):
    defs = collect_ids(load_docs(root), Report())
    top = {kind: 0 for kind in ID_KINDS}
    for ident in defs:
        p, kind, digits = ident.split("-")
        if p == prefix:
            top[kind] = max(top[kind], int(digits))
    return {kind.lower(): f"{prefix}-{kind}-{top[kind] + 1:03d}" for kind in ID_KINDS}


# --------------------------------------------------------------------------- config + check

def docs_config(root):
    try:
        import project_config
        config = project_config.load(root) or {}
    except Exception:
        config = {}
    section = config.get("docs") if isinstance(config, dict) else None
    return section if isinstance(section, dict) else {}


def workspace_repos(root):
    return {name: path for name, path in codebase_scan.discover_repos(root)}


def run_check(root, write=False, nightly=False, today=None, locked_from=None):
    """All rules. `locked_from` (a writer's snapshot) turns on R9 and makes problems inside
    team-owned content warnings for the team, since the writer may not touch it."""
    root = os.path.abspath(root)
    today = today or datetime.date.today()
    report = Report(locked=locked_from is not None)
    if locked_from is not None:
        enforce_lock(root, locked_from, write, report)
    repos = workspace_repos(root)
    settings = docs_config(root)
    docs = load_docs(root)
    tokens = {d.rel: check_structure(d, repos, report) for d in docs}
    check_domain_map(root, docs, report)
    defs = collect_ids(docs, report)
    inv = extract(repos, settings.get("extract"))
    for warning in inv.warnings:
        report.warn("R4", "extract", warning)
    # Generated output first (with --write), so the anchors and citations below see it.
    arch = next((d for d in docs if d.kind == "architecture"), None)
    gen = os.path.join(root, "docs", GEN_DIR)
    _sync_file(os.path.join(gen, "diagrams", "architecture.mmd"), gen_diagram(arch), write,
               f"{GEN_DIR}/diagrams/architecture.mmd", report)
    for doc in docs:
        if doc.kind != "technical" or not doc.domain:
            continue
        roots = [str(r) for r in doc.fm.get("code_roots") or []]
        functional = next((d for d in docs if d.kind == "functional" and d.domain == doc.domain), None)
        domain_text = doc.text + (functional.text if functional else "")
        _sync_file(os.path.join(gen, f"{doc.domain}.inventory.md"),
                   gen_inventory(doc.domain, inv, roots, domain_text), write,
                   f"{GEN_DIR}/{doc.domain}.inventory.md", report)
        _sync_block(doc.path, CONNECTIONS, gen_connections(inv, roots), write, doc.rel, report,
                    heading="Cross-repo connections")
    if write:
        docs = load_docs(root)
        report_ids = Report()
        defs = collect_ids(docs, report_ids)
    wanted = {f"{d.domain}.inventory.md" for d in docs if d.kind == "technical" and d.domain}
    if os.path.isdir(gen):
        for name in sorted(os.listdir(gen)):
            if name.endswith(".inventory.md") and name not in wanted:
                if write:
                    os.remove(os.path.join(gen, name))
                else:
                    report.err("R4", f"{GEN_DIR}/{name}", "inventory of a domain that has no technical doc",
                               "run living_docs.py check --write")
    anchors, by_doc = collect_anchors(repos, docs, defs, report)
    _sync_file(os.path.join(root, "docs", INDEX_DIR, "code-to-facts.md"), gen_index(anchors), write,
               f"{INDEX_DIR}/code-to-facts.md", report)
    opted_in = [r for r in settings.get("facts_blocks") or [] if isinstance(r, str)]
    blocks = gen_facts_blocks(repos, anchors, defs, opted_in)
    for target, block in sorted(blocks.items()):
        _sync_block(target, FACTS, block, write, os.path.relpath(target, root), report)
    if write:
        remove_stale_facts(repos, opted_in, set(blocks))
    check_citations(root, repos, docs, defs, report)
    check_side_effects(root, repos, docs, defs, report)
    for call in inv.calls:
        if inv.routes and not serving_route(inv, call):
            report.err("R6", call["anchor"], f"calls {call['method']} {call['path']}, which no "
                       "repository serves", "fix the client, add the route, or add the project's "
                       "route pattern under docs.extract in maestro.config.yaml")
    if inv.calls and not inv.routes:
        report.warn("R6", "extract", "no routes were extracted, so app calls were not checked; add the "
                    "project's route pattern under docs.extract in maestro.config.yaml")
    check_staleness(repos, docs, by_doc, nightly, today, report)
    report.errors = list(dict.fromkeys(report.errors))
    report.warnings = list(dict.fromkeys(report.warnings))
    stats = {"docs": len(docs), "domains": len({d.domain for d in docs if d.domain}),
             "ids": len(defs), "anchors": sum(len(v) for v in by_doc.values()),
             "routes": len(inv.routes), "calls": len(inv.calls), "tokens": tokens}
    return report, stats


# --------------------------------------------------------------------------- stamp, cited, domains

def doc_hashes(root):
    return {d.rel: _sha(d.text) for d in load_docs(root)}


def stamp(root, snapshot=None):
    root = os.path.abspath(root)
    repos = workspace_repos(root)
    before = {}
    if snapshot:
        with open(snapshot, encoding="utf-8") as fh:
            before = json.load(fh).get("docs", {})
    stamped = []
    for doc in load_docs(root):
        if snapshot is not None and before.get(doc.rel) == _sha(doc.text):
            continue
        match = re.match(r"---\n(.*?)\n---\n", doc.text, re.S)
        if not match:
            continue
        heads = {}
        for name in doc.fm.get("repos") or []:
            if name in repos and _head(repos[name]):
                heads[name] = _head(repos[name])
        value = "{" + ", ".join(f'{k}: "{v}"' for k, v in heads.items()) + "}"
        fm_lines = match.group(1).split("\n")
        fm_lines = _set_fm(fm_lines, "verified_at", value, after="repos")
        fm_lines = _set_fm(fm_lines, "status", "draft", after="reviewed")
        text = "---\n" + "\n".join(fm_lines) + "\n---\n" + doc.text[match.end():]
        if text != doc.text:
            write_text(doc.path, text)
        stamped.append(doc.rel)
    return stamped


def _set_fm(lines, key, value, after):
    for i, line in enumerate(lines):
        if re.match(rf"^{key}\s*:", line):
            lines[i] = f"{key}: {value}"
            return lines
    for i, line in enumerate(lines):
        if re.match(rf"^{after}\s*:", line):
            return lines[:i + 1] + [f"{key}: {value}"] + lines[i + 1:]
    return lines + [f"{key}: {value}"]


def cited(root, sources):
    docs = load_docs(root)
    defs = collect_ids(docs, Report())
    pattern = id_re(known_prefixes(docs))
    found = []
    for source in sources:
        text = read_text(source) or ""
        for ident in pattern.findall(text):
            if ident in defs and ident not in found:
                found.append(ident)
    return found, defs


def domains_for(root, repos_filter=None):
    docs = load_docs(root)
    arch = next((d for d in docs if d.kind == "architecture"), None)
    rows = domain_map(arch)
    if repos_filter:
        rows = [r for r in rows if set(r["repos"]) & set(repos_filter)]
    return rows


# --------------------------------------------------------------------------- minimal docs
_MIN_ARCHITECTURE = """---
doc: architecture
id_prefix: ARCH
owner: "Unknown. (ask: tech lead, since 2026-11-10)"
repos: [{repos}]
verified_at: {{}}
reviewed: {{by: null, date: null}}
status: verified
---
> Start here, then open one domain doc.

# Architecture

## System context and repos
A demo product used by tests.
| Repo or provider | Kind | Purpose | Owns data | Runs on |
| --- | --- | --- | --- | --- |
{repo_rows}

## Domain map
| Domain | Purpose | Repos | Owner | Technical | Functional |
| --- | --- | --- | --- | --- | --- |
| {domain} | The demo domain | {repos} | demo team | [technical](technical/{domain}.md) | [functional](functional/{domain}.md) |

## Cross-repo flows and contracts
None.

## Platform-wide invariants
None.
"""

_MIN_FUNCTIONAL = """---
doc: functional
domain: {domain}
id_prefix: DM
owner: "demo team"
repos: [{repos}]
verified_at: {{}}
reviewed: {{by: null, date: null}}
status: verified
---
> {domain} functional. How it is built is in technical/{domain}.md.

# {domain}: Functional

## Purpose and actors
The demo domain lets a user save a draft.

## Business rules
| ID | Rule | Edge | Why / source |
| --- | --- | --- | --- |
| DM-BR-001 | A draft belongs to one user. | None. | Demo requirement |

## Open questions and owned unknowns
None.
"""

_MIN_TECHNICAL = """---
doc: technical
domain: {domain}
id_prefix: DM
owner: "demo team"
repos: [{repos}]
code_roots: [{roots}]
verified_at: {{}}
reviewed: {{by: null, date: null}}
status: verified
---
> {domain} technical. Rules DM-BR-* are in functional/{domain}.md.

# {domain}: Technical

## Invariants and consistency
None.

## Change scenarios
None.

## Cross-repo connections
<!-- generated:connections begin; from code by living_docs.py; do not edit -->
None.
<!-- generated:connections end -->

## Known gaps and tech debt
None.
"""


def write_minimal_docs(root, domain, repos):
    """A minimal doc set that passes `check`, for the simulator and tests of other workflows."""
    names = ", ".join(repos)
    values = {"domain": domain, "repos": names, "roots": ", ".join(f"{r}/src" for r in repos),
              "repo_rows": "\n".join(f"| {r} | service | Demo {r} | None. | local |" for r in repos)}
    for rel, template in (("docs/architecture.md", _MIN_ARCHITECTURE),
                          (f"docs/functional/{domain}.md", _MIN_FUNCTIONAL),
                          (f"docs/technical/{domain}.md", _MIN_TECHNICAL)):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_text(path, template.format(**values))


# --------------------------------------------------------------------------- CLI

def _summary(report, extra=None):
    issues = [f"ERROR {e}" for e in report.errors] + [f"WARN {w}" for w in report.warnings]
    payload = {
        "valid": not report.errors,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "issues_summary": " | ".join(issues[:8]) if issues else "living docs checks passed",
    }
    payload.update(extra or {})
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--root", default=".")
    p.add_argument("--write", action="store_true")
    p.add_argument("--nightly", action="store_true")
    p.add_argument("--today")
    p.add_argument("--report", action="store_true", help="always exit 0; last line is JSON")
    p.add_argument("--locked-from", help="a writer's snapshot: team-owned content may not change (R9)")
    p = sub.add_parser("extract")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p = sub.add_parser("snippet")
    p.add_argument("ids")
    p.add_argument("--root", default=".")
    p = sub.add_parser("cited")
    p.add_argument("--root", default=".")
    p.add_argument("--from", dest="sources", action="append", required=True)
    p.add_argument("--repos", default="", help="also report the doc paths of these repos' domains")
    p.add_argument("--out", required=True)
    p = sub.add_parser("domains")
    p.add_argument("--root", default=".")
    p.add_argument("--repos", default="")
    p.add_argument("--impact", help="impact.json: use the repositories it names (all domains when absent)")
    p = sub.add_parser("snapshot")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p = sub.add_parser("stamp")
    p.add_argument("--root", default=".")
    p.add_argument("--snapshot")
    p = sub.add_parser("status")
    p.add_argument("--root", default=".")
    p = sub.add_parser("rules")
    p.add_argument("--root", default=".")
    p.add_argument("--repo", help="read this repository from --worktree instead of its checkout")
    p.add_argument("--worktree")
    p.add_argument("--out", help="also write the full report (JSON) here")
    p = sub.add_parser("scaffold")
    p.add_argument("--root", default=".")
    p = sub.add_parser("next")
    p.add_argument("prefix")
    p.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        today = datetime.date.fromisoformat(args.today) if args.today else None
        locked = None
        if args.locked_from:
            if not os.path.isfile(args.locked_from):
                print(f"--locked-from {args.locked_from} does not exist", file=sys.stderr)
                return 2
            with open(args.locked_from, encoding="utf-8") as fh:
                locked = json.load(fh).get("team") or {}
        report, stats = run_check(args.root, write=args.write, nightly=args.nightly, today=today,
                                  locked_from=locked)
        for warning in report.warnings:
            print("WARN ", warning)
        for error in report.errors:
            print("ERROR", error)
        print(json.dumps(_summary(report, {k: v for k, v in stats.items() if k != "tokens"})))
        return 0 if args.report or not report.errors else 1
    if args.cmd == "extract":
        root = os.path.abspath(args.root)
        inv = extract(workspace_repos(root), docs_config(root).get("extract"))
        write_text(args.out, gen_workspace_inventory(inv))
        print(json.dumps({"inventory_path": args.out, "routes": len(inv.routes), "calls": len(inv.calls),
                          "events": len(event_rows(inv)), "tables": len(inv.tables),
                          "jobs": len(inv.jobs), "config": len(inv.config)}))
        return 0
    if args.cmd == "snippet":
        defs = collect_ids(load_docs(args.root), Report())
        missing = []
        for ident in [i.strip() for i in args.ids.split(",") if i.strip()]:
            if ident in defs:
                print(snippet(defs, ident))
            else:
                missing.append(ident)
        if missing:
            print(f"not defined: {', '.join(missing)}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "cited":
        root = os.path.abspath(args.root)
        sources = [src if os.path.isabs(src) else os.path.join(root, src) for src in args.sources]
        out = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
        found, defs = cited(root, sources)
        wanted = [r.strip() for r in args.repos.split(",") if r.strip()]
        rows = domains_for(root, wanted) if wanted else []
        lines = ["# Cited living-doc facts",
                 "> The rows behind every rule, invariant and change scenario the inputs cite. "
                 "Generated by living_docs.py.", ""]
        lines += [f"- {snippet(defs, i)}" for i in found] or ["None. The inputs cite no living-doc IDs."]
        write_text(out, "\n".join(lines) + "\n")
        print(json.dumps({"facts_path": args.out, "cited_count": len(found), "cited_csv": ",".join(found),
                          "technical_paths": ", ".join(f"docs/{r['technical']}" for r in rows
                                                       if r["technical"]) or "None"}))
        return 0
    if args.cmd == "domains":
        wanted = [r.strip() for r in args.repos.split(",") if r.strip()]
        if args.impact:
            impact_path = args.impact if os.path.isabs(args.impact) else os.path.join(args.root, args.impact)
            try:
                with open(impact_path, encoding="utf-8") as fh:
                    named = json.load(fh).get("repos") or []
                wanted += [r["name"] if isinstance(r, dict) else str(r) for r in named
                           if (r.get("name") if isinstance(r, dict) else r)]
            except (OSError, ValueError, AttributeError):
                pass
        rows = domains_for(args.root, wanted)
        if wanted and not rows:
            rows = domains_for(args.root)
        tech = [f"docs/{r['technical']}" for r in rows if r["technical"]]
        func = [f"docs/{r['functional']}" for r in rows if r["functional"]]
        print(json.dumps({"domains_csv": ",".join(r["domain"] for r in rows),
                          "technical_paths": ", ".join(tech) or "None",
                          "functional_paths": ", ".join(func) or "None",
                          "domain_count": len(rows)}))
        return 0
    if args.cmd == "snapshot":
        write_text(args.out, json.dumps({"docs": doc_hashes(args.root), "team": team_snapshot(args.root)},
                                        indent=2, sort_keys=True) + "\n")
        print(json.dumps({"snapshot_path": args.out}))
        return 0
    if args.cmd == "stamp":
        snapshot = args.snapshot if args.snapshot and os.path.isfile(args.snapshot) else None
        stamped = stamp(args.root, snapshot)
        print(json.dumps({"stamped_count": len(stamped), "stamped_csv": ",".join(stamped)}))
        return 0
    if args.cmd == "status":
        print(json.dumps(rules_status(os.path.abspath(args.root))))
        return 0
    if args.cmd == "rules":
        if bool(args.repo) != bool(args.worktree):
            parser.error("--repo and --worktree go together")
        result = rules_check(args.root, args.repo, args.worktree)
        report_path = ""
        if args.out and result.get("skipped"):
            # the team has written no rules: nothing to report, so no file (and none left over)
            try:
                os.remove(args.out)
            except OSError:
                pass
        elif args.out:
            write_text(args.out, json.dumps(result, indent=2) + "\n")
            report_path = args.out
        line = {k: v for k, v in result.items() if k not in ("errors", "warnings")}
        line["report_path"] = report_path
        print(json.dumps(line))
        return 0
    if args.cmd == "scaffold":
        print(json.dumps(scaffold_side_effects(os.path.abspath(args.root))))
        return 0
    if args.cmd == "next":
        if not re.fullmatch(PREFIX_RE, args.prefix.upper()):
            parser.error("next needs a domain's id_prefix, e.g. 'next PL'")
        print(json.dumps(next_ids(args.root, args.prefix.upper())))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
