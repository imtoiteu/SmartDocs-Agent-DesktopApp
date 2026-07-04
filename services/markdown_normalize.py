"""
SmartDocs Platform — OCR Markdown normalization
===============================================
OCR engines that emit Markdown — notably GLM-OCR, a sampling-based VLM — can
occasionally produce an unmatched or empty ``$$`` display-math delimiter. A single
stray ``$$`` makes the total count odd, and the viewer pairs ``$$…$$`` non-greedily,
so the bad delimiter flips the pairing and dumps real formulas into the page as
raw LaTeX.

This module repairs the Markdown at the artifact-generation layer — BEFORE it is
persisted — so malformed Markdown never reaches the renderer. The renderer is left
unchanged.

Scope: only display-math ``$$`` delimiters are touched. Inline ``$…$`` and all other
content are passed through verbatim. Well-formed Markdown is returned unchanged
(the function is idempotent).
"""

from __future__ import annotations


def count_display_delims(md: str) -> int:
    """Number of ``$$`` delimiters (a well-formed document has an even count)."""
    return md.count("$$") if md else 0


def has_unmatched_display_math(md: str) -> bool:
    """True if the document contains an odd number of ``$$`` delimiters."""
    return count_display_delims(md) % 2 == 1


def repair_unmatched_display_math(md: str) -> str:
    """Repair unmatched / empty ``$$`` display-math delimiters.

    Algorithm — scan ``$$`` left to right as alternating open/close:
      * a genuine block (``$$`` … non-empty body … ``$$``) is kept verbatim;
      * an empty / whitespace-only block (a stray duplicate opener) has its opener
        dropped, re-pairing the closer with the next ``$$``;
      * a final unmatched ``$$`` (no closer) is dropped.

    Whitespace and all non-math content are preserved. Returns the input unchanged
    when there is nothing to repair.
    """
    if not md or "$$" not in md:
        return md

    out = []
    i = 0
    while True:
        op = md.find("$$", i)
        if op < 0:                      # no more openers
            out.append(md[i:])
            break
        out.append(md[i:op])            # text before the opener
        cl = md.find("$$", op + 2)
        if cl < 0:                      # unmatched trailing "$$": drop it, keep the rest
            out.append(md[op + 2:])
            break
        body = md[op + 2:cl]
        if body.strip():                # genuine display block — keep verbatim
            out.append("$$" + body + "$$")
            i = cl + 2
        else:                           # empty/stray block — drop opener, keep body, re-pair
            out.append(body)
            i = cl
    return "".join(out)
