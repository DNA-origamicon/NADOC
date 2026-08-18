"""Numeric parity checks for pure native-VR Full-view projections."""

import numpy as np
from types import SimpleNamespace

from backend.core.vr_scene_projection import (
    crossover_extra_base_full_projections,
    ds_linker_connector_projections,
    ss_linker_projection,
)


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


def _linker_nucleotides(*, linker_type: str) -> list[dict]:
    strand_ids = (
        ("__lnk__link__s", "__lnk__link__s")
        if linker_type == "ss"
        else ("__lnk__link__a", "__lnk__link__b")
    )
    return [
        {
            "strand_id": "oh-a",
            "overhang_id": "oh-a",
            "helix_id": "ha",
            "bp_index": 3,
            "is_five_prime": True,
            "backbone_position": [-0.2, 0.0, 0.0],
        },
        {
            "strand_id": "oh-b",
            "overhang_id": "oh-b",
            "helix_id": "hb",
            "bp_index": 8,
            "is_three_prime": True,
            "backbone_position": [4.2, 0.0, 0.0],
        },
        {
            "strand_id": strand_ids[0],
            "helix_id": "ha",
            "bp_index": 3,
            "backbone_position": [0.0, 0.0, 0.0],
            "base_normal": [0.0, 1.0, 0.0],
            "axis_tangent": [0.0, 0.0, 1.0],
        },
        {
            "strand_id": strand_ids[1],
            "helix_id": "hb",
            "bp_index": 8,
            "backbone_position": [4.0, 0.0, 0.0],
            "base_normal": [0.0, 1.0, 0.0],
            "axis_tangent": [0.0, 0.0, 1.0],
        },
    ]


def _linker(*, linker_type: str, length: int = 2, relaxed: bool = False):
    return SimpleNamespace(
        id="link",
        overhang_a_id="oh-a",
        overhang_a_attach="free_end",
        overhang_b_id="oh-b",
        overhang_b_attach="free_end",
        linker_type=linker_type,
        length_value=length,
        length_unit="bp",
        bridge_relaxed=relaxed,
        bridge_bin_index=0,
    )


def test_ss_linker_projection_uses_complement_anchors_and_full_slab_frame() -> None:
    projection = ss_linker_projection(
        _linker_nucleotides(linker_type="ss"), _linker(linker_type="ss")
    )

    assert projection is not None
    assert projection.strand_id == "__lnk__link__s"
    assert len(projection.bases) == 2
    assert len(projection.backbone_points) == 49
    np.testing.assert_allclose(projection.backbone_points[0], [0, 0, 0])
    np.testing.assert_allclose(projection.backbone_points[-1], [4, 0, 0])
    for base in projection.bases:
        axes = np.stack([base.slab_axis_x, base.slab_axis_y, base.slab_axis_z])
        np.testing.assert_allclose(np.linalg.norm(axes, axis=1), [0.30, 0.06, 0.70])
        np.testing.assert_allclose(base.slab_center - base.bead_center, [0, 0.45, 0])


def test_relaxed_ss_linker_projection_matches_desktop_chord_stretch() -> None:
    projection = ss_linker_projection(
        _linker_nucleotides(linker_type="ss"),
        _linker(linker_type="ss", length=4, relaxed=True),
    )

    assert projection is not None
    assert len(projection.bases) == 4
    np.testing.assert_allclose(projection.bases[0].bead_center, [0, 0, 0], atol=1e-8)
    np.testing.assert_allclose(projection.bases[-1].bead_center, [4, 0, 0], atol=1e-8)


def test_ds_linker_projection_connects_each_anchor_to_bridge_boundary() -> None:
    nucleotides = _linker_nucleotides(linker_type="ds")
    nucleotides.extend(
        [
            {
                "strand_id": "__lnk__link__a",
                "helix_id": "__lnk__link",
                "bp_index": 0,
                "backbone_position": [0.5, 0.5, 0.0],
            },
            {
                "strand_id": "__lnk__link__b",
                "helix_id": "__lnk__link",
                "bp_index": 1,
                "backbone_position": [3.5, 0.5, 0.0],
            },
        ]
    )

    connectors = ds_linker_connector_projections(nucleotides, _linker(linker_type="ds"))

    assert [connector.strand_id for connector in connectors] == [
        "__lnk__link__a",
        "__lnk__link__b",
    ]
    assert all(len(connector.points) == 49 for connector in connectors)
    np.testing.assert_allclose(connectors[0].points[0], [0, 0, 0])
    np.testing.assert_allclose(connectors[0].points[-1], [0.5, 0.5, 0])
    np.testing.assert_allclose(connectors[1].points[0], [4, 0, 0])
    np.testing.assert_allclose(connectors[1].points[-1], [3.5, 0.5, 0])
