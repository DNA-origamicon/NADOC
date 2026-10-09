"""Approximate a generated bend path with an ordinary editable sweep."""

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import Design
from backend.core.sweep import SweepRequest, build_sweep


def sweep_request(lattice, cells, length, path, start, *, source=None):
    from backend.core.lattice import make_bundle_design
    from backend.core.curved_rod_generator import bend_operations
    from backend.core.deformation import _precompute_arm_frames
    from backend.core.sweep_path import path_table, frame_key

    if source is not None:
        from backend.core.lattice_occupancy import occupied_lattice_cells

        occupied = occupied_lattice_cells(source, "XY")
        if occupied.intersection(map(tuple, cells)):
            # An even column shift preserves both lattice footprints while
            # keeping the native sweep editable alongside existing geometry.
            shift = 2 * (
                (max(c for _, c in occupied) - min(c for _, c in cells)) // 2 + 1
            )
            cells = [(r, c + shift) for r, c in cells]
    seed = make_bundle_design(cells, length, lattice_type=lattice)
    seed = seed.copy_with(
        deformations=bend_operations(path, start, [h.id for h in seed.helices])
    )
    spine, _, _ = _precompute_arm_frames(seed, seed.helices, 0, length - 1)
    # Three bend windows per editable point, plus the straight-tail boundaries.
    stop = min(length - 1, start + int(np.ceil(path["length_nm"] / RISE / 7)) * 7)
    indices = sorted({0, start, stop, length - 1, *range(start, stop, 21)})
    points = spine[indices] - spine[0]
    frames = frame_key([np.eye(3).ravel().tolist()] + [None] * (len(points) - 1))
    arc = path_table(tuple(map(tuple, points)), None, frames)[2][-1]
    # Preserve the routed lattice length after spline interpolation/rounding.
    points *= (length - 1) * RISE / arc
    return SweepRequest(
        cells=cells,
        points_nm=points.tolist(),
        orientations_deg=[(0, 0, 0)] + [None] * (len(points) - 1),
        ligate_adjacent=False,
    )


def routed_sweep(lattice, request):
    from backend.core.seamed_router import auto_scaffold_seamed

    design = build_sweep(Design(lattice_type=lattice), request)
    design, result = auto_scaffold_seamed(design)
    if not result.valid or len([s for s in design.scaffolds() if not s.is_reference]) != 1:
        raise ValueError("The generated sweep could not be routed as one scaffold.")
    return encode_sweep(design)


def encode_sweep(design):
    """Recompute safe marks after routing changes the forbidden crossover sites."""
    from backend.core.sweep_loop_skips import generated_sweep_loop_skips

    helices = list(design.helices)
    for op in design.deformations:
        if op.type != "sweep":
            continue
        marks, warnings = generated_sweep_loop_skips(design, op)
        if warnings:
            raise ValueError(
                "The generated sweep cannot fully encode its curvature: "
                + "; ".join(warnings)
            )
        helices = [
            h.model_copy(update={"loop_skips": marks.get(h.id, [])})
            if h.id in op.affected_helix_ids
            else h
            for h in helices
        ]
    return design.copy_with(helices=helices)
