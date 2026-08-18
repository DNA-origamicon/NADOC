"""Numeric parity checks for pure native-VR Full-view projections."""

import numpy as np

from backend.core.vr_scene_projection import crossover_extra_base_full_projections


def _nucleotide(x: float, direction: str) -> dict:
    return {
        "backbone_position": [x, 0.0, 0.0],
        "axis_tangent": [0.0, 0.0, 1.0],
        "direction": direction,
    }


def test_extra_base_projection_preserves_sequence_order_and_slab_frame() -> None:
    direct = crossover_extra_base_full_projections(
        _nucleotide(0.0, "FORWARD"),
        _nucleotide(2.0, "REVERSE"),
        "AT",
        sim_reversed=False,
        local_frame_reversed=False,
    )
    reversed_run = crossover_extra_base_full_projections(
        _nucleotide(0.0, "FORWARD"),
        _nucleotide(2.0, "REVERSE"),
        "AT",
        sim_reversed=True,
        local_frame_reversed=False,
    )

    assert [entry.sim_k for entry in direct] == [0, 1]
    assert [entry.base for entry in direct] == ["A", "T"]
    assert [entry.sim_k for entry in reversed_run] == [1, 0]
    assert [entry.base for entry in reversed_run] == ["T", "A"]
    for entry in [*direct, *reversed_run]:
        axes = np.stack([entry.slab_axis_x, entry.slab_axis_y, entry.slab_axis_z])
        np.testing.assert_allclose(np.linalg.norm(axes, axis=1), [0.30, 0.06, 0.70])
        np.testing.assert_allclose(
            axes @ axes.T - np.diag(np.diag(axes @ axes.T)), 0, atol=1e-12
        )
        # The connector owns one +X / ±Z slab corner, not an ambiguous edge midpoint.
        corner_delta = entry.slab_corner - entry.slab_center
        np.testing.assert_allclose(np.linalg.norm(corner_delta), np.hypot(0.15, 0.35))
