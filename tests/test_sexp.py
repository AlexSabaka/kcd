"""Tests for the S-expression core (`kcd.core.sexp`)."""

from __future__ import annotations

import pytest

from kcd.core.sexp import Quoted, dumps, parse


def test_parse_nested_structure() -> None:
    assert parse('(a (b 1) (c "x"))') == ["a", ["b", "1"], ["c", "x"]]


def test_parse_distinguishes_quoted_from_bare() -> None:
    """Bare atoms (list heads, keywords, numbers) vs double-quoted tokens."""
    tree = parse('(symbol "R" passive)')
    assert tree[0] == "symbol" and not isinstance(tree[0], Quoted)
    assert tree[1] == "R" and isinstance(tree[1], Quoted)
    assert tree[2] == "passive" and not isinstance(tree[2], Quoted)


def test_roundtrip_preserves_structure_and_quoting() -> None:
    src = '(kicad_symbol_lib (version 20231120) (symbol "R" (property "Value" "10k")))'
    assert parse(dumps(parse(src))) == parse(src)
    redumped = dumps(parse(src))
    assert '"R"' in redumped           # quoted token re-quoted
    assert "(version 20231120)" in redumped  # bare atoms stay bare


def test_empty_quoted_string_roundtrips() -> None:
    tree = parse('(name "" (x 0))')
    assert tree[1] == "" and isinstance(tree[1], Quoted)
    assert parse(dumps(tree)) == tree


def test_escapes_in_quoted_string() -> None:
    tree = parse(r'(text "a\"b\\c")')
    assert tree[1] == 'a"b\\c'
    assert parse(dumps(tree))[1] == 'a"b\\c'


def test_atom_only_form_stays_inline() -> None:
    assert dumps(parse("(at 0 3.81 270)")) == "(at 0 3.81 270)"


@pytest.mark.parametrize("bad", ["", "(a (b)", ")"])
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse(bad)
