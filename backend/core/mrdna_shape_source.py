"""M5 — assemble the mrDNA source bundle for the cross-engine comparison card (S5).

mrDNA is a CANDIDATE engine in the shared-metric track (it is the reference for no
observable — oxDNA is the SHAPE reference, CanDo the RMSF reference, NAMD the gold override).
This module turns a completed mrDNA coarse relaxation's readouts — the reconstructed relaxed
display frame + a per-nucleotide RMSF from the CG trajectory ensemble — into the
``{engine, descriptors, rmsf, shape_frame, field}`` bundle
:func:`backend.core.shape_compare.build_comparison_report` consumes, so the card shows a LIVE
mrDNA column (its absolute twist/bend cross-validated against oxDNA's relaxed shape).  It is
the mrDNA twin of :mod:`backend.core.oxdna_shape_source` (O1) /
:mod:`backend.core.cando_shape_source` (C5) and follows the same SOURCE-BUNDLE CONTRACT.

It is a PURE Physical-layer assembly (Three-Layer Law): no I/O, no topology access, no engine
of its own.  Descriptors come from the SAME locked estimators the metrics use
(:func:`compute_shape_descriptors`) on the rigid dsDNA-core mask
(:func:`_filter_to_reference_core` against ``core_reference_geometry`` — the ragged
single-stranded ends with ill-defined twist/bend drop out).  The emitted VALUE is mrDNA's
ABSOLUTE twist/bend on the relaxed frame — the cross-engine-comparable quantity.

COPY-KEY GAP (the M5-specific fix).  mrDNA's ``_display_positions`` emits crossover extra-base
inserts as ``{helix_id:"__xb__", bp_index:<crossover-id string>, direction:k}`` entries (so the
native insert beads follow the relaxed junction on screen).  Their ``bp_index`` is a *string*,
which crashes the shared ``_dev_key`` (``int(bp_index)``) — oxDNA never lets them into its
source (``configuration_full`` drops ``__xb__``).  The gap bites the SHAPE column: the display
frame handed to this builder DOES carry those inserts, and ``_filter_to_reference_core`` /
``_core_column_key`` drop them (non-int ``bp_index`` → not in the core) before
``compute_shape_descriptors`` ever runs.  The RMSF list, by contrast, comes from
``mrdna_trajectory_rmsf`` → per-frame ``nuc_pos_override_display_from_coarse``, which emits only
integer ``(helix,bp,dir)`` keys (no ``__xb__``); :func:`_rmsf_profile` still skips any non-int
``bp_index`` defensively (so a hand-built RMSF list can't smuggle one in), but in production the
RMSF path never produces one.

Field-response emission is deferred (``field`` defaults to ``None``; a caller may pass a
pre-built :func:`field_response_profile` result through) — a natural follow-up once an anchored
mrDNA field run's relaxed frame is on hand, built the way M2 applies the field.
"""
from __future__ import annotations

from backend.core.oxdna_health import _filter_to_reference_core
from backend.core.shape_metrics import compute_shape_descriptors


def _rmsf_profile(rmsf) -> list[dict]:
    """Map a per-nucleotide RMSF list (``{helix_id, bp_index, direction, copy, rmsf_nm}``,
    e.g. from :func:`rmsf_from_ensemble` over the CG trajectory) to the comparison card's
    RMSF-profile shape.  Entries without an ``rmsf_nm`` value are dropped (a base with no
    fluctuation sample); entries whose ``bp_index`` is not an integer are dropped too — the
    ``__xb__`` extra-base inserts, which are not part of the comparable dsDNA core (the
    copy-key gap)."""
    out: list[dict] = []
    for p in rmsf or []:
        v = p.get("rmsf_nm")
        if v is None:
            continue
        bp = p.get("bp_index")
        if not isinstance(bp, int):   # __xb__ inserts (string crossover id) drop out
            continue
        direction = p.get("direction")
        out.append({
            "helix_id": p["helix_id"],
            "bp_index": bp,
            "direction": getattr(direction, "value", direction),
            "copy": int(p.get("copy", 0)),
            "rmsf_nm": float(v),
        })
    return out


def build_mrdna_shape_source(shape_frame, core_reference, *, rmsf=None, field=None) -> dict:
    """The mrDNA source bundle for the cross-engine comparison card.

    ``shape_frame`` — the mrDNA relaxed display-position list (``_display_positions`` output:
    ``{helix_id, bp_index, direction, backbone_position}`` dicts, possibly including the
    string-``bp_index`` ``__xb__`` inserts).  ``core_reference`` — the design's core geometry
    (``core_reference_geometry(design)``), used as the dsDNA-core MASK: only columns present in
    it survive, so the floppy ssDNA ends AND the ``__xb__`` inserts drop out before the
    twist/bend descriptors run.  ``rmsf`` — an optional per-nucleotide RMSF list from the CG
    trajectory ensemble.  ``field`` — an optional pre-built ``field_response_profile`` result.

    Returns ``{engine:"mrdna", descriptors, rmsf, shape_frame, field}``.  The emitted
    ``descriptors`` and ``shape_frame`` are the CORE-filtered frame; when the core mask leaves
    no columns, both are ``None`` (no comparable frame).  Pure — never touches topology.
    """
    core_frame = _filter_to_reference_core(shape_frame or [], core_reference or [])
    descriptors = compute_shape_descriptors(core_frame) if core_frame else None
    return {
        "engine": "mrdna",
        "descriptors": descriptors,
        "rmsf": _rmsf_profile(rmsf) or None,
        "shape_frame": core_frame or None,
        "field": field,
    }
