"""Realize a sweep's local bending strain as safe, signed loop/skip marks.

Uses the stored spline and rotation-minimizing frame, not rendered nucleotides.
The length difference of an offset fiber is -curvature·offset ds. Integrating
that signed difference locally preserves both lobes of an S bend. Authored twist rotates the footprint used for bending demand. Torsional
compensation is not included in this bending calculation.
"""
from bisect import bisect_left
import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import LoopSkip
from backend.core.loop_skip_calculator import (
    CELL_BP_DEFAULT, MAX_DELTA_PER_CELL, _active_intervals_for_helices,
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
    from backend.core.sweep_feasibility import bending_vectors
    local = -bending_vectors(p.points_nm, p.initial_tangent,
        np.asarray(p.initial_rotation).reshape(3, 3), np.asarray(tangent) * p.direction,
        p.point_frames, distances)
    vectors = -np.einsum('nki,k->ni', local, weights) * ((hi - lo) / (2 * RISE))[:, None]
    return bps, vectors


def _place_runs(bps, demand, forbidden, reserved, label, *, safe=False, cell_origin=0, warnings=None, warning_sites=None):
    """Quantize separately within each signed, contiguous duplex run."""
    result, start = [], 0
    cell_counts = {}
    for bp in reserved:
        cell = (bp-cell_origin)//CELL_BP_DEFAULT
        cell_counts[cell] = cell_counts.get(cell, 0)+1
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
            requested = count
            if safe:
                count = min(count, len(free))
            if count > len(free):
                raise ValueError(f'{label}: needs {count} loop/skip sites but only {len(free)} safe sites remain in this bend region')
            cumulative = np.cumsum(weights)
            ideals = np.interp((np.arange(count) + .5) * total / count, cumulative, run) if count else []
            placed = 0
            for ideal in ideals:
                if safe:
                    free = [bp for bp in free if cell_counts.get((bp-cell_origin)//CELL_BP_DEFAULT,0) < MAX_DELTA_PER_CELL]
                    if not free:
                        break
                at = bisect_left(free, ideal)
                choices = [i for i in (at - 1, at) if 0 <= i < len(free)]
                index = min(choices, key=lambda i: (abs(free[i] - ideal), free[i]))
                bp = free.pop(index); reserved.add(bp)
                result.append(LoopSkip(bp_index=bp, delta=int(signs[start])))
                cell = (bp-cell_origin)//CELL_BP_DEFAULT
                cell_counts[cell] = cell_counts.get(cell, 0)+1
                placed += 1
            if safe and placed < requested and warnings is not None:
                if warning_sites is not None:
                    warning_sites.append(int(run[len(run)//2]))
                warnings.append(f"{label}: applied {placed} of {requested} requested corrections in bp {int(run[0])}–{int(run[-1])}; safe-site or density limit reached.")
        start = end
    return sorted(result, key=lambda mark: mark.bp_index)


def sweep_loop_skips(design, *, existing=None, ignored_helix_ids=(), safe=False, warnings=None, include_generated=False, warning_sites=None):
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
        if include_generated and op.params.auto_loop_skips:
            generated, _ = generated_sweep_loop_skips(design, op, existing=existing, ignored_helix_ids=ignored)
            for hid, marks in generated.items():
                result.setdefault(hid, []).extend(marks)
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
            for cell in ([] if safe else np.flatnonzero(counts)):
                scale = CELL_BP_DEFAULT / counts[cell]
                validate_loop_skip_limits(float(deletions[cell]) * scale,
                                          float(insertions[cell]) * scale, label=label)
            marks = _place_runs(local_bps, demand, forbidden.get(helix.id, set()),
                                reserved.setdefault(helix.id, set()), label, safe=safe,
                                cell_origin=op.plane_a_bp, warnings=warnings, warning_sites=warning_sites)
            if marks:
                result.setdefault(helix.id, []).extend(marks)
    return result


def generated_sweep_loop_skips(design, op, *, existing=None, ignored_helix_ids=(), warning_sites=None):
    """Deterministic, bounded realization scoped to one new sweep's helices.

    Square-lattice compensation is staggered within this footprint, independent
    of older geometry. Recompute from clean marks, so repeated calls cannot stack.
    Strand topology is retained to respect source junctions and crossover margins.
    """
    from backend.core.loop_skip_calculator import sq_lattice_periodic_skips, relocate_marks_off_forbidden
    ids = set(op.affected_helix_ids) - set(ignored_helix_ids)
    scoped = design.copy_with(helices=[h.model_copy(update={'loop_skips': []}) for h in design.helices if h.id in ids],
                              deformations=[op], strands=design.active_strands())
    periodic = relocate_marks_off_forbidden(sq_lattice_periodic_skips(scoped), scoped)
    occupied = {hid: list(marks) for hid, marks in (existing or {}).items()}
    # Existing deformation marks win at a collision.
    periodic = {hid: [m for m in marks if m.bp_index not in {x.bp_index for x in occupied.get(hid, [])}]
                for hid, marks in periodic.items()}
    for hid, marks in periodic.items():
        occupied.setdefault(hid, []).extend(marks)
    warnings = []
    bending = sweep_loop_skips(scoped, existing=occupied, safe=True, warnings=warnings, warning_sites=warning_sites)
    result = {hid: list(marks) for hid, marks in periodic.items() if marks}
    for hid, marks in bending.items():
        result.setdefault(hid, []).extend(marks)
    return {hid: sorted(marks, key=lambda m: m.bp_index) for hid, marks in result.items()}, warnings
