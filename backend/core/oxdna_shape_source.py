"""O1 — assemble the oxDNA source bundle for the cross-engine comparison card (S5).

oxDNA is the per-observable reference for relaxed SHAPE (and field deflection) in the
shared-metric track.  This module turns oxDNA readouts already read off disk — the relaxed
display frame, the production/field RMSF map, an optional field-response profile — into the
``{engine, descriptors, rmsf, shape_frame, field}`` bundle
:func:`backend.core.shape_compare.build_comparison_report` consumes, so the comparison card
shows a LIVE oxDNA column instead of an empty ``getSources``.

It is a PURE Physical-layer assembly (Three-Layer Law): no I/O, no topology access, no
engine of its own.  The descriptors come from the SAME locked ``oxdna_health`` estimators
the Graphs-&-Metrics card uses (:func:`compute_shape_descriptors` composes
``measure_bundle_twist`` / the chord-sagitta bend / Rg), on the same rigid dsDNA-core mask
(:func:`_filter_to_reference_core` against ``core_reference_geometry``, so the ragged
single-stranded ends with ill-defined twist/bend drop out).  Note the VALUE is oxDNA's
ABSOLUTE twist/bend on the relaxed frame — the cross-engine-comparable quantity (oxDNA
absolute vs CanDo absolute).  It is deliberately NOT the DIFFERENTIAL (measured − analytic)
twist/curvature the Graphs-&-Metrics card plots over the production trajectory, so the two
numbers are not expected to be equal — same estimator, different reference and frame.
"""
from __future__ import annotations

from backend.core.oxdna_health import _filter_to_reference_core
from backend.core.shape_metrics import compute_shape_descriptors


def _rmsf_profile(rmsf_positions) -> list[dict]:
    """Map ``production_rmsf`` positions (``{helix_id, bp_index, direction, copy, rmsf}``)
    to the comparison card's RMSF profile shape (``{helix_id, bp_index, direction, copy,
    rmsf_nm}``).  Entries with no ``rmsf`` value are dropped (a base with no fluctuation
    sample), so a partial map yields a partial profile rather than ``None`` rmsf_nm."""
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


def build_oxdna_shape_source(shape_frame, core_reference, *,
                             rmsf_positions=None, field=None) -> dict:
    """The oxDNA source bundle for the cross-engine comparison card.

    ``shape_frame`` — the relaxed display-position list (``{helix_id, bp_index, direction,
    backbone_position}`` dicts, e.g. from the ``/display`` reader).  ``core_reference`` —
    the design's core geometry (``core_reference_geometry(design)``), used as the dsDNA-core
    MASK: only columns present in it survive, so the floppy ssDNA ends are dropped before
    the twist/bend descriptors run.  ``rmsf_positions`` — an optional ``production_rmsf``
    position map (RMSF from the trajectory).  ``field`` — an optional
    ``field_response_profile`` result (a field run's deflection map).

    Returns ``{engine:"oxdna", descriptors, rmsf, shape_frame, field}``.  The emitted
    ``descriptors`` and ``shape_frame`` are the CORE-filtered frame (so cross-engine
    twist/bend/shape-RMSD compare the rigid core only); when the core mask leaves no
    columns, both are ``None`` (no comparable frame).  Pure — never touches topology.
    """
    core_frame = _filter_to_reference_core(shape_frame or [], core_reference or [])
    descriptors = compute_shape_descriptors(core_frame) if core_frame else None
    rmsf = _rmsf_profile(rmsf_positions) or None
    return {
        "engine": "oxdna",
        "descriptors": descriptors,
        "rmsf": rmsf,
        "shape_frame": core_frame or None,
        "field": field,
    }
