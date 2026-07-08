"""N4 — assemble the NAMD source bundle for the cross-engine comparison card (S5).

NAMD is the GOLD-OVERRIDE engine of the shared-metric track: once a NAMD run for a design
exists, its descriptors become the reference for EVERY observable (shape, RMSF, field),
overriding the oxDNA-shape / CanDo-RMSF policy (:func:`shape_metrics.reference_for` returns
``"namd"`` for every observable when it is present).  This module turns a NAMD run's readouts
— the time-mean backbone structure over the aligned trajectory + a per-nucleotide RMSF, BOTH
produced in one pass by :func:`backend.core.md_trajectory.md_rmsf` — into the
``{engine, descriptors, rmsf, shape_frame, field}`` bundle
:func:`backend.core.shape_compare.build_comparison_report` consumes, so the card shows a LIVE
NAMD column and NAMD becomes the reference the other engines are scored against.  It is the
NAMD twin of :mod:`backend.core.oxdna_shape_source` (O1) /
:mod:`backend.core.cando_shape_source` (C5) / :mod:`backend.core.mrdna_shape_source` (M5) and
follows the same SOURCE-BUNDLE CONTRACT.

It is a PURE Physical-layer assembly (Three-Layer Law): no I/O, no topology access, no engine
of its own.  Descriptors come from the SAME locked estimators the MD "Graphs and Metrics" card
uses (:func:`compute_shape_descriptors`) on the rigid dsDNA-core mask
(:func:`_filter_to_reference_core` against ``core_reference_geometry`` — the ragged
single-stranded ends with ill-defined twist/bend drop out).  The emitted VALUE is NAMD's
ABSOLUTE twist/bend on the time-mean structure — the cross-engine-comparable quantity.

``md_rmsf`` emits ONE Kabsch-aligned positions list where each entry carries BOTH the mean
``backbone_position`` (the low-noise time-mean shape) AND the per-nucleotide ``rmsf`` — so the
caller passes that same list as both ``shape_frame`` (read for the shape) and
``rmsf_positions`` (read for the fluctuation), exactly as O1 does with ``production_rmsf``.  Its
positions use the same ``rmsf`` key + string ``direction`` as oxDNA's, so the remap and core
filter are identical to O1.

Field-response emission is deferred (``field`` defaults to ``None``; a caller may pass a
pre-built :func:`field_response_profile` result through) — the natural follow-up once an
anchored NAMD field run's trajectory is on hand, built the way N1 applies the field.
"""
from __future__ import annotations

from backend.core.oxdna_health import _filter_to_reference_core
from backend.core.shape_metrics import compute_shape_descriptors


def _rmsf_profile(rmsf_positions) -> list[dict]:
    """Map ``md_rmsf`` positions (``{helix_id, bp_index, direction, backbone_position, rmsf}``)
    to the comparison card's RMSF-profile shape (``{helix_id, bp_index, direction, copy,
    rmsf_nm}``).  Entries with no ``rmsf`` value are dropped (a base with no fluctuation
    sample).  Identical to O1's remap — NAMD's trajectory RMSF uses the same ``rmsf`` key."""
    out: list[dict] = []
    for p in rmsf_positions or []:
        r = p.get("rmsf")
        if r is None:
            continue
        direction = p.get("direction")
        out.append({
            "helix_id": p["helix_id"],
            "bp_index": int(p["bp_index"]),
            "direction": getattr(direction, "value", direction),
            "copy": int(p.get("copy", 0)),
            "rmsf_nm": float(r),
        })
    return out


def build_namd_shape_source(shape_frame, core_reference, *,
                            rmsf_positions=None, field=None) -> dict:
    """The NAMD source bundle for the cross-engine comparison card.

    ``shape_frame`` — the NAMD time-mean display-position list (``md_rmsf(...)["positions"]``:
    ``{helix_id, bp_index, direction, backbone_position, rmsf}`` dicts).  ``core_reference`` —
    the design's core geometry (``core_reference_geometry(design)``), used as the dsDNA-core
    MASK: only columns present in it survive, so the floppy ssDNA ends drop out before the
    twist/bend descriptors run.  ``rmsf_positions`` — the same ``md_rmsf`` positions list, read
    for the per-nucleotide ``rmsf`` (the gold-override RMSF column).  ``field`` — an optional
    pre-built ``field_response_profile`` result.

    Returns ``{engine:"namd", descriptors, rmsf, shape_frame, field}``.  The emitted
    ``descriptors`` and ``shape_frame`` are the CORE-filtered frame; when the core mask leaves
    no columns, both are ``None`` (no comparable frame).  Pure — never touches topology.
    """
    core_frame = _filter_to_reference_core(shape_frame or [], core_reference or [])
    descriptors = compute_shape_descriptors(core_frame) if core_frame else None
    return {
        "engine": "namd",
        "descriptors": descriptors,
        "rmsf": _rmsf_profile(rmsf_positions) or None,
        "shape_frame": core_frame or None,
        "field": field,
    }
