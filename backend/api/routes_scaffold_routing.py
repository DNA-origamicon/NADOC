"""
API layer — auto-scaffold *routing* variant endpoints (extracted from crud.py).

This module hosts the one-click scaffold auto-routing commands — each computes a
Hamiltonian path through the scaffold helices and places the crossovers/seams
for a particular polymerization/seam strategy, under a single feature-log entry:

  POST /design/auto-scaffold-seamed       — seam + near-ends + far-ends (HJ seam)
  POST /design/auto-scaffold-matched      — like seamed, far face = translate of near (blunt-end stacking)
  POST /design/auto-scaffold-seamless     — one end crossover per helix pair (zig-zag)
  POST /design/route-for-polymerization   — fill bare scaffold ends with connector + bridging staples

One reason to change: the set of auto-routing strategies NADOC offers. These
sit under crud.py's ``# ── Sequence assignment endpoints`` banner only by
adjacency — they place crossovers/seams (topology routing), NOT sequences. The
actual sequence-assignment + full-autostaple routes (which DO touch sequences)
stay in crud.py.

The shared response helper ``_design_response_with_geometry`` stays in crud.py
(used by 100+ routes) and is imported back here — same shared-kernel convention
as routes_clusters.py / routes_camera_poses.py. The routing algorithms live in
``backend/core/{seamed_router,seamless_router,polymer_router}.py`` and are
imported function-locally inside each handler exactly as before.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api import state as design_state

# Shared response helper used by 100+ crud.py routes; it stays in crud.py and is
# imported back here (same convention as routes_clusters.py / routes_camera_poses.py).
from backend.api.crud import _design_response_with_geometry

router = APIRouter()


def _run_auto_scaffold_with_feature_log(
    op_kind: str,
    label: str,
    params: dict,
    runner,
):
    """Shared helper: run an auto-scaffold variant under mutate_with_feature_log,
    threading the algorithm's `result` object back out via a closure.

    `runner(design)` must return ``(updated_design, result)``. If ``result.valid``
    is False, raises HTTPException 422.
    """
    holder: dict = {}

    def _fn(d):
        try:
            updated, result = runner(d)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if hasattr(result, "valid") and not result.valid:
            raise HTTPException(status_code=422, detail="; ".join(result.errors))
        holder["result"] = result
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind=op_kind,
        label=label,
        params=params,
        fn=_fn,
    )
    return updated, report, holder["result"]


def _guard_seamed_routable(errors_fn) -> None:
    """Refuse a seamed/matched route (422) that would fragment into a disjoint
    scaffold — an odd-helix group or a shape with no continuous crossover path.

    Runs on the LIVE design BEFORE any state mutation, so a refused route leaves
    the design (and its feature log) untouched; the frontend surfaces ``detail``
    as a toast.  ``errors_fn`` is ``seamed_router.seamed_routability_errors``.
    """
    errs = errors_fn(design_state.get_or_404())
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))


@router.post("/design/auto-scaffold-seamed", status_code=200)
def auto_scaffold_seamed_endpoint() -> dict:
    """Seamed scaffold routing: Create Seam + Create Near Ends + Create Far Ends atomically.

    Computes the Hamiltonian path through scaffold helices, places Holliday-junction
    seam crossovers at interior pairs, extends and connects the near (-lo) face, then
    extends and connects the far (+hi) face.  All three phases share one snapshot.
    """
    from backend.core.seamed_router import (
        auto_scaffold_seamed,
        seamed_routability_errors,
    )

    _guard_seamed_routable(seamed_routability_errors)

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind="auto-scaffold-seamed",
        label="Auto-scaffold (seamed)",
        params={},
        runner=lambda d: auto_scaffold_seamed(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"] = result.warnings
    resp["seam_xovers"] = result.seam_xovers
    resp["near_end_xovers"] = result.near_end_xovers
    resp["far_end_xovers"] = result.far_end_xovers
    return resp


@router.post("/design/auto-scaffold-matched", status_code=200)
def auto_scaffold_matched_endpoint() -> dict:
    """Matched-ends scaffold routing for blunt-end end-to-end polymerization.

    Like seamed routing, but the far (+hi) face is made an exact translate of the
    near (-lo) face by one repeat period (a whole multiple of the lattice
    crossover period), so identical copies stack end-to-end: every helix's far
    cap lands on the next copy's near cap.  Seam marking + sequence assignment
    stay with the existing periodic tools.
    """
    from backend.core.seamed_router import (
        auto_scaffold_matched,
        seamed_routability_errors,
    )

    _guard_seamed_routable(seamed_routability_errors)

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind="auto-scaffold-matched",
        label="Auto-scaffold (matched ends)",
        params={},
        runner=lambda d: auto_scaffold_matched(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"] = result.warnings
    resp["seam_xovers"] = result.seam_xovers
    resp["near_end_xovers"] = result.near_end_xovers
    resp["far_end_xovers"] = result.far_end_xovers
    return resp


@router.post("/design/auto-scaffold-seamless", status_code=200)
def auto_scaffold_seamless_endpoint() -> dict:
    """Seamless scaffold routing: one end crossover per helix pair (zig-zag).

    Computes a Hamiltonian path through scaffold helices, places HJ bridges
    between coverage-signature groups (multi-section designs like dumbbells),
    then places a single end crossover per within-group adjacent pair,
    alternating hi/lo face based on helix parity.
    """
    from backend.core.seamless_router import auto_scaffold_seamless

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind="auto-scaffold-seamless",
        label="Auto-scaffold (seamless)",
        params={},
        runner=lambda d: auto_scaffold_seamless(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"] = result.warnings
    resp["end_xovers"] = result.end_xovers
    resp["bridge_xovers"] = result.bridge_xovers
    return resp


@router.post("/design/route-for-polymerization", status_code=200)
def route_for_polymerization_endpoint() -> dict:
    """Route bare scaffold ends for end-to-end polymerization.

    Fills the single-stranded scaffold left at the two terminal faces with one
    fixed connector staple per bare run, then stitches each face-helix's two
    connectors into a bridging staple across a periodic boundary (exactly one
    flagged ``is_periodic_seam`` so the part becomes Polymerize-Periodic
    eligible and its far face is a translate of its near face).

    Non-blocking: warns (rather than fails) when no Autoscaffold op was run or a
    helix lacks an unpaired end. Hard-errors (422) only when there is nothing to
    route at all.
    """
    from backend.core.polymer_router import route_for_polymerization

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind="route-for-polymerization",
        label="Route for polymerization",
        params={},
        runner=lambda d: route_for_polymerization(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"] = result.warnings
    resp["connector_strand_ids"] = result.new_connector_strand_ids
    resp["seam_ligation_ids"] = result.seam_ligation_ids
    resp["principal_seam_id"] = result.principal_seam_id
    return resp
