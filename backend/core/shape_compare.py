"""Cross-engine comparison report — the data behind the S5 comparison card.

The shared-metric track (S1–S4) built the *math* that puts every engine's prediction
on one comparable footing:

    S1  ``compute_shape_descriptors``   — one scalar descriptor set per frame
    S2  ``deviation_profile`` / ``rmsf_from_ensemble`` / ``normalize_rmsf_profile``
    S3  ``compare_descriptors`` / ``reference_for`` — per-observable agreement + policy
    S4  ``field_response_profile`` / ``compare_field_response`` — E-field deflection

This module (S5) is the thin, PURE assembly that turns a list of per-engine source
bundles into ONE report the comparison card renders/exports: a scalar table (each
engine's value + signed %-delta vs the per-observable reference), per-engine RMSF
profiles for the overlay, cross-engine agreement scores, and — when a field stage ran —
a field-deflection panel.  It only composes the S1–S4 functions; it computes no physics
of its own and reads only Physical-layer position/descriptor dicts (Three-Layer Law).

A *source bundle* is what each engine's own task (O1/C5/M5/N4) will emit for the current
design::

    {"engine": "oxdna",
     "descriptors": <compute_shape_descriptors output> | None,
     "rmsf":        [{helix_id, bp_index, rmsf_nm, direction?, copy?}, …] | None,
     "shape_frame": <display-position map> | None,
     "field":       <field_response_profile output> | None}

The per-observable reference (which engine is the denominator) follows the S3 policy via
``reference_for`` — oxDNA for shape+field, CanDo for RMSF, NAMD overriding all when
present.  Every comparison degrades gracefully: a bundle missing an observable simply
doesn't contribute to that observable's rows, and with only one engine present the report
still carries that engine's raw scalar values (no deltas).
"""
from __future__ import annotations

from backend.core.shape_metrics import (
    COMPARABLE_SCALARS,
    _rmsf_per_bp,
    compare_descriptors,
    compare_field_response,
    reference_for,
    twist_profile,
)


def _rmsf_profile_points(profile) -> list[list[float]]:
    """A plottable ``[[ordinal, rmsf_nm], …]`` series for one engine's RMSF profile,
    collapsed to per-base-pair (``_rmsf_per_bp``) and sorted by ``(helix, bp, copy)`` so
    the x-axis is a stable base-pair ordinal.  The overlay compares curve SHAPE; the
    quantitative bp-matched agreement is the Pearson/Spearman in the agreement table."""
    per_bp = _rmsf_per_bp(profile or [])
    return [[float(i), float(per_bp[k])] for i, k in enumerate(sorted(per_bp))]


def _twist_profile_points(shape_frame) -> list[list[float]]:
    """A plottable ``[[axial_nm, cumulative_twist_deg], …]`` series for one engine's
    core-filtered ``shape_frame`` (its bundle CUMULATIVE twist vs axial distance from the
    start, the last y = the scalar ``twist_total_deg``).  ``[]`` for a frame that can't
    define twist (<2 helices)."""
    return [[float(x), float(y)] for x, y in twist_profile(shape_frame or [])]


