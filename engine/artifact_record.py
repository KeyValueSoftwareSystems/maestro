#!/usr/bin/env python3
"""artifact_record.py — the per-run manifest of published stage artifacts.

The lead agent (skills/maestro) publishes a rendered stage doc and gets back a shareable
URL (Claude Code) or just a file path (Cursor / Codex). To make a *revision* update the
SAME link instead of minting a new one, that mapping has to persist across the run — and
per the engine's rules it must be written by deterministic engine code, not by the LLM and
not into state.yaml. This owns `.maestro/runs/<slug>/artifacts.json`.

  get <run_dir> <key>
      Print {"key","file","url","title"} for <key> (url/file "" if never recorded).
      The agent reads `url` and passes it back to the publisher so the link updates in place.

  record <run_dir> <key> --file F [--url U] [--title T]
      Upsert the mapping for <key>. Print the stored record.

  list <run_dir>
      Print the whole manifest.

Stdlib-only, atomic write (tmp + rename), deterministic (no timestamps) so it is
golden-set testable like the rest of the engine.
"""
import json
import os
import sys

VERSION = 1


def _path(run_dir):
    return os.path.join(run_dir, "artifacts.json")


def load(run_dir):
    p = _path(run_dir)
    if not os.path.exists(p):
        return {"version": VERSION, "artifacts": {}}
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), dict):
        raise ValueError(f"malformed manifest: {p}")
    data.setdefault("version", VERSION)
    return data


def save(run_dir, data):
    os.makedirs(run_dir, exist_ok=True)
    p = _path(run_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, p)


def get(run_dir, key):
    rec = load(run_dir)["artifacts"].get(key, {})
    return {
        "key": key,
        "file": rec.get("file", ""),
        "url": rec.get("url", ""),
        "title": rec.get("title", ""),
    }


def record(run_dir, key, file="", url="", title=""):
    data = load(run_dir)
    cur = data["artifacts"].get(key, {})
    # A record with no fresh url keeps any url already on file (path-only harnesses must not
    # wipe a link a previous Claude Code run established for the same stage).
    rec = {
        "file": file or cur.get("file", ""),
        "url": url or cur.get("url", ""),
        "title": title or cur.get("title", ""),
    }
    data["artifacts"][key] = rec
    save(run_dir, data)
    out = {"key": key}
    out.update(rec)
    return out


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__.split("\n\n")[2] + "\n")
        return 2
    cmd, run_dir = argv[0], argv[1]
    rest = argv[2:]
    try:
        if cmd == "get":
            if not rest:
                sys.stderr.write("get needs <key>\n")
                return 2
            print(json.dumps(get(run_dir, rest[0])))
            return 0
        if cmd == "list":
            print(json.dumps(load(run_dir)))
            return 0
        if cmd == "record":
            if not rest:
                sys.stderr.write("record needs <key>\n")
                return 2
            key = rest[0]
            opts = rest[1:]
            vals = {"--file": "", "--url": "", "--title": ""}
            i = 0
            while i < len(opts):
                if opts[i] in vals and i + 1 < len(opts):
                    vals[opts[i]] = opts[i + 1]
                    i += 2
                else:
                    i += 1
            print(json.dumps(record(run_dir, key, vals["--file"], vals["--url"], vals["--title"])))
            return 0
        sys.stderr.write(f"unknown command: {cmd}\n")
        return 2
    except (ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
