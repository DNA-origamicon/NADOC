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


# ── Sub-domain tiling / sequence / annotations (Refactor #39) ────────────────
#
# Pure metadata logic for ``OverhangSpec.sub_domains``, service-pushed out of
# crud.py's ``# ── Sub-domains`` region. Sub-domains tile an overhang gap-lessly
# 5'→3' and may carry a sequence_override + cached annotations. These functions
# resolve backing-domain lengths, slice each sub-domain's effective sequence,
# compute its Tm/GC/hairpin/dimer annotation cache, and validate the tiling
# invariants. All are HTTP-free: the tiling validator raises
# :class:`SubDomainTilingError` (a status-carrying domain error) which the crud
# shim (``_validate_sub_domain_tiling``) translates into ``HTTPException`` so
# core never imports fastapi (L4/L15).

_DNA_BASES = set("ACGTN")


class SubDomainTilingError(Exception):
    """Raised when an overhang's sub-domain tiling violates an invariant.

    Carries an HTTP-style ``status`` + ``detail`` so the thin api shim can
    re-raise it as an ``HTTPException`` without core importing fastapi.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _ovhg_domain_lengths(design) -> dict:
    """Return {overhang_id: domain_length_bp} for every overhang domain.

    Uses abs() because REVERSE-direction domains have start_bp > end_bp.
    """
    result = {}
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id is not None:
                result[domain.overhang_id] = abs(domain.end_bp - domain.start_bp) + 1
    return result


def _ovhg_backing_length(design: Design, overhang_id: str) -> Optional[int]:
    """Resolve the backing-domain length for a given overhang id.

    Returns None when no domain references the overhang (e.g. orphaned spec).
    Mirrors the convention used by ``_ovhg_domain_lengths``.
    """
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id == overhang_id:
                return abs(domain.end_bp - domain.start_bp) + 1
    return None


def validate_sub_domain_tiling(design: Design, overhang_id: str) -> None:
    """Raise :class:`SubDomainTilingError` if the overhang's tiling is broken.

    Invariants enforced:
      • Σ length_bp == backing domain length.
      • Offsets contiguous (each sd.start_bp_offset == previous end).
      • Every length_bp ≥ 1.
      • Each ``sequence_override`` (if set) has length == length_bp and bases
        in ACGTN.

    Designed to run after every mutating sub-domain endpoint.
    """
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None:
        raise SubDomainTilingError(404, f"Overhang {overhang_id!r} not found.")
    sub_doms = sorted(ovhg.sub_domains, key=lambda sd: sd.start_bp_offset)
    if not sub_doms:
        raise SubDomainTilingError(422, f"Overhang {overhang_id!r} has no sub-domains.")

    expected_offset = 0
    for sd in sub_doms:
        if sd.length_bp < 1:
            raise SubDomainTilingError(422, (
                f"Sub-domain {sd.name!r} ({sd.id}) has length_bp < 1."
            ))
        if sd.start_bp_offset != expected_offset:
            raise SubDomainTilingError(422, (
                f"Sub-domains on overhang {overhang_id!r} are not gap-less "
                f"(sub-domain {sd.name!r} starts at {sd.start_bp_offset}, "
                f"expected {expected_offset})."
            ))
        if sd.sequence_override is not None:
            if len(sd.sequence_override) != sd.length_bp:
                raise SubDomainTilingError(422, (
                    f"Sub-domain {sd.name!r} ({sd.id}) sequence_override length "
                    f"({len(sd.sequence_override)}) != length_bp ({sd.length_bp})."
                ))
            if any(b not in _DNA_BASES for b in sd.sequence_override.upper()):
                raise SubDomainTilingError(422, (
                    f"Sub-domain {sd.name!r} ({sd.id}) sequence_override contains "
                    f"non-ACGTN bases."
                ))
        expected_offset += sd.length_bp

    backing = _ovhg_backing_length(design, overhang_id)
    if backing is not None and expected_offset != backing:
        raise SubDomainTilingError(422, (
            f"Sub-domain tiling sum ({expected_offset}) != backing domain length "
            f"({backing}) for overhang {overhang_id!r}."
        ))


def _resolve_sub_domain_sequence(ovhg, sub_dom) -> Optional[str]:
    """Return the effective 5'→3' sequence for *sub_dom* (override or parent slice).

    Returns ``None`` when neither the sub-domain nor the parent overhang has a
    sequence (Tm/GC/structure annotations are undefined in that case).
    """
    if sub_dom.sequence_override:
        return sub_dom.sequence_override.upper()
    parent = ovhg.sequence
    if not parent:
        return None
    start = sub_dom.start_bp_offset
    end = start + sub_dom.length_bp
    slice_ = parent.upper()[start:end]
    if len(slice_) < sub_dom.length_bp:
        return None
    return slice_


def _compute_sub_domain_annotations(seq: Optional[str], na_mM: float, conc_nM: float) -> dict:
    """Return the annotation cache dict for *seq*; safely handles None / 'N's."""
    from backend.core.overhang_generator import has_hairpin, has_dimer
    from backend.core.thermo import tm_nn, gc_content
    if not seq:
        return {
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    tm = tm_nn(seq, na_mM=na_mM, conc_nM=conc_nM)
    gc = gc_content(seq) if all(b in "ACGT" for b in seq) else None
    # has_hairpin / has_dimer are robust to short sequences.
    try:
        hp = has_hairpin(seq) if all(b in "ACGT" for b in seq) else False
    except Exception:
        hp = False
    try:
        dm = has_dimer(seq) if all(b in "ACGT" for b in seq) else False
    except Exception:
        dm = False
    return {
        "tm_celsius": tm,
        "gc_percent": gc,
        "hairpin_warning": hp,
        "dimer_warning": dm,
    }


# ── Boundary-hairpin scan + overhang replacement (Refactor #40) ──────────────
#
# Pure model transforms service-pushed out of crud.py's ``# ── Sub-domains``
# region. ``_replace_ovhg`` rebuilds a Design with one overhang swapped (a
# ``model_copy``); ``_apply_boundary_hairpin_warnings`` re-runs the
# boundary-hairpin detector + the inner-sequence annotation scan and toggles
# each sub-domain's ``hairpin_warning`` accordingly. Both are HTTP-free and
# state-free — they take a :class:`Design` and return a new one — so they live
# in core and the crud handlers import them back (api → core).


def _replace_ovhg(design: Design, new_spec) -> Design:
    new_overhangs = [new_spec if o.id == new_spec.id else o for o in design.overhangs]
    return design.model_copy(update={"overhangs": new_overhangs})


def _apply_boundary_hairpin_warnings(design: Design, overhang_id: str) -> Design:
    """Toggle ``hairpin_warning`` on sub-domains based on boundary-hairpin scan.

    Phase 3 (overhang revamp): after any sub-domain sequence change, scan every
    pair of adjacent sub-domains for a hairpin spanning their junction
    (see ``backend.core.overhang_generator.detect_boundary_hairpins``). Both
    sub-domains touching a flagged boundary get ``hairpin_warning=True`` *added*;
    sub-domains that previously had a warning solely from a boundary that no
    longer reports get it cleared.

    The detector flags BOUNDARIES, not sub-domains. We translate by collecting
    every sub-domain id that touches at least one flagged boundary into a "warn"
    set, and clearing the flag on everyone else (so user fixes propagate
    immediately).

    Note: this does NOT clobber per-sub-domain hairpin warnings flagged by the
    inner-sequence scan (``_compute_sub_domain_annotations``). Callers always
    invoke the inner scan first (which sets ``hairpin_warning`` from the inner
    bases), so when the boundary scan then unions in boundary-driven warnings,
    the existing inner-warning bit is preserved via the explicit ``or``.
    """
    from backend.core.overhang_generator import detect_boundary_hairpins
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None or not ovhg.sub_domains:
        return design
    reports = detect_boundary_hairpins(ovhg)
    boundary_warn_ids: set[str] = set()
    for r in reports:
        boundary_warn_ids.add(r["sub_domain_a_id"])
        boundary_warn_ids.add(r["sub_domain_b_id"])

    # Re-evaluate inner-sequence hairpin status per sub-domain so a stale boundary
    # warning clears when the actual inner sequence has no hairpin AND the
    # boundary no longer fires. This keeps user-visible warnings honest.
    new_sub_doms = []
    changed = False
    for sd in ovhg.sub_domains:
        seq = _resolve_sub_domain_sequence(ovhg, sd)
        ann = _compute_sub_domain_annotations(
            seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
        )
        inner_hp = bool(ann.get("hairpin_warning"))
        bdy_hp   = sd.id in boundary_warn_ids
        new_hp   = inner_hp or bdy_hp
        if new_hp != sd.hairpin_warning:
            changed = True
            new_sub_doms.append(sd.model_copy(update={"hairpin_warning": new_hp}))
        else:
            new_sub_doms.append(sd)
    if not changed:
        return design
    new_ovhg = ovhg.model_copy(update={"sub_domains": new_sub_doms})
    return _replace_ovhg(design, new_ovhg)