def build_comparison_report(sources) -> dict:
    """Assemble the cross-engine comparison report from per-engine source bundles.

    ``sources`` is a list of source bundles (see the module docstring).  Returns::

        {"ready": bool,                 # False only when no engine is present
         "engines": [name, …],
         "references": {"shape", "rmsf", "field"},   # per-observable reference engine | None
         "scalars": [{"name", "reference",
                      "cells": {engine: {"value", "signed_pct_delta"}}}, …],
         "rmsf_profiles": [{"engine", "is_reference", "points": [[ord, rmsf], …]}, …],
         "twist_profiles": [{"engine", "is_reference", "points": [[axial_nm, twist_deg], …]}, …],
         "agreement": [{"engine",                      # one row per non-trivial candidate
                        "shape_rmsd_nm",               # vs the shape reference | None
                        "rmsf": {pearson, spearman, n, …} | None,   # vs the RMSF reference
                        "field": {cosine_similarity, magnitude_ratio, n_shared_free} | None},
                       …],
         "field": {"reference", "rows": [{engine, anchored_max_drift_nm,
                    free_proj_along_field_nm, passed, cosine_vs_ref,
                    magnitude_ratio}, …]} | None}

    Pure: composes ``compare_descriptors`` / ``compare_field_response`` / ``reference_for``
    — no I/O, no topology access.
    """
    sources = [s for s in (sources or []) if s and s.get("engine")]
    engines = [s["engine"] for s in sources]
    by_engine = {s["engine"]: s for s in sources}

    if not engines:
        return {"ready": False, "engines": [], "references": {},
                "scalars": [], "rmsf_profiles": [], "agreement": [], "field": None,
                "reason": "no engine sources supplied"}

    shape_ref = reference_for(engines, "shape")
    rmsf_ref = reference_for(engines, "rmsf")
    field_ref = reference_for(engines, "field")   # policy reference (for the references dict)
    # For the field comparison/panel the reference must actually CARRY field data — else the
    # policy engine (e.g. oxDNA) would be labelled the reference while contributing no
    # deflection, and every cosine-vs-ref would be a misleading None.  Resolve it among the
    # field-carrying engines only (None when the policy engine isn't one of them).
    field_engines = [e for e in engines if by_engine[e].get("field")]
    field_cmp_ref = reference_for(field_engines, "field") if field_engines else None

    # ── Scalar table: each engine's descriptor value + signed %-delta vs shape_ref ──
    ref_desc = (by_engine.get(shape_ref, {}).get("descriptors") or {}) if shape_ref else {}
    scalars: list[dict] = []
    for name in COMPARABLE_SCALARS:
        cells: dict = {}
        rv = ref_desc.get(name)
        for eng in engines:
            v = (by_engine[eng].get("descriptors") or {}).get(name)
            pct = None
            if shape_ref and eng != shape_ref and v is not None and rv not in (None, 0):
                pct = (float(v) - float(rv)) / abs(float(rv)) * 100.0
            cells[eng] = {"value": v, "signed_pct_delta": pct}
        scalars.append({"name": name, "reference": shape_ref, "cells": cells})

    # ── RMSF profiles (per-engine overlay) ─────────────────────────────────────────
    rmsf_profiles = [
        {"engine": eng, "is_reference": eng == rmsf_ref,
         "points": _rmsf_profile_points(by_engine[eng].get("rmsf"))}
        for eng in engines if by_engine[eng].get("rmsf")
    ]

    # ── Twist profiles (per-engine overlay) ────────────────────────────────────────
    # Cumulative twist vs axial distance, from each engine's core-filtered shape_frame;
    # the reference (shape) engine is flagged so the overlay colours it consistently.
    # Only engines whose frame actually defines twist (≥2 helices) contribute a curve.
    twist_profiles = []
    for eng in engines:
        pts = _twist_profile_points(by_engine[eng].get("shape_frame"))
        if pts:
            twist_profiles.append(
                {"engine": eng, "is_reference": eng == shape_ref, "points": pts})

    # ── Agreement rows: each candidate engine scored against the per-observable refs ─
    agreement: list[dict] = []
    for eng in engines:
        is_shape_ref = eng == shape_ref
        is_rmsf_ref = eng == rmsf_ref
        shape_rmsd = None
        if shape_ref and not is_shape_ref:
            shape_rmsd = compare_descriptors(
                by_engine[eng], by_engine[shape_ref])["shape_rmsd_nm"]
        rmsf_ag = None
        if rmsf_ref and not is_rmsf_ref:
            rmsf_ag = compare_descriptors(
                by_engine[eng], by_engine[rmsf_ref])["rmsf"]
        field_ag = None
        if (field_cmp_ref and eng != field_cmp_ref
                and by_engine[eng].get("field") and by_engine[field_cmp_ref].get("field")):
            field_ag = compare_field_response(
                by_engine[eng]["field"], by_engine[field_cmp_ref]["field"])
        if shape_rmsd is None and rmsf_ag is None and field_ag is None:
            continue
        agreement.append({"engine": eng, "shape_rmsd_nm": shape_rmsd,
                          "rmsf": rmsf_ag, "field": field_ag})

    # ── Field panel: per-engine deflection verdict + agreement vs the field reference ─
    field = None
    if field_engines:
        ref_field = by_engine.get(field_cmp_ref, {}).get("field") if field_cmp_ref else None
        rows = []
        for eng in field_engines:
            prof = by_engine[eng]["field"]
            cmp = (compare_field_response(prof, ref_field)
                   if ref_field is not None and eng != field_cmp_ref else None)
            rows.append({
                "engine": eng,
                "is_reference": eng == field_cmp_ref,
                "anchored_max_drift_nm": prof.get("anchored_max_drift_nm"),
                "free_proj_along_field_nm": prof.get("free_proj_along_field_nm"),
                "passed": prof.get("passed"),
                "cosine_vs_ref": cmp["cosine_similarity"] if cmp else None,
                "magnitude_ratio": cmp["magnitude_ratio"] if cmp else None,
            })
        field = {"reference": field_cmp_ref, "rows": rows}

    return {
        "ready": True,
        "engines": engines,
        "references": {"shape": shape_ref, "rmsf": rmsf_ref, "field": field_ref},
        "scalars": scalars,
        "rmsf_profiles": rmsf_profiles,
        "twist_profiles": twist_profiles,
        "agreement": agreement,
        "field": field,
    }
