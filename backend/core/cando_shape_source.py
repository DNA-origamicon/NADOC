"""C5 — assemble the CanDo FEM source bundle for the cross-engine comparison card (S5).

CanDo is the per-observable reference for RMSF/flexibility in the shared-metric track.
This module turns a CanDo ``predict_shape`` result — the FEM display frame + its per-bp
free-free NMA RMSF (already computed by the solver) — into the
``{engine, descriptors, rmsf, shape_frame, field}`` bundle
:func:`backend.core.shape_compare.build_comparison_report` consumes, so the card shows a
LIVE CanDo column beside the oxDNA one and yields the first real oxDNA-vs-CanDo agreement
numbers.  It is the CanDo twin of :mod:`backend.core.oxdna_shape_source` (O1) and follows
the same SOURCE-BUNDLE CONTRACT.

It is a PURE Physical-layer assembly (Three-Layer Law): no I/O, no topology access, no
engine of its own.  Descriptors come from the SAME locked estimators the metrics use
(:func:`compute_shape_descriptors`), on the same rigid dsDNA-core mask
(:func:`_filter_to_reference_core` against ``core_reference_geometry`` — the ragged
single-stranded ends with ill-defined twist/bend drop out).  The emitted VALUE is CanDo's
ABSOLUTE twist/bend on the predicted frame — the cross-engine-comparable quantity (oxDNA
absolute vs CanDo absolute).

CanDo's NMA RMSF is DIRECTION-LESS (one value per duplex-core base pair, since both strands
share the single axis node), so :func:`_rmsf_profile` emits ``direction=None``.  The
comparison's :func:`_rmsf_per_bp` collapses over strand direction anyway (S3 lesson), so
CanDo's per-bp RMSF still pairs with oxDNA/NAMD per-strand ensemble RMSF instead of leaving
a silently-empty intersection.

Field-response emission is deliberately NOT done here (``field`` defaults to ``None``, and
a caller may pass a pre-built :func:`field_response_profile` result through).  When it is
added, it MUST be built from the RAW ``solve_prestress_shape(field=)`` axis-node frame — NOT
``predict_shape``'s ``positions``, which are per-frame Kabsch-reposed onto the design so a
genuinely-held anchor spuriously drifts ~5 nm (the C2 lesson).
"""
from __future__ import annotations

from backend.core.oxdna_health import _filter_to_reference_core
from backend.core.shape_metrics import compute_shape_descriptors


def _rmsf_profile(rmsf) -> list[dict]:
    """Map CanDo ``predict_shape``'s per-bp NMA RMSF (``{helix_id, bp_index, rmsf_nm}``)
    to the comparison card's RMSF-profile shape (``{helix_id, bp_index, direction, copy,
    rmsf_nm}``).  ``direction`` is ``None`` — CanDo's RMSF is a direction-less axis-node
    value (both strands share the node); the cross-engine collapse ignores direction.
    Entries without an ``rmsf_nm`` value are dropped (a base with no fluctuation sample)."""
    out: list[dict] = []
    for r in rmsf or []:
        v = r.get("rmsf_nm")
        if v is None:
            continue
        out.append({
            "helix_id": r["helix_id"],
            "bp_index": int(r["bp_index"]),
            "direction": None,
            "copy": int(r.get("copy", 0)),
            "rmsf_nm": float(v),
        })
    return out


def build_cando_shape_source(shape_frame, core_reference, *, rmsf=None, field=None) -> dict:
    """The CanDo source bundle for the cross-engine comparison card.

    ``shape_frame`` — the CanDo ``predict_shape`` display frame (``predict_shape(...)
    ["positions"]``: ``{helix_id, bp_index, direction, backbone_position}`` dicts).
    ``core_reference`` — the design's core geometry (``core_reference_geometry(design)``),
    used as the dsDNA-core MASK: only columns present in it survive, so the floppy ssDNA
    ends drop out before the twist/bend descriptors run.  ``rmsf`` — the solver's per-bp NMA
    RMSF list (``predict_shape(...)["rmsf"]``: ``{helix_id, bp_index, rmsf_nm}``), the RMSF
    reference column.  ``field`` — an optional pre-built ``field_response_profile`` result
    (built from the RAW solved frame — see the module docstring).

    Returns ``{engine:"cando", descriptors, rmsf, shape_frame, field}``.  The emitted
    ``descriptors`` and ``shape_frame`` are the CORE-filtered frame; when the core mask
    leaves no columns, both are ``None`` (no comparable frame).  Pure — never touches
    topology.
    """
    core_frame = _filter_to_reference_core(shape_frame or [], core_reference or [])
    descriptors = compute_shape_descriptors(core_frame) if core_frame else None
    return {
        "engine": "cando",
        "descriptors": descriptors,
        "rmsf": _rmsf_profile(rmsf) or None,
        "shape_frame": core_frame or None,
        "field": field,
    }
