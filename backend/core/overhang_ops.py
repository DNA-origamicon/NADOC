"""Core service — overhang end-polarity & linker-compatibility rules.

Pure topology business logic lifted out of ``backend/api/crud.py``'s
``# ── Overhang connections`` region (service push, Refactor #38). These
functions decide, from overhang ids / attach points / linker type alone,
whether two overhangs may be joined by a ss/ds linker and produce the
human-readable error message when they may not. They are the Watson-Crick
polarity rule that governs ``POST /design/overhang-connections``.

They have **zero api dependency**: no ``HTTPException``, no ``design_state``,
no ``_build_*`` builder — they take a :class:`Design` (read-only) plus plain
strings and return values. The api handler keeps the HTTP translation (turn a
returned error string into ``HTTPException(400, ...)``); the rule itself is
testable directly (no ``TestClient``). The dependency arrow is api → core.

Of the six functions here, three are the public entry points the crud handler
calls back (``_overhang_end``, ``_used_overhang_ends``,
``_check_linker_compatibility``); the other three (``_comp_first_polarity``,
``_ds_polarity_message``, ``_ss_polarity_message``) are only ever called by
their siblings here and so stay module-private (L17).
"""

from typing import Optional

from backend.core.models import Design


def _overhang_end(ovhg_id: str) -> Optional[str]:
    """Parse `_5p` / `_3p` suffix from an overhang id, or None if absent."""
    if ovhg_id.endswith("_5p"): return "5p"
    if ovhg_id.endswith("_3p"): return "3p"
    return None


def _used_overhang_ends(
    design: Design, exclude_conn_id: Optional[str] = None,
) -> set[tuple[str, str]]:
    """Collect every (overhang_id, attach) tuple already in use, optionally
    excluding a single connection (e.g. the one being patched in place)."""
    used: set[tuple[str, str]] = set()
    for c in design.overhang_connections:
        if exclude_conn_id is not None and c.id == exclude_conn_id:
            continue
        used.add((c.overhang_a_id, c.overhang_a_attach))
        used.add((c.overhang_b_id, c.overhang_b_attach))
    return used


def _comp_first_polarity(end_type: Optional[str], attach: str) -> Optional[bool]:
    """Side polarity for linker topology / pairing.

    "Comp-first" means the linker strand on this side traverses
    [complement, bridge] (5' → 3'); the bridge attaches at the complement's
    3' end, which lands at:
      • OH's free_tip when the OH is 5' (since 5p OH's free_tip is at start_bp,
        and complement 3' lands at start_bp);
      • OH's root when the OH is 3' (3p OH's root is at start_bp).

    Returns True (comp-first), False (bridge-first), or None when the end type
    is unknown (synthetic fixtures with no _5p/_3p suffix).
    """
    if end_type is None:
        return None
    if end_type == "5p":
        return attach == "free_end"
    if end_type == "3p":
        return attach == "root"
    return None


def _check_linker_compatibility(
    end_a: Optional[str],
    end_b: Optional[str],
    attach_a: str,
    attach_b: str,
    linker_type: str,
) -> Optional[str]:
    """Return an error message if the combination is physically invalid, else None.

    The rule is one Watson-Crick polarity test applied across all four end-pair
    categories (5p+5p, 3p+3p, 5p+3p, 3p+5p). Define each side's polarity:

        comp_first := (5p AND free_end) OR (3p AND root)

    A dsDNA linker requires `comp_first(A) == comp_first(B)` so the two bridge
    halves on the virtual `__lnk__` helix run antiparallel and form a real
    duplex. The mixed-polarity case puts both halves in the same 5'→3'
    direction along `__lnk__` — non-physical.

    A ssDNA linker is the inverse: the single strand traverses
    [complement_a, bridge, complement_b] (5'→3'), so the boundary at A is at
    complement_a's 3' (comp-first) and at B is at complement_b's 5'
    (bridge-first). Therefore the two sides MUST disagree on polarity:
    `comp_first(A) != comp_first(B)`.

    Both rules collapse to a single check; only the desired equality flips
    between the two linker types.
    """
    cfa = _comp_first_polarity(end_a, attach_a)
    cfb = _comp_first_polarity(end_b, attach_b)
    if cfa is None or cfb is None:
        # Unknown polarity for one or both sides — let caller proceed (matches
        # legacy fixture-friendly behaviour). Real designs always have _5p/_3p
        # tags, so this only covers synthetic OverhangSpec records in tests.
        return None
    if linker_type == "ds":
        if cfa == cfb:
            return None
        return _ds_polarity_message(end_a, end_b, attach_a, attach_b)
    if linker_type == "ss":
        if cfa != cfb:
            return None
        return _ss_polarity_message(end_a, end_b, attach_a, attach_b)
    return None


def _ds_polarity_message(end_a: str, end_b: str, attach_a: str, attach_b: str) -> str:
    if end_a == end_b:
        return (
            f"dsDNA linker between two {end_a} ends needs matching attach "
            f"(both root or both free end) so the two bridge halves pair antiparallel."
        )
    return (
        f"dsDNA linker between a {end_a} and a {end_b} end needs OPPOSITE "
        f"attach (one root, one free end) so the two bridge halves pair antiparallel."
    )


def _ss_polarity_message(end_a: str, end_b: str, attach_a: str, attach_b: str) -> str:
    if end_a == end_b:
        return (
            f"ssDNA linker between two {end_a} ends needs OPPOSITE attach "
            f"(one root, one free end) so the bridge can be one continuous 5'→3' strand."
        )
    return (
        f"ssDNA linker between a {end_a} and a {end_b} end needs matching attach "
        f"(both root or both free end) so the bridge can be one continuous 5'→3' strand."
    )
