"""Strict-subset YAML loader/emitter for Maestro workflow and state files.

Zero-dependency by design: the pack must run on any dev machine with only a Python 3
interpreter. The subset is locked in docs/workflow-spec.md — block mappings and lists,
single-line flow lists/maps, plain/quoted scalars, `|` / `|-` block literals, comments.
Anchors, aliases, tags, folded scalars and multi-document files are rejected. The builder
UI emits only this subset, so files round-trip between js-yaml and this module.
"""

from __future__ import annotations

import re


class WfError(ValueError):
    def __init__(self, msg, line=None):
        self.line = line
        super().__init__(f"line {line}: {msg}" if line else msg)


# ---------------------------------------------------------------- loading

_UNSUPPORTED_LEAD = ("&", "*", "!", "%", ">", "@", "`")

_BOOLS = {"true": True, "false": False}
_NULLS = {"null", "~"}

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")


class _Line:
    __slots__ = ("indent", "text", "no")

    def __init__(self, indent, text, no):
        self.indent, self.text, self.no = indent, text, no


def loads(text):
    if text.startswith("﻿"):
        text = text[1:]
    raw_lines = text.splitlines()
    lines = []
    for no, raw in enumerate(raw_lines, 1):
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        if stripped == "---":
            # A document separator only at column 0. An indented `---` (e.g. a markdown
            # rule inside a `|` block literal) is consumed by the literal's line range.
            if lines:
                raise WfError("multi-document files are not supported", no)
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if "\t" in raw[: indent + 1]:
            raise WfError("tabs are not allowed in indentation", no)
        lines.append(_Line(indent, stripped.strip(), no))
    if not lines:
        return {}
    value, pos = _parse_block(lines, 0, raw_lines)
    if pos != len(lines):
        raise WfError("unexpected content", lines[pos].no)
    return value


def _strip_comment(raw):
    """Remove a trailing comment, respecting quotes. Full-line comments become empty."""
    out = []
    quote = None
    i = 0
    while i < len(raw):
        c = raw[i]
        if quote:
            if quote == "'" and c == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                quote = None
            elif quote == '"':
                if c == "\\" and i + 1 < len(raw):
                    out.append(raw[i : i + 2])
                    i += 2
                    continue
                if c == '"':
                    quote = None
            out.append(c)
            i += 1
            continue
        if c in ("'", '"') and (i == 0 or raw[i - 1] in " \t:,[{-"):
            # a quote only OPENS at a token boundary (mid-word apostrophes are literal)
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or raw[i - 1] in " \t"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _is_list_item(line):
    return line.text == "-" or line.text.startswith("- ")


def _parse_block(lines, pos, raw_lines):
    if _is_list_item(lines[pos]):
        return _parse_list(lines, pos, lines[pos].indent, raw_lines)
    return _parse_map(lines, pos, raw_lines)


def _parse_list(lines, pos, indent, raw_lines):
    items = []
    while pos < len(lines) and lines[pos].indent == indent and _is_list_item(lines[pos]):
        line = lines[pos]
        rest = line.text[1:].lstrip()
        if not rest:  # bare "-": nested block value
            pos += 1
            if pos >= len(lines) or lines[pos].indent <= indent:
                items.append(None)
                continue
            value, pos = _parse_block(lines, pos, raw_lines)
            items.append(value)
            continue
        key, _ = _try_key(rest)
        if key is not None:
            # "- key: value" — a mapping whose further keys sit at the content column.
            item_indent = line.indent + (len(line.text) - len(rest))
            fake = _Line(item_indent, rest, line.no)
            value, pos = _parse_map_entries(fake, lines, pos + 1, raw_lines)
            items.append(value)
        else:
            items.append(_parse_scalar(rest, line.no))
            pos += 1
    return items, pos


def _parse_map(lines, pos, raw_lines):
    return _parse_map_entries(lines[pos], lines, pos + 1, raw_lines)


def _parse_map_entries(first, lines, pos, raw_lines):
    """Parse a mapping whose first `key: …` line is `first`; siblings share its indent."""
    out = {}
    line = first
    while True:
        key, rest = _try_key(line.text)
        if key is None:
            raise WfError(f"expected 'key:' but got {line.text!r}", line.no)
        if key in out:
            raise WfError(f"duplicate key {key!r}", line.no)
        if rest in ("|", "|-"):
            value, pos = _parse_block_literal(lines, pos, line, rest == "|-", raw_lines)
            out[key] = value
        elif rest in (">", ">-"):
            raise WfError("folded scalars (>) are not supported", line.no)
        elif rest:
            out[key] = _parse_scalar(rest, line.no)
        else:
            if pos < len(lines) and lines[pos].indent > line.indent:
                value, pos = _parse_block(lines, pos, raw_lines)
                out[key] = value
            elif pos < len(lines) and lines[pos].indent == line.indent and _is_list_item(lines[pos]):
                # list at the same indent as its key — common human style
                value, pos = _parse_list(lines, pos, line.indent, raw_lines)
                out[key] = value
            else:
                out[key] = None
        if pos >= len(lines) or lines[pos].indent < line.indent:
            return out, pos
        nxt = lines[pos]
        if nxt.indent > line.indent:
            raise WfError("bad indentation", nxt.no)
        if _is_list_item(nxt):
            return out, pos
        line = nxt
        pos += 1


