#!/usr/bin/env python3
"""ui_server — the folder-aware backend behind `maestro ui`.

A tiny stdlib-only HTTP server that serves ui/builder.html AND exposes the repo it is
launched in, so the builder no longer needs the browser File System Access API:

    GET  /                     the builder page
    GET  /api/health           {"ok": true, "root": ...}   (the client's server probe)
    GET  /api/workflows        [{"file","name"}] under <root>/workflows
    GET  /api/workflow?file=X  raw YAML source of <root>/workflows/X
    PUT  /api/workflow?file=X   overwrite that workflow (source only, atomic)
    GET  /api/runs             [{"slug","state"}] from <root>/.maestro/*/state.yaml

This is dev tooling: it reads/serves and writes workflow SOURCE only. It never touches
.maestro/**/state.yaml and never drives a run — the /maestro skill + engine remain the
sole execution path and the only writer of run state. Bound to 127.0.0.1 exclusively.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import state as statemod
import wf as wfmod

DEFAULT_PORT = 8422
PORT_SCAN = 20              # how many ports to try past the default before giving up
MAX_BODY = 1 << 20         # 1 MiB cap on a PUT body
MAX_SCAN = 2000            # ceiling on files listed, a runaway backstop

# Directories never walked for the list, and never written to. .maestro is run state
# (engine-only); .git is history; the rest are noise / vendored trees.
SKIP_DIRS = {".git", ".maestro", ".claude", ".cursor", "node_modules",
             "__pycache__", ".venv", "venv", ".idea", ".vscode", ".mypy_cache"}


# ---------------------------------------------------------------- data helpers

def _safe_repo_yaml(root, file, for_write=False):
    """Resolve <root>/<file> for a .yaml/.yml file, or None if it's not allowed.

    realpath first so a symlink can't tunnel out; commonpath rejects '..' and absolute
    paths that escape the repo. Reads may target any YAML under root except .git; writes
    additionally refuse .maestro (run state is engine-only). This is a localhost dev tool
    on the user's own repo — the same authority their editor has.
    """
    if not file:
        return None
    root_real = os.path.realpath(root)
    cand = os.path.realpath(os.path.join(root_real, file))
    if os.path.commonpath([cand, root_real]) != root_real:
        return None
    if not cand.endswith((".yaml", ".yml")):
        return None
    rel_parts = os.path.relpath(cand, root_real).split(os.sep)
    if ".git" in rel_parts:
        return None
    if for_write and ".maestro" in rel_parts:
        return None
    return cand


def _is_workflow(doc):
    return isinstance(doc, dict) and isinstance(doc.get("nodes"), list) and bool(doc["nodes"])


def _sort_workflows(entries):
    # maestro workflows first, then the canonical workflows/ dir, then by path
    def key(e):
        under_wf = not e["file"].replace(os.sep, "/").startswith("workflows/")
        return (not e["workflow"], under_wf, e["file"])
    return sorted(entries, key=key)


def list_workflows(root):
    """Recursively list every YAML file under root, tagging maestro workflows.

    Each entry: {file: <repo-relative path>, name, workflow: bool, valid: bool}.
    'workflow' means the top level is a non-empty nodes: list; 'valid' means it parsed.
    """
    root_real = os.path.realpath(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root_real):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.endswith((".yaml", ".yml")):
                continue
            if len(out) >= MAX_SCAN:
                return _sort_workflows(out)
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root_real)
            entry = {"file": rel, "name": name, "workflow": False, "valid": False}
            try:
                doc = wfmod.load_file(path)
                entry["valid"] = True
                if _is_workflow(doc):
                    entry["workflow"] = True
                    if doc.get("name"):
                        entry["name"] = str(doc["name"])
            except (OSError, ValueError):
                pass  # unparseable: still listed, tagged not-a-workflow / invalid
            out.append(entry)
    return _sort_workflows(out)


def list_runs(root):
    base = os.path.join(root, statemod.MAESTRO_DIR)
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        if not statemod.valid_slug(name):
            continue
        if not os.path.isdir(os.path.join(base, name)):
            continue
        data = statemod.load(name, root)
        if data is not None:
            out.append({"slug": name, "state": data})
    return out


# ---------------------------------------------------------------- HTTP handler

class Handler(BaseHTTPRequestHandler):
    ROOT = "."
    BUILDER = None
    server_version = "maestro-ui"

    def log_message(self, *args):  # silence the default per-request stderr spam
        pass

    # -- responders -------------------------------------------------------
    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def _fail(self, code, msg):
        self._json({"ok": False, "error": msg}, code)

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self._serve_builder()
        if path == "/api/health":
            return self._json({"ok": True, "root": os.path.abspath(self.ROOT)})
        if path == "/api/workflows":
            return self._json(list_workflows(self.ROOT))
        if path == "/api/runs":
            return self._json(list_runs(self.ROOT))
        if path == "/api/workflow":
            return self._get_workflow(parse_qs(url.query))
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._fail(404, "not found")

    def do_HEAD(self):
        self.do_GET()

    def do_PUT(self):
        url = urlparse(self.path)
        if url.path == "/api/workflow":
            return self._put_workflow(parse_qs(url.query))
        return self._fail(404, "not found")

    # -- endpoint bodies --------------------------------------------------
    def _serve_builder(self):
        try:
            with open(self.BUILDER, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            return self._fail(500, f"cannot read builder: {exc}")
        return self._send(200, body, "text/html; charset=utf-8")

    def _get_workflow(self, query):
        file = (query.get("file") or [""])[0]
        cand = _safe_repo_yaml(self.ROOT, file)
        if cand is None or not os.path.isfile(cand):
            return self._fail(404, "no such workflow")
        try:
            with open(cand, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            return self._fail(500, f"read failed: {exc}")
        return self._send(200, body, "text/yaml; charset=utf-8")

    def _put_workflow(self, query):
        file = (query.get("file") or [""])[0]
        cand = _safe_repo_yaml(self.ROOT, file, for_write=True)
        if cand is None:
            return self._fail(400, "invalid workflow path")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._fail(400, "bad Content-Length")
        if length > MAX_BODY:
            return self._fail(413, "workflow too large")
        raw = self.rfile.read(length) if length else b""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return self._fail(400, "body must be UTF-8")
        try:
            wfmod.loads(text)  # reject anything outside the accepted YAML subset
        except ValueError as exc:
            return self._fail(400, f"not a valid workflow: {exc}")
        tmp = cand + ".tmp"
        try:
            os.makedirs(os.path.dirname(cand), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, cand)  # atomic
        except OSError as exc:
            return self._fail(500, f"write failed: {exc}")
        return self._json({"ok": True, "file": os.path.basename(cand)})


# ---------------------------------------------------------------- serving

def resolve_builder(args):
    if args.builder:
        return os.path.abspath(args.builder)
    # default: the copy shipped next to this engine (engine/../ui/builder.html)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "ui", "builder.html")


def serve(root, port, builder, open_browser=True):
    Handler.ROOT = os.path.abspath(root)
    Handler.BUILDER = builder
    httpd, bound = None, None
    for candidate in range(port, port + PORT_SCAN):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            bound = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print(f"error: no free port in {port}..{port + PORT_SCAN - 1}", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{bound}/"
    print(f"Maestro UI  ->  {url}")
    print(f"  serving   {Handler.ROOT}")
    print(f"  builder   {builder}")
    print("  Ctrl-C to stop")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — a headless box just gets the printed URL
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ui_server", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root to serve (default: cwd)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("MAESTRO_UI_PORT") or DEFAULT_PORT),
                        help=f"port (default: {DEFAULT_PORT} or $MAESTRO_UI_PORT)")
    parser.add_argument("--builder", help="path to builder.html (default: bundled ui/)")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args(argv)
    builder = resolve_builder(args)
    if not os.path.isfile(builder):
        print(f"error: builder not found: {builder}", file=sys.stderr)
        return 1
    return serve(args.root, args.port, builder, open_browser=not args.no_open)


if __name__ == "__main__":
    sys.exit(main())
