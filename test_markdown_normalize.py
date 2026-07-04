"""Tests for services.markdown_normalize.repair_unmatched_display_math.

Runs under pytest OR standalone (`python test_markdown_normalize.py`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.markdown_normalize import (
    repair_unmatched_display_math as fix,
    has_unmatched_display_math,
    count_display_delims,
)


def _balanced(md):
    return count_display_delims(md) % 2 == 0


def test_wellformed_unchanged():
    md = "Intro.\n\n$$\na = b + c\n$$\n\nMore.\n\n$$ x^2 $$\n"
    assert fix(md) == md
    assert _balanced(fix(md))


def test_no_math_passthrough():
    md = "Just text with a $5 price and no display math."
    assert fix(md) == md


def test_inline_math_untouched():
    md = "An inline formula $a+b$ stays as-is."
    assert fix(md) == md


def test_the_real_glmocr_defect():
    # The exact malformation observed in doc 200 (stray empty $$ before a block).
    bad = "implies that\n\n$$\n$$\n\\sum_{i=1}^{n} x_i = d R.\n$$\n\ndone"
    out = fix(bad)
    assert has_unmatched_display_math(bad) is True       # input was malformed (odd $$)
    assert has_unmatched_display_math(out) is False      # repaired to even
    assert "\\sum_{i=1}^{n} x_i = d R." in out           # real formula preserved
    # The repaired block is a single well-formed display block around the formula.
    assert out.count("$$") == 2


def test_empty_block_adjacent():
    assert fix("a $$$$ b") == "a  b"                      # empty $$$$ removed
    assert _balanced(fix("a $$$$ b"))


def test_trailing_unmatched_dropped():
    out = fix("text $$ a=b $$ and a dangling $$ here")
    assert _balanced(out)
    assert "a=b" in out and "dangling" in out


def test_idempotent():
    bad = "x\n\n$$\n$$\nE=mc^2\n$$\n"
    once = fix(bad)
    assert fix(once) == once
    assert _balanced(once)


def test_multiple_strays():
    bad = "$$\n$$\nA=1\n$$\n\ntext\n\n$$\n$$\nB=2\n$$"
    out = fix(bad)
    assert _balanced(out)
    assert "A=1" in out and "B=2" in out
    assert out.count("$$") == 4                          # two clean blocks remain


if __name__ == "__main__":
    import traceback
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print(f"PASS  {name}")
        except Exception:
            failed += 1; print(f"FAIL  {name}"); traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
