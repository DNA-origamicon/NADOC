"""Headless ssDNA flexible-segment relax — a faithful Python port of the
frontend PBD constraint solver.

The in-app *Relax flexible segments* command pulls the rigid leaves of a hinge
together until every unpaired-ssDNA scaffold tether is taut at its contour
length ("free until taut"). That minimisation runs **in the browser**
(``frontend/src/scene/cluster_gizmo.js`` — ``relaxSsdna`` /
``_projectSsdnaConstraints`` / ``_maxSsViolation``), so a headless script (or an
AI design pipeline) could *apply* a relax via ``POST /design/flexible-relax`` but
could not *compute* one.  This module closes that gap: it re-implements the exact
position-based-dynamics solver in Python so a headless relax matches what the
user sees in the app.

Three-Layer Law: this is **display/pose-layer only**.  It moves
``cluster_transforms`` (rigid poses); it NEVER touches the strand graph, helices,
crossovers, or flexible-segment *marks*.  The relaxed geometry is read from the
geometry kernel; nothing is written back to topology.

Faithful-port reference (cite when editing): the solver math mirrors
``cluster_gizmo.js`` lines ~808-887 (``_projectSsdnaConstraints`` / candidate
position / ``_maxSsViolation``) and ~905-957 (``relaxSsdna`` convergence loop);
the orchestration (group by cluster pair → move the smaller cluster →
translate-only for a lone tether → Gauss-Seidel sweep) mirrors
``frontend/src/scene/flex_relax.js`` ``relaxFlexible``.  The pure solver is also
pinned for JS↔Python parity in ``tests/test_flexible_relax.py`` against the
golden the vitest ``flexible_relax_solver.test.js`` produces from the same fixture.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, FlexibleAnchor

# Solver constants — IDENTICAL to cluster_gizmo.js (_SS_GAIN, _SS_ITERS,
# _SS_RELAX_OUTER, _SS_RELAX_EPS) and flex_relax.js (_SS_RELAX_TOL).
_SS_GAIN = 0.6
_SS_ITERS = 6
_SS_RELAX_OUTER = 80
_SS_RELAX_EPS = 1e-3      # nm — converged when max violation below this
_SS_RELAX_TOL = 0.05      # nm — overstretch beyond contour that counts as "needs relax"


# ── Pure PBD solver (port of relaxSsdna + _projectSsdnaConstraints) ─────────────

def relax_cluster_pose(
    pivot,
    translation,
    rotation,
    tethers,
    *,
    translate_only: bool = False,
):
    """Solve one moving cluster's relaxed pose.

    ``pivot`` / ``translation`` (nm) / ``rotation`` (quaternion ``[x,y,z,w]``)
    are the cluster's CURRENT transform.  ``tethers`` is a list of
    ``(moving_anchor_world_pos, fixed_anchor_world_pos, contour_nm)`` — the
    moving anchor is the tether end ON this cluster (it rides the pose), the
    fixed anchor is the other cluster's end (held still), both already at their
    current posed world positions.  ``translate_only`` slides without rotating
    (a lone tether has no rotation basis).

    Returns ``(new_translation, new_rotation, residual_nm, moved)`` — the absolute
    new transform (pivot unchanged), the largest remaining overstretch, and
    whether the cluster moved at all (False when nothing was overstretched).
    """
    pivot = np.asarray(pivot, dtype=float)
    dummy_pos = pivot + np.asarray(translation, dtype=float)
    start_pos = dummy_pos.copy()
    dummy_rot = Rotation.from_quat(rotation)
    start_rot = dummy_rot
    incr_rot = Rotation.identity()

    teth = [
        (np.asarray(m, dtype=float), np.asarray(f, dtype=float), float(c))
        for (m, f, c) in tethers
    ]

    def candidate(pM0):
        # world = incrQuat·(pM0 − startDummyPos) + dummyPos  (cluster_gizmo.js:825)
        return incr_rot.apply(pM0 - start_pos) + dummy_pos

    def max_violation():
        m = 0.0
        for pM0, pF, contour in teth:
            d = float(np.linalg.norm(candidate(pM0) - pF)) - contour
            if d > m:
                m = d
        return m

    if not teth or max_violation() <= _SS_RELAX_EPS:
        return list(translation), list(rotation), max_violation(), False

    for _ in range(_SS_RELAX_OUTER):
        if max_violation() <= _SS_RELAX_EPS:
            break
        # ── _projectSsdnaConstraints: _SS_ITERS internal iterations ────────────
        for _it in range(_SS_ITERS):
            # Rotation pass: accumulate torque about the pivot from violations.
            torque = np.zeros(3)
            sum_r2 = 0.0
            n_viol = 0
            for pM0, pF, contour in teth:
                pM = candidate(pM0)
                dist = float(np.linalg.norm(pM - pF))
                if dist <= contour or dist < 1e-9:
                    continue
                target = pF + (pM - pF) * (contour / dist)
                delta = target - pM
                r = pM - pivot
                torque = torque + np.cross(r, delta)
                sum_r2 += float(np.dot(r, r))
                n_viol += 1
            if n_viol == 0:
                break
            if not translate_only and sum_r2 > 1e-6:
                rv = torque * (_SS_GAIN / sum_r2)
                angle = float(np.linalg.norm(rv))
                if angle > 1e-9:
                    if angle > 0.25:
                        angle = 0.25  # clamp per-iter rotation for stability
                    axis = rv / float(np.linalg.norm(rv))
                    q = Rotation.from_rotvec(axis * angle)
                    dummy_pos = q.apply(dummy_pos - pivot) + pivot
                    dummy_rot = q * dummy_rot               # premultiply
                    incr_rot = dummy_rot * start_rot.inv()
            # Translation pass: residual after rotation.
            d_t = np.zeros(3)
            n_t = 0
            for pM0, pF, contour in teth:
                pM = candidate(pM0)
                dist = float(np.linalg.norm(pM - pF))
                if dist <= contour or dist < 1e-9:
                    continue
                target = pF + (pM - pF) * (contour / dist)
                d_t = d_t + (target - pM)
                n_t += 1
            if n_t > 0:
                dummy_pos = dummy_pos + d_t * (_SS_GAIN / n_t)

    residual = max_violation()
    new_translation = (dummy_pos - pivot).tolist()
    new_rotation = dummy_rot.as_quat().tolist()
    return new_translation, new_rotation, residual, True


# ── Orchestration (port of flex_relax.js relaxFlexible) ─────────────────────────

def _geom_index(design: Design) -> dict:
    """(helix_id, bp_index, direction-string) → posed backbone position (np)."""
    out = {}
    for n in _geometry_for_design(design):
        out[(n["helix_id"], n["bp_index"], n["direction"])] = np.asarray(
            n["backbone_position"], dtype=float
        )
    return out


def _anchor_world_pos(
    geom_index: dict, design: Design, anchor: FlexibleAnchor
) -> Optional[np.ndarray]:
    """Resolve a flexible anchor → its posed backbone world position.

    Mirrors ``flexAnchorKey`` (design_queries.js): the anchor names a strand +
    domain index + bp + direction; the domain supplies the helix.
    """
    strand = next((s for s in design.strands if s.id == anchor.strand_id), None)
    if strand is None or anchor.domain_index >= len(strand.domains):
        return None
    helix_id = strand.domains[anchor.domain_index].helix_id
    return geom_index.get((helix_id, anchor.bp_index, anchor.direction.value))


def _cluster_bead_count(geom_index: dict, design: Design, cluster_id: str) -> int:
    ct = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if ct is None:
        return 0
    hids = set(ct.helix_ids)
    return sum(1 for (h, _bp, _d) in geom_index if h in hids)


def compute_relax_transforms(
    design: Design,
    *,
    scope: str = "all",
    conn_id: Optional[str] = None,
):
    """Compute the relaxed pose for every overstretched flexible-connected pair.

    Returns ``(transforms, residual_remains)`` where ``transforms`` is a list of
    ``{"cluster_id", "pivot", "translation", "rotation"}`` (the absolute new
    poses, one per moved cluster — ready for ``POST /design/flexible-relax``), and
    ``residual_remains`` flags that some tether is still overstretched after the
    sweep budget.  Pure read of the design (does not mutate the input); the
    headless wrapper commits the result through the route.
    """
    conns_all = list(design.flexible_connections or [])
    if not conns_all:
        return [], False

    def pair_key(a: str, b: str):
        return tuple(sorted([a, b]))

    if scope == "one":
        conn = next((c for c in conns_all if c.id == conn_id), None)
        if conn is None:
            return [], False
        pairs = [pair_key(conn.cluster_a_id, conn.cluster_b_id)]
    else:
        pairs = list({pair_key(c.cluster_a_id, c.cluster_b_id) for c in conns_all})
        pairs.sort()

    work = design
    moved: dict[str, dict] = {}
    residual_remains = False
    max_sweeps = 8 if scope == "all" else 2

    for _sweep in range(max_sweeps):
        progressed = False
        for pk in pairs:
            conns = [
                c for c in (work.flexible_connections or [])
                if pair_key(c.cluster_a_id, c.cluster_b_id) == pk
            ]
            if not conns:
                continue
            ca, cb = pk
            geom = _geom_index(work)
            cnt_a = _cluster_bead_count(geom, work, ca)
            cnt_b = _cluster_bead_count(geom, work, cb)
            moving = ca if cnt_a <= cnt_b else cb
            translate_only = len(conns) == 1

            tethers = []
            for c in conns:
                on_a = c.cluster_a_id == moving
                m_anchor = c.anchor_a if on_a else c.anchor_b
                f_anchor = c.anchor_b if on_a else c.anchor_a
                pM0 = _anchor_world_pos(geom, work, m_anchor)
                pF = _anchor_world_pos(geom, work, f_anchor)
                if pM0 is None or pF is None:
                    continue
                tethers.append((pM0, pF, c.contour_length_nm))
            if not tethers:
                continue

            overstretched = any(
                float(np.linalg.norm(pM0 - pF)) > contour + _SS_RELAX_TOL
                for (pM0, pF, contour) in tethers
            )
            if not overstretched:
                continue

            ct = next(c for c in work.cluster_transforms if c.id == moving)
            new_tr, new_rot, residual, did_move = relax_cluster_pose(
                ct.pivot, ct.translation, ct.rotation, tethers,
                translate_only=translate_only,
            )
            if did_move:
                new_cts = [
                    c.model_copy(update={"translation": list(new_tr), "rotation": list(new_rot)})
                    if c.id == moving else c
                    for c in work.cluster_transforms
                ]
                work = work.copy_with(cluster_transforms=new_cts)
                moved[moving] = {
                    "cluster_id": moving,
                    "pivot": list(ct.pivot),
                    "translation": list(new_tr),
                    "rotation": list(new_rot),
                }
                progressed = True
            if residual > _SS_RELAX_TOL:
                residual_remains = True
        if not progressed:
            break

    return list(moved.values()), residual_remains
