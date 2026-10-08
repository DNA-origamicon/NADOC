"""Realize a sweep's local bending strain as safe, signed loop/skip marks.

Uses the stored spline and rotation-minimizing frame, not rendered nucleotides.
The length difference of an offset fiber is -curvature·offset ds. Integrating
that signed difference locally preserves both lobes of an S bend. There is no
extra twist term: sweep frames parallel-transport the cross-section without roll.
"""
from bisect import bisect_left
import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import LoopSkip
from backend.core.sweep_path import path_table, rotation_between
from backend.core.loop_skip_calculator import (
    CELL_BP_DEFAULT, _active_intervals_for_helices,
    _bundle_centroid_and_tangent, _helix_cross_section_offset,
    forbidden_loop_skip_bps, validate_loop_skip_limits,
)


def sweep_strain_vectors(op, tangent):
    """Per-bp signed length change / RISE, per nm of canonical offset.

    Each nucleotide owns a path interval. Continuation owns the source-to-first
    interval too, in either direction. New bundles split terminal intervals in
    half. Clipping those bins to the path avoids a fictitious extra terminal bp.
    """
    p = op.params
    bps = np.arange(op.plane_a_bp, op.plane_b_bp + 1)
    step = bps - op.plane_a_bp if p.direction == 1 else op.plane_b_bp - bps
    centers = step + p.start_step - (.5 if p.start_step else 0)
    pitch = p.path_length_nm / p.steps
    lo = np.clip((centers - .5) * pitch, 0, p.path_length_nm)
    hi = np.clip((centers + .5) * pitch, 0, p.path_length_nm)
    nodes, weights = np.polynomial.legendre.leggauss(5)
    distances = ((lo + hi)[:, None] + (hi - lo)[:, None] * nodes) / 2
    points = tuple(tuple(v for v in point) for point in p.points_nm)
    initial = tuple(p.initial_tangent) if p.initial_tangent is not None else None
    spline, parameters, arc, tangents, rotations = path_table(points, initial)
    u = np.interp(distances.ravel(), arc, parameters)
    d1, d2 = spline(u, 1), spline(u, 2)
    speed2 = np.einsum('ij,ij->i', d1, d1)
    curvature = d2 / speed2[:, None] - d1 * (np.einsum('ij,ij->i', d1, d2) / speed2**2)[:, None]
    base = np.asarray(p.initial_rotation).reshape(3, 3)
    align = rotation_between(base @ tangent * p.direction, tangents[0])
    frames = rotations(np.clip(distances.ravel(), 0, arc[-1])).as_matrix() @ align @ base
    local = np.einsum('nji,nj->ni', frames, curvature).reshape(len(bps), len(nodes), 3)
    vectors = -np.einsum('nki,k->ni', local, weights) * ((hi - lo) / (2 * RISE))[:, None]
    return bps, vectors


def _place_runs(bps, demand, forbidden, reserved, label):
    """Quantize separately within each signed, contiguous duplex run."""
    result, start = [], 0
    signs = np.sign(np.where(np.abs(demand) < 1e-10, 0, demand)).astype(int)
    while start < len(bps):
        end = start + 1
        while end < len(bps) and bps[end] == bps[end-1] + 1 and signs[end] == signs[start]:
            end += 1
        weights = np.abs(demand[start:end])
        total = float(weights.sum())
        count = round(total)
        if count:
            run = bps[start:end]
            free = [int(bp) for bp in run if bp not in forbidden and bp not in reserved]
            if count > len(free):
                raise ValueError(f'{label}: needs {count} loop/skip sites but only {len(free)} safe sites remain in this bend region')
            cumulative = np.cumsum(weights)
            ideals = np.interp((np.arange(count) + .5) * total / count, cumulative, run)
            for ideal in ideals:
                at = bisect_left(free, ideal)
                choices = [i for i in (at - 1, at) if 0 <= i < len(free)]
                index = min(choices, key=lambda i: (abs(free[i] - ideal), free[i]))
                bp = free.pop(index); reserved.add(bp)
                result.append(LoopSkip(bp_index=bp, delta=int(signs[start])))
        start = end
    return sorted(result, key=lambda mark: mark.bp_index)


def sweep_loop_skips(design, *, existing=None, ignored_helix_ids=()):
    """Realize all sweeps, preserving other deformation/SQ marks on collision.

    Fails before mutation if a sweep exceeds the existing per-cell density limit
    or has insufficient safe sites. This does not restrict Sweep authoring.
    """
    ignored = set(ignored_helix_ids)
    active = design.copy_with(strands=design.active_strands())
    forbidden = forbidden_loop_skip_bps(active)
    reserved = {hid: {mark.bp_index for mark in marks} for hid, marks in (existing or {}).items()}
    result = {}
    for op in design.deformations:
        if op.type != 'sweep':
            continue
        helices = [h for h in design.helices if h.id in op.affected_helix_ids]
        if not helices:
            continue
        centroid, tangent = _bundle_centroid_and_tangent(helices)
        bps, vectors = sweep_strain_vectors(op, tangent)
        for helix in helices:
            if helix.id in ignored:
                continue
            intervals = _active_intervals_for_helices(active, {helix.id})
            mask = np.zeros(len(bps), dtype=bool)
            for lo, hi in intervals:
                mask |= (bps >= lo) & (bps < hi)
            mask &= (bps >= helix.bp_start) & (bps < helix.bp_start + helix.length_bp)
            local_bps = bps[mask]
            demand = (vectors @ _helix_cross_section_offset(helix, centroid, tangent))[mask]
            label = f'Sweep {op.id}, helix {helix.id}'
            cells = (local_bps - op.plane_a_bp) // CELL_BP_DEFAULT
            counts = np.bincount(cells)
            deletions = np.bincount(cells, weights=np.maximum(-demand, 0))
            insertions = np.bincount(cells, weights=np.maximum(demand, 0))
            for cell in np.flatnonzero(counts):
                scale = CELL_BP_DEFAULT / counts[cell]
                validate_loop_skip_limits(float(deletions[cell]) * scale,
                                          float(insertions[cell]) * scale, label=label)
            marks = _place_runs(local_bps, demand, forbidden.get(helix.id, set()),
                                reserved.setdefault(helix.id, set()), label)
            if marks:
                result.setdefault(helix.id, []).extend(marks)
    return result
