"""
Hinge scaffold router — single-strand routing for forced-ligation hinge designs
(two rigid leaves bridged across a physical gap by cross-gap scaffold links).

Approach (compliant retry, 2026-06-26).  The earlier attempt built a bespoke
single-pass raster and regressed the seamed contract (no seams, no scaffold-end
extension).  This version instead routes through the EXISTING, proven seamed
pipeline so seams + extended ssDNA ends come for free, and is **self-gated**
against ``scaffold_routing_invariants`` so it can never return a non-compliant
routing — it falls back to the caller's classic pipeline if anything is off.

How it works:

  1. The hinge primitive's cross-gap bridges are encoded as 2-domain scaffold
     SEED strands (the link spans both leaves).  The forced-ligation *records*
     are provenance for those seeds.  Temporarily DROP the FL records — the seed
     strands themselves still connect the leaves — and run ``auto_scaffold_seamed``.
     With the bridges carried by the seeds, the seamed router routes the whole
     thing to ONE strand with proper seams and extended ends.
  2. Re-derive a ForcedLigation for each in-strand junction that crosses the gap
     (a junction between two helices that are NOT lattice scaffold-neighbours),
     so the gap bridges are recorded against the actual routed topology.
  3. Self-gate: require exactly one scaffold strand, every original cross-gap
     helix-pair re-bridged, and ``scaffold_routing_invariants`` clean.  Otherwise
     return ``None`` (the caller falls back — no regression).

Generalisation note (2026-06-26): extending this to arbitrary 2×(2n) hinges was
investigated.  Reuse-based approaches (adjacency augmentation, route+splice, and
an FL-preserving hybrid that weaves the path through every bridge) all FAIL for
n>1 because the seamed router's uniform double-pass requires the inner connection
to be a mid-helix SEAM, while a forced ligation connects at the helix END — so a
seam on a bridged helix needs a second gap crossing the bridge can't supply and
the return pass fragments off.  The gold hand-route avoids this with an asymmetric
single-pass / double-pass inner structure that the uniform machinery cannot
express; reproducing it needs a from-scratch weave generator (not yet built).
See ``memory/project_hinge_autoscaffold.md`` (GENERALIZATION INVESTIGATION).

Three-Layer Law: only topology + the seamed router's helix-axis extension.
"""

from __future__ import annotations

from backend.core.models import Design, ForcedLigation
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import (
    SeamedResult,
    _build_adj,
    _scaffold_coverage,
)


def _scaffold_strands(design: Design):
    return [s for s in design.strands if s.is_scaffold and not s.is_reference]


def route_hinge(design: Design) -> tuple[Design, SeamedResult] | None:
    """Route a forced-ligation hinge to one seamed, compliant scaffold strand.

    Returns ``(updated_design, result)`` or ``None`` (caller falls back).

    First tries the from-scratch weave realizer (``hinge_weave_router``), which
    threads every gap rung and handles arbitrary leaf thickness / column count;
    it is self-gated, so on any miss we fall through to the original single-link
    drop-and-rederive path below (itself self-gated → classic fallback).
    """
    if not design.forced_ligations:
        return None

    from backend.core.hinge_weave_router import realize_hinge_weave

    woven = realize_hinge_weave(design.model_copy(deep=True))
    if woven is not None:
        return woven

    coverage = _scaffold_coverage(design)
    if not coverage:
        return None
    adj = _build_adj(design, coverage)

    # Scaffold routing owns only FLs whose endpoints are both scaffold; overhang /
    # staple-binding FLs (e.g. a ``bound end to root`` overhang duplex) are carried
    # through untouched.
    scaf_fls = [
        fl for fl in design.forced_ligations
        if fl.three_prime_helix_id in coverage and fl.five_prime_helix_id in coverage
    ]
    other_fls = [
        fl for fl in design.forced_ligations
        if fl.three_prime_helix_id not in coverage or fl.five_prime_helix_id not in coverage
    ]
    if not scaf_fls:
        return None

    # Cross-gap helix pairs = scaffold-FL endpoints that are NOT lattice
    # scaffold-neighbours (the physical gap).  An FL between lattice-adjacent helices
    # is a genuine one-off manual anchor, not a hinge bridge → decline so it is
    # preserved as-is.
    gap_pairs: set[tuple[str, str]] = set()
    for fl in scaf_fls:
        a, b = fl.three_prime_helix_id, fl.five_prime_helix_id
        if b in adj.get(a, set()):
            return None  # lattice-adjacent → not a gap bridge
        gap_pairs.add((min(a, b), max(a, b)))

    # ── Route the seeds (scaffold FL records dropped, others kept) through the
    #    proven seamed pipeline ──
    from backend.core.seamed_router import auto_scaffold_seamed

    seed = design.model_copy(update={"forced_ligations": list(other_fls)})
    routed, result = auto_scaffold_seamed(seed.model_copy(deep=True))

    scaf = _scaffold_strands(routed)
    if len(scaf) != 1:
        return None  # bridges did not coalesce into a single strand → fall back
    strand = scaf[0]

    # ── Re-derive ForcedLigation records from the in-strand gap crossings ────────
    new_fls: list[ForcedLigation] = []
    bridged: set[tuple[str, str]] = set()
    for a_dom, b_dom in zip(strand.domains, strand.domains[1:]):
        key = (min(a_dom.helix_id, b_dom.helix_id), max(a_dom.helix_id, b_dom.helix_id))
        if key not in gap_pairs:
            continue
        new_fls.append(ForcedLigation(
            three_prime_helix_id=a_dom.helix_id,
            three_prime_bp=a_dom.end_bp,
            three_prime_direction=a_dom.direction,
            five_prime_helix_id=b_dom.helix_id,
            five_prime_bp=b_dom.start_bp,
            five_prime_direction=b_dom.direction,
        ))
        bridged.add(key)

    # Every gap bridge present in the input must be carried by the routed strand.
    if bridged != gap_pairs:
        return None

    out = routed.model_copy(update={"forced_ligations": new_fls + list(other_fls)})

    # ── Self-gate: never return a non-compliant routing (the regression gate) ────
    if scaffold_routing_invariants(out, require_seams=True):
        return None

    return out, result
