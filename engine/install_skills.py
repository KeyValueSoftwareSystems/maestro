#!/usr/bin/env python3
"""Install skills into a host's skills directory without overwriting a user's edits.

install.sh calls this instead of copying skills over `<host>/skills/`. The manifest
(.maestro/skill-manifest.json) records, per host and skill, the hash of the copy this installer
last wrote. Per skill:

  missing                               -> added    (copy)
  identical to the new version          -> current  (nothing to do)
  matches the manifest (a stock copy)   -> updated  (replace)
  differs from the manifest (edited)    -> kept     (keep it; write each new file beside it as
                                                     <file>.upstream to review and merge)
  installed before the manifest existed -> updated  (replace; the old files are kept as
                                                     <file>.previous, so nothing is lost)

The hash covers every file in the skill directory except *.upstream / *.previous. `.upstream`
files are never named SKILL.md, so a host never discovers them as a second skill. A `*.previous`
backup is kept across upgrades (a stale `*.upstream` is dropped when the copy is replaced).

--retire <name> ...  removes skills the pack no longer ships, but only OUR stock copy: its hash
matches the manifest, or (installed before the manifest) its SKILL.md frontmatter carries the
pack's `sdlc` tag. A skill of the user's under the same name (`plan`, `verify`) is left alone.

Usage: install_skills.py --dst <host skills dir> --host <name> --manifest <json>
                         [--skill <source skill dir> ...] | [--skills-from <file listing dirs>]
                         | [--retire <name> ...]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

SIDE = (".upstream", ".previous")


def _files(directory):
    out = []
    for dirpath, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(SIDE):
                continue
            full = os.path.join(dirpath, name)
            out.append(os.path.relpath(full, directory))
    return out


def tree_hash(directory):
    digest = hashlib.sha256()
    for rel in _files(directory):
        digest.update(rel.replace(os.sep, "/").encode() + b"\0")
        with open(os.path.join(directory, rel), "rb") as fh:
            digest.update(fh.read().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def _side_copy(src, dst, suffix):
    for rel in _files(src):
        target = os.path.join(dst, rel + suffix)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(src, rel), target)


def _backups(directory):
    """-> {rel: bytes} of the *.previous files under directory (the user's saved copies)."""
    out = {}
    for dirpath, dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(".previous"):
                full = os.path.join(dirpath, name)
                with open(full, "rb") as fh:
                    out[os.path.relpath(full, directory)] = fh.read()
    return out


def _replace(src, dst):
    kept = {}
    if os.path.islink(dst):
        os.unlink(dst)          # never recurse through a link into someone else's tree
    elif os.path.isdir(dst):
        kept = _backups(dst)    # a backup promised as kept must survive the next upgrade
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    for rel, data in kept.items():
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)


def _has_pack_tag(directory):
    """True when the SKILL.md frontmatter `tags:` line carries the pack's `sdlc` tag."""
    try:
        with open(os.path.join(directory, "SKILL.md"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("tags:"):
                    return "sdlc" in line.replace("[", " ").replace("]", " ").replace(",", " ").split()
    except OSError:
        pass
    return False


def retire(names, dst_root, host, manifest_path):
    """Remove retired skills that are our stock copy. -> {"removed": [...], "kept": [...]}."""
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}
    recorded = (manifest.get("hosts") or {}).get(host) or {}
    report = {"removed": [], "kept": []}
    for name in names:
        target = os.path.join(dst_root, name)
        if os.path.islink(target):
            report["kept"].append(name)         # the user's link; never ours
            continue
        if not os.path.isdir(target):
            continue
        ours = (tree_hash(target) == recorded[name]) if name in recorded else _has_pack_tag(target)
        if ours:
            shutil.rmtree(target)
            report["removed"].append(name)
        else:
            report["kept"].append(name)
    return report


def install(skill_dirs, dst_root, host, manifest_path):
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}
    recorded = (manifest.get("hosts") or {}).get(host) or {}
    report = {"added": [], "current": [], "updated": [], "kept": [], "replaced": [], "linked": []}
    # A directory symlink (template `.claude/skills` -> `../skills`) is the
    # template source tree. Never follow it and never replace it.
    if os.path.islink(dst_root):
        raise SystemExit(
            f"FAIL: {dst_root} is a symlink. Host skill folders must be real "
            "directories; link each template skill from there into skills/."
        )
    os.makedirs(dst_root, exist_ok=True)
    for src in skill_dirs:
        name = os.path.basename(os.path.normpath(src))
        dst = os.path.join(dst_root, name)
        new = tree_hash(src)
        if os.path.islink(dst):
            # a template workspace links its own skills in here; never write through the link
            report["linked"].append(name)
            continue
        if not os.path.isdir(dst):
            _replace(src, dst)
            report["added"].append(name)
        else:
            local = tree_hash(dst)
            if local == new:
                report["current"].append(name)
            elif name not in recorded:
                previous = {}
                for rel in _files(dst):
                    with open(os.path.join(dst, rel), "rb") as fh:
                        previous[rel] = fh.read()
                _replace(src, dst)
                for rel, data in previous.items():
                    target = os.path.join(dst, rel + ".previous")
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as fh:
                        fh.write(data)
                report["replaced"].append(name)
            elif local == recorded[name]:
                _replace(src, dst)
                report["updated"].append(name)
            else:
                _side_copy(src, dst, ".upstream")
                report["kept"].append(name)
                continue  # the user's copy stays; keep the hash of what we last wrote
        recorded[name] = new
    manifest.setdefault("hosts", {})[host] = recorded
    manifest["schema_version"] = 1
    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--skills-from")
    parser.add_argument("--retire", nargs="+", metavar="NAME",
                        help="remove these retired skills if they are our stock copy")
    args = parser.parse_args(argv)
    if args.retire:
        result = retire(args.retire, args.dst, args.host, args.manifest)
        for name in result["removed"]:
            print(f"  removed retired skill -> {os.path.join(args.dst, name)}")
        for name in result["kept"]:
            print(f"  kept {os.path.join(args.dst, name)} (not a stock Maestro copy of the "
                  f"retired skill '{name}')")
        return 0
    skills = list(args.skill)
    if args.skills_from:
        with open(args.skills_from, encoding="utf-8") as fh:
            skills += [line.strip() for line in fh if line.strip()]
    report = install(skills, args.dst, args.host, args.manifest)
    for name in report["kept"]:
        print(f"  kept your edited skill {name}; the new version is beside it as *.upstream")
    for name in report["replaced"]:
        print(f"  updated {name}; your previous copy is kept as *.previous")
    print(f"  skills -> {args.dst} ({len(report['added'])} added, {len(report['updated'])} updated, "
          f"{len(report['current'])} current, {len(report['kept'])} kept as edited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
