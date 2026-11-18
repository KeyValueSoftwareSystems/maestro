"""Route-condition grammar for Maestro workflows.

Exactly four forms (docs/workflow-spec.md) — parsed BEFORE placeholder substitution so
substituted values can never inject operators:

    <text> == <literal>
    <text> != <literal>
    <text> in [a, b, c]
    <text>                # truthy

Comparison normalises numbers and booleans ("3" == 3, "true" == true) and otherwise
compares strings. Truthiness: missing, "", "false", "0", "null", "none" and an empty list or
map ("[]", "{}", also as the JSON text a placeholder renders) are false.
"""

from __future__ import annotations

import re


class CondError(ValueError):
    pass


_IN_RE = re.compile(r"^(.*?)\s+in\s+(\[.*\])$")
_CMP_RE = re.compile(r"^(.*?)\s*(==|!=)\s*(.+)$")


def parse(cond):
    """-> (lhs_text, op, rhs) where op is '==', '!=', 'in' or 'truthy'."""
    cond = cond.strip()
    if not cond:
        raise CondError("empty condition")
    m = _IN_RE.match(cond)
    if m:
        lhs, rhs_src = m.group(1).strip(), m.group(2)
        rhs = _parse_list(rhs_src, cond)
        if not lhs:
            raise CondError(f"missing left-hand side in {cond!r}")
        return lhs, "in", rhs
    m = _CMP_RE.match(cond)
    if m:
        lhs, op, rhs_src = m.group(1).strip(), m.group(2), m.group(3).strip()
        if not lhs:
            raise CondError(f"missing left-hand side in {cond!r}")
        rhs = _parse_literal(rhs_src, cond)
        return lhs, op, rhs
    if re.search(r"==|!=|\sin\s", cond):
        raise CondError(f"malformed comparison in {cond!r}")
    return cond, "truthy", None


def _parse_list(src, cond):
    inner = src[1:-1].strip()
    if not inner:
        raise CondError(f"empty list in condition {cond!r}")
    parts, quote, cur = [], None, []
    for c in inner:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            cur.append(c)
        elif c == ",":
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur).strip())
    if quote:
        raise CondError(f"unterminated string in {cond!r}")
    return [_parse_literal(p, cond) for p in parts if p]


def _parse_literal(src, cond):
    if src[0] in ("'", '"'):
        if len(src) < 2 or src[-1] != src[0]:
            raise CondError(f"unterminated string literal in {cond!r}")
        if src[0] == '"':
            return src[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return src[1:-1].replace("''", "'")
    low = src.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if re.match(r"^-?\d+$", src):
        return int(src)
    if re.match(r"^-?\d+\.\d+$", src):
        return float(src)
    if re.search(r"\s", src):
        raise CondError(f"unquoted literal with spaces in {cond!r}")
    return src


_FALSY = {"", "false", "0", "null", "~", "none"}


def norm(value):
    """Canonical string form used for comparison."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    low = s.lower()
    if low in ("true", "false"):
        return low
    if re.match(r"^-?\d+$", s):
        return str(int(s))
    if re.match(r"^-?\d+\.\d+$", s):
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    return s


_EMPTY_COLLECTION_RE = re.compile(r"^(\[\s*\]|\{\s*\})$")


def truthy(value):
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    text = norm(value).lower()
    return text not in _FALSY and not _EMPTY_COLLECTION_RE.match(text)


def evaluate(cond, substitute):
    """Evaluate `cond`. `substitute(text) -> value` resolves ${...} placeholders in the
    left-hand side (returning None for a missing reference is allowed)."""
    lhs_text, op, rhs = parse(cond)
    lhs = substitute(lhs_text)
    if op == "truthy":
        return truthy(lhs)
    if op == "in":
        return norm(lhs) in {norm(r) for r in rhs}
    if op == "==":
        return norm(lhs) == norm(rhs)
    return norm(lhs) != norm(rhs)
