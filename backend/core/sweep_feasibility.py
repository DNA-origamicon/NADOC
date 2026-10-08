"""Advisory bending demand against existing loop/skip density limits.

This assesses curvature of the actual footprint, not experimental stability or
availability of crossover-safe modification sites. Twist rotates that footprint;
this bending diagnostic does not certify torsional feasibility.
"""
import numpy as np
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.loop_skip_calculator import CELL_BP_DEFAULT, MAX_DELTA_PER_CELL
from backend.core.sweep_path import path_table, oriented_sample, frame_key


def bending_vectors(points, initial, base, normal, frames, distances):
    table = path_table(tuple(tuple(p) for p in points), None if initial is None else tuple(initial), frame_key(frames))
    u = np.interp(np.asarray(distances).ravel(), table[2], table[1])
    d1, d2 = table[0](u, 1), table[0](u, 2)
    speed2 = np.einsum('ij,ij->i', d1, d1)
    if np.any(speed2 < 1e-16):
        raise ValueError('Sweep has a stationary cusp; adjust the neighboring points')
    curvature = d2 / speed2[:, None] - d1 * (np.einsum('ij,ij->i', d1, d2) / speed2**2)[:, None]
    _, matrices, _ = oriented_sample(points, np.asarray(distances).ravel(), initial, base, normal, frames)
    return -np.einsum('nji,nj->ni', matrices, curvature).reshape(*np.shape(distances), 3)


def sweep_feasibility(points, initial, base, normal, frames, offsets, steps, path_distances):
    table = path_table(points, None if initial is None else tuple(initial), frame_key(frames))
    length = table[2][-1]
    start = 1 if initial is not None else 0
    # Match sweep_loop_skips' nucleotide bins, including half terminal bins.
    centers = np.arange(start, steps + 1) - (.5 if start else 0)
    lo = np.clip((centers - .5) * length / steps, 0, length)
    hi = np.clip((centers + .5) * length / steps, 0, length)
    nodes, weights = np.polynomial.legendre.leggauss(5)
    distances = ((lo + hi)[:, None] + (hi - lo)[:, None] * nodes) / 2
    vectors = np.einsum('nki,k->ni', bending_vectors(points, initial, base, normal, frames, distances), weights) * ((hi - lo) / (2 * RISE))[:, None]
    cells = np.arange(len(centers)) // CELL_BP_DEFAULT
    counts = np.bincount(cells)
    worst = np.zeros(len(counts))
    for offset in offsets:
        demand = vectors @ offset
        for signed in (demand, -demand):
            density = np.bincount(cells, weights=np.maximum(signed, 0)) * CELL_BP_DEFAULT / counts
            worst = np.maximum(worst, density)
    bad = np.flatnonzero(worst > MAX_DELTA_PER_CELL + 1e-8)
    ranges = [[float(lo[i * CELL_BP_DEFAULT]), float(hi[min((i+1)*CELL_BP_DEFAULT, len(hi))-1])] for i in bad]
    segments = [i for i in range(len(path_distances)-1)
                if any(path_distances[i] <= b and path_distances[i+1] >= a for a, b in ranges)]
    return dict(status='warning' if len(bad) else 'ok', warning_segments=segments,
                ranges_nm=ranges, max_delta_per_cell=float(worst.max(initial=0)),
                limit_per_cell=MAX_DELTA_PER_CELL, cell_bp=CELL_BP_DEFAULT,
                message='Bend exceeds the loop/skip density limit; creation is allowed.' if len(bad) else '',
                scope='Bending demand only; not a stability or torsional feasibility prediction.')
