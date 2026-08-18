#!/usr/bin/env python3
"""render_doc.py — deterministic Markdown -> self-contained HTML for stage artifacts.

Stdlib-only (no third-party markdown lib), matching the engine's zero-dependency rule.
Turns a stage's committed .md (PRD, HLD, LLD, review pack…) into ONE self-contained,
theme-aware HTML fragment with no external assets. That fragment is:

  * publish-ready — it is <style> + content with no <html>/<head>/<body>, exactly what
    a harness artifact publisher (Claude Code) wraps; and
  * locally openable — a browser renders <style> + content fine on its own, so Cursor /
    Codex users just open the file.

Renders the Markdown subset the SDLC skills emit: ATX headings, paragraphs, bold/italic,
inline code, fenced code blocks, unordered/ordered lists, pipe tables, blockquotes,
horizontal rules and links.

Usage:
    python3 render_doc.py INPUT.md [OUTPUT.html] [--title "Title"]

Deterministic: identical input -> byte-identical output (no timestamps, no randomness),
so it is golden-set testable like the rest of the engine.
"""
import html
import os
import re
import sys

# --------------------------------------------------------------------------- inline

_CODE_SENTINEL = "\x00"


def _inline(text):
    """Inline Markdown -> HTML. Escape first, protect code spans, then bold/italic/links."""
    spans = []

    def _stash(m):
        spans.append(m.group(1))
        return f"{_CODE_SENTINEL}{len(spans) - 1}{_CODE_SENTINEL}"

    text = re.sub(r"`([^`]+)`", _stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)

    def _restore(m):
        return "<code>" + html.escape(spans[int(m.group(1))], quote=False) + "</code>"

    return re.sub(rf"{_CODE_SENTINEL}(\d+){_CODE_SENTINEL}", _restore, text)


# --------------------------------------------------------------------------- table


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _table(rows):
    head = _cells(rows[0])
    body = [_cells(r) for r in rows[2:]]
    out = ['<div class="tbl"><table>', "<thead><tr>"]
    out += [f"<th>{_inline(h)}</th>" for h in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


_HR = re.compile(r"(-{3,}|\*{3,}|_{3,})$")
_BLOCK_START = re.compile(r"(#{1,6}\s|[-*]\s|\d+\.\s|>|```)")


# --------------------------------------------------------------------------- blocks


def md_to_body(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    stack = []  # open list tags: "ul" / "ol"
    i, n = 0, len(lines)

    def close_lists():
        while stack:
            out.append(f"</{stack.pop()}>")

    while i < n:
        raw = lines[i]
        line = raw.strip()

        if line.startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            out.append("<pre><code>" + html.escape("\n".join(buf), quote=False) + "</code></pre>")
            continue

        if line == "":
            close_lists()
            i += 1
            continue

        if _HR.fullmatch(line):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"(#{1,6})\s+(.*)$", line)
        if m:
            close_lists()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # pipe table: header row + a separator row of dashes/pipes/colons
        if "|" in line and i + 1 < n and "-" in lines[i + 1] and re.match(
            r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]
        ):
            close_lists()
            rows = [lines[i], lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        if line.startswith(">"):
            close_lists()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + _inline(" ".join(buf)) + "</blockquote>")
            continue

        m = re.match(r"[-*]\s+(.*)$", line)
        if m:
            if not stack or stack[-1] != "ul":
                close_lists()
                out.append("<ul>")
                stack.append("ul")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        m = re.match(r"\d+\.\s+(.*)$", line)
        if m:
            if not stack or stack[-1] != "ol":
                close_lists()
                out.append("<ol>")
                stack.append("ol")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        # paragraph: gather following non-block lines
        close_lists()
        buf = [line]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not _BLOCK_START.match(lines[i].strip())
            and not _HR.fullmatch(lines[i].strip())
        ):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(buf)) + "</p>")

    close_lists()
    return "\n".join(out)


# --------------------------------------------------------------------------- shell

_CSS = """
:root{--bg:#fbfaf7;--panel:#fff;--ink:#1c1b19;--muted:#6e6a61;--faint:#97928a;
--line:#e9e4da;--accent:#c1852a;--code-bg:#f4f0e8;
--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#171613;--panel:#201e1a;--ink:#f1ece2;
--muted:#a29b90;--faint:#7c766c;--line:#322e28;--accent:#e0a94a;--code-bg:#262320}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6}
.doc{max-width:820px;margin:0 auto;padding:clamp(24px,5vw,60px) clamp(16px,4vw,40px) 80px}
.doc-kicker{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
color:var(--faint);margin:0 0 26px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.doc h1{font-family:var(--serif);font-size:clamp(26px,4.5vw,38px);line-height:1.12;
font-weight:600;margin:0 0 18px;letter-spacing:-.01em}
.doc h2{font-family:var(--serif);font-size:23px;font-weight:600;margin:38px 0 12px;
padding-bottom:8px;border-bottom:2px solid var(--ink)}
.doc h3{font-size:17px;font-weight:700;margin:28px 0 8px}
.doc h4{font-size:14px;font-weight:700;margin:22px 0 6px;color:var(--muted)}
.doc h5,.doc h6{font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;
color:var(--faint);margin:20px 0 6px}
.doc p{margin:0 0 14px}
.doc a{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 40%,transparent)}
.doc strong{font-weight:700}
.doc ul,.doc ol{margin:0 0 14px;padding-left:22px}
.doc li{margin:4px 0}
.doc code{font-family:var(--mono);font-size:.88em;background:var(--code-bg);
padding:1px 6px;border-radius:5px}
.doc pre{background:var(--code-bg);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;overflow-x:auto;margin:0 0 16px}
.doc pre code{background:none;padding:0;font-size:12.5px;line-height:1.5}
.doc blockquote{margin:0 0 16px;padding:2px 16px;border-left:3px solid var(--accent);
color:var(--muted)}
.doc hr{border:0;border-top:1px solid var(--line);margin:28px 0}
.tbl{overflow-x:auto;margin:0 0 18px}
.doc table{border-collapse:collapse;width:100%;font-size:13.5px}
.doc th,.doc td{border:1px solid var(--line);padding:8px 12px;text-align:left;vertical-align:top}
.doc th{background:var(--code-bg);font-weight:600}
.doc tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--ink) 2%,transparent)}
"""


def render(md, title=None):
    """Markdown string -> self-contained HTML fragment (str)."""
    if title is None:
        m = re.search(r"^#\s+(.+)$", md, re.M)
        title = m.group(1).strip() if m else "Document"
    body = md_to_body(md)
    css = re.sub(r"\n\s*", "", _CSS).strip()  # minify for stable, compact output
    return (
        '<meta charset="utf-8">\n'
        f"<style>{css}</style>\n"
        '<main class="doc">\n'
        f'<p class="doc-kicker">Stage artifact · {html.escape(title, quote=False)}</p>\n'
        f"{body}\n"
        "</main>\n"
    )


# --------------------------------------------------------------------------- cli


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    title = None
    for a in argv:
        if a.startswith("--title="):
            title = a[len("--title="):]
    if len(argv) >= 2 and "--title" in argv:
        j = argv.index("--title")
        if j + 1 < len(argv):
            title = argv[j + 1]
            args = [a for a in args if a != title]
    if not args:
        sys.stderr.write("usage: render_doc.py INPUT.md [OUTPUT.html] [--title T]\n")
        return 2
    src = args[0]
    dst = args[1] if len(args) > 1 else os.path.splitext(src)[0] + ".html"
    with open(src, "r", encoding="utf-8") as fh:
        md = fh.read()
    out = render(md, title)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
