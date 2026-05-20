"""Minimal S-expression reader/writer for KiCad files.

KiCad's `.kicad_sym` / `.kicad_sch` / `.kicad_pcb` files are S-expressions.
kicad-skip parses `.kicad_sch` but not standalone `.kicad_sym` libraries, so
kcd needs its own parser for the library layer (Wave 3) — and Waves 4-5 reuse
it to splice symbol definitions into a project's `lib_symbols`.

A parsed node is one of:
  - `list`    — a `( ... )` form
  - `Quoted`  — a token that was double-quoted in the source
  - `str`     — a bare atom (a list head, a keyword like `yes`, or a number)

`Quoted` is a `str` subclass: consumers compare it like any string
(`node[0] == "symbol"`), but `dumps` knows to re-quote it. Round-trip is
semantic, not byte-identical — KiCad reformats on save anyway.
"""

from __future__ import annotations

Node = "list | Quoted | str"

_WHITESPACE = " \t\r\n"
_DELIMS = ' \t\r\n()"'
_UNESCAPE = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}


class Quoted(str):
    """A string atom that was double-quoted in the source. `dumps` re-quotes it."""

    __slots__ = ()


def parse(text: str) -> list:
    """Parse one S-expression and return its top-level list.

    Raises:
        ValueError: empty input, an unexpected `)`, or an unbalanced form.
    """
    tokens = _tokenize(text)
    if not tokens:
        raise ValueError("empty s-expression")

    pos = 0

    def build() -> object:
        nonlocal pos
        kind, val = tokens[pos]
        if kind == "(":
            pos += 1
            node: list = []
            while pos < len(tokens) and tokens[pos][0] != ")":
                node.append(build())
            if pos >= len(tokens):
                raise ValueError("unbalanced s-expression: missing ')'")
            pos += 1  # consume ')'
            return node
        if kind == ")":
            raise ValueError("unexpected ')'")
        pos += 1
        return Quoted(val) if kind == "str" else val

    return build()  # type: ignore[return-value]


def dumps(node: object, indent: int = 0) -> str:
    """Serialize a node back to S-expression text (tab-indented, KiCad-ish).

    Atom-only forms stay on one line; forms containing sub-forms break across
    lines with their leading atoms kept on the opening line.
    """
    if not isinstance(node, list):
        return _atom(node)
    if not node:
        return "()"
    if not any(isinstance(c, list) for c in node):
        return "(" + " ".join(_atom(c) for c in node) + ")"

    # Multiline: keep leading non-list atoms on the opening line.
    lead = 1
    while lead < len(node) and not isinstance(node[lead], list):
        lead += 1
    head = "(" + " ".join(_atom(c) for c in node[:lead])
    child_pad = "\t" * (indent + 1)
    body = "".join(
        "\n" + child_pad + dumps(c, indent + 1) for c in node[lead:]
    )
    return head + body + "\n" + "\t" * indent + ")"


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _WHITESPACE:
            i += 1
        elif c == "(":
            out.append(("(", ""))
            i += 1
        elif c == ")":
            out.append((")", ""))
            i += 1
        elif c == '"':
            i += 1
            buf: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(_UNESCAPE.get(text[i + 1], text[i + 1]))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1  # closing quote
            out.append(("str", "".join(buf)))
        else:
            start = i
            while i < n and text[i] not in _DELIMS:
                i += 1
            out.append(("atom", text[start:i]))
    return out


def _needs_quote(s: str) -> bool:
    return s == "" or any(c in s for c in _DELIMS) or "\\" in s


def _atom(node: object) -> str:
    s = str(node)
    if isinstance(node, Quoted) or _needs_quote(s):
        esc = (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{esc}"'
    return s