def _parse_block_literal(lines, pos, key_line, strip_final, raw_lines):
    """Collect the raw body of a `|` block, preserving inner '#' and blank lines."""
    body_lines = []
    body_indent = None
    i = key_line.no  # 0-based index of the first candidate body line in raw_lines
    while i < len(raw_lines):
        raw = raw_lines[i]
        if not raw.strip():
            body_lines.append("")
            i += 1
            continue
        this_indent = len(raw) - len(raw.lstrip(" "))
        if this_indent <= key_line.indent:
            break
        if body_indent is None:
            body_indent = this_indent
        if this_indent < body_indent:
            break
        body_lines.append(raw[body_indent:])
        i += 1
    while body_lines and body_lines[-1] == "":
        body_lines.pop()
    text = "\n".join(body_lines)
    if not strip_final and text:
        text += "\n"
    last_body_no = i  # raw line numbers 1..i are consumed
    while pos < len(lines) and key_line.no < lines[pos].no <= last_body_no:
        pos += 1
    return text, pos


_KEY_RE_PLAIN = re.compile(r"^([^\s:#'\"\[\]{},][^:]*?):(\s+|$)")


def _scan_quoted(text):
    """Index just past the closing quote of a quoted scalar at text[0], else None."""
    q = text[0]
    i = 1
    while i < len(text):
        c = text[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < len(text) and text[i + 1] == "'":
                i += 2  # '' escape
                continue
            return i + 1
        i += 1
    return None


def _try_key(text):
    if text and text[0] in ("'", '"'):
        # a quoted token is a key ONLY if the maximal quoted scalar is followed by ':'
        end = _scan_quoted(text)
        if end is None:
            return None, None
        rest = text[end:]
        if rest == ":" or rest.startswith(": ") or rest.rstrip() == ":":
            return _unquote(text[:end]), rest[1:].strip()
        return None, None
    m = _KEY_RE_PLAIN.match(text)
    if m:
        return _unquote(m.group(1)), text[m.end() :].strip()
    return None, None


def _unquote(token):
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        body = token[1:-1]
        return re.sub(
            r"\\(.)",
            lambda m: {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(
                m.group(1), "\\" + m.group(1)
            ),
            body,
        )
    if len(token) >= 2 and token[0] == "'" and token[-1] == "'":
        return token[1:-1].replace("''", "'")
    return token


def _parse_scalar(text, no):
    text = text.strip()
    if not text:
        return None
    if text[0] in _UNSUPPORTED_LEAD:
        raise WfError(f"unsupported YAML feature at {text[:12]!r}", no)
    if text[0] == "[":
        return _parse_flow_list(text, no)
    if text[0] == "{":
        return _parse_flow_map(text, no)
    if text[0] in ("'", '"'):
        if len(text) < 2 or text[-1] != text[0]:
            raise WfError("unterminated quoted string", no)
        return _unquote(text)
    low = text.lower()
    if low in _NULLS:
        return None
    if low in _BOOLS:
        return _BOOLS[low]
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _parse_flow_list(text, no):
    parts = _split_flow(text, no, "]")
    return [_parse_flow_value(p, no) for p in parts]


def _parse_flow_map(text, no):
    parts = _split_flow(text, no, "}")
    out = {}
    for part in parts:
        key, rest = _try_key(part)
        if key is None:
            raise WfError(f"expected 'key: value' in flow map, got {part!r}", no)
        out[key] = _parse_flow_value(rest, no)
    return out


def _parse_flow_value(text, no):
    if text.startswith("["):
        return _parse_flow_list(text, no)
    if text.startswith("{"):
        return _parse_flow_map(text, no)
    return _parse_scalar(text, no)


def _split_flow(text, no, closer):
    if text[-1] != closer:
        raise WfError(f"flow collection must close with {closer!r} on the same line", no)
    inner = text[1:-1].strip()
    if not inner:
        return []
    parts, depth, quote, cur = [], 0, None, []
    prev = ""
    for c in inner:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
            prev = c
            continue
        if c in ("'", '"') and (prev == "" or prev in " :,[{"):
            quote = c
            cur.append(c)
        elif c in "[{":
            depth += 1
            cur.append(c)
        elif c in "]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            prev = ","
            continue
        else:
            cur.append(c)
        prev = c
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------- dumping

_PLAIN_OK = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./ ${}()<>=!*+@-]*$")


def dumps(obj):
    out = []
    _dump(obj, out, 0)
    return "\n".join(out) + "\n"


def _dump(obj, out, indent):
    pad = " " * indent
    if isinstance(obj, dict):
        if not obj:
            out.append(pad + "{}")
            return
        for key, value in obj.items():
            _dump_entry(f"{pad}{_dump_key(key)}:", value, out, indent)
    elif isinstance(obj, list):
        if not obj:
            out.append(pad + "[]")
            return
        for item in obj:
            if isinstance(item, dict) and item:
                sub = []
                _dump(item, sub, indent + 2)
                out.append(f"{pad}- " + sub[0][indent + 2 :])
                out.extend(sub[1:])
            elif isinstance(item, dict):
                out.append(f"{pad}- {{}}")
            elif isinstance(item, list):
                out.append(f"{pad}- {_dump_flow(item) if item else '[]'}")
            else:
                out.append(f"{pad}- {_dump_scalar(item)}")
    else:
        out.append(pad + _dump_scalar(obj))


def _literal_safe(s):
    """True if a multi-line string round-trips through a `|`/`|-` block literal.

    The emitter has no indentation-indicator or line-folding, so a string is only
    literal-safe when the loader can recover it byte-for-byte: no carriage returns
    (splitlines would split on them), no whitespace-only interior line (reloaded as a
    blank), and no leading whitespace on the first content line (which would inflate the
    inferred block indent and truncate later lines). Anything else falls back to a
    double-quoted scalar with escapes.
    """
    if "\r" in s:
        return False
    body = s[:-1] if s.endswith("\n") else s
    seen_content = False
    for line in body.split("\n"):
        if not line:
            continue
        if line.strip() == "":
            return False
        if not seen_content:
            if line[0] in " \t":
                return False
            seen_content = True
    return True


def _dump_entry(prefix, value, out, indent):
    pad = " " * indent
    if isinstance(value, str) and "\n" in value and _literal_safe(value):
        marker = "|" if value.endswith("\n") else "|-"
        out.append(f"{prefix} {marker}")
        body = value[:-1] if value.endswith("\n") else value
        for bl in body.split("\n"):
            out.append(f"{pad}  {bl}" if bl else "")
    elif isinstance(value, dict):
        if not value:
            out.append(f"{prefix} {{}}")
        elif _flowable(value):
            out.append(f"{prefix} {_dump_flow(value)}")
        else:
            out.append(prefix)
            _dump(value, out, indent + 2)
    elif isinstance(value, list):
        if not value:
            out.append(f"{prefix} []")
        elif _flowable(value):
            out.append(f"{prefix} {_dump_flow(value)}")
        else:
            out.append(prefix)
            _dump(value, out, indent + 2)
    else:
        out.append(f"{prefix} {_dump_scalar(value)}")


def _flowable(value):
    """Small leaf collections render inline: {a: b} / [a, b]."""
    items = value if isinstance(value, list) else list(value.values())
    if any(isinstance(v, (dict, list)) or (isinstance(v, str) and "\n" in v) for v in items):
        return False
    return len(_dump_flow(value)) <= 100


def _dump_flow(value):
    if isinstance(value, list):
        return "[" + ", ".join(_dump_scalar(v) for v in value) + "]"
    return "{" + ", ".join(f"{_dump_key(k)}: {_dump_scalar(v)}" for k, v in value.items()) + "}"


def _dump_key(key):
    key = str(key)
    if _PLAIN_OK.match(key) and ":" not in key and not key.endswith(" "):
        return key
    return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value)
    if s == "":
        return '""'
    low = s.lower()
    needs_quote = (
        not _PLAIN_OK.match(s)
        or low in _BOOLS
        or low in _NULLS
        or bool(_INT_RE.match(s))
        or bool(_FLOAT_RE.match(s))
        or s != s.strip()
        or s.startswith(("- ", "? "))
        or ": " in s
        or s.endswith(":")
        or s[0] in "[{#&*!|>%@`'\"~"
    )
    if needs_quote:
        body = (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{body}"'
    return s


# ---------------------------------------------------------------- file io

def load_file(path):
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read())


def dump_file(path, obj):
    import os

    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dumps(obj))
    os.replace(tmp, path)
