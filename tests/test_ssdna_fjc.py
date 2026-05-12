"""Tests for the ssDNA FJC lookup + relax_ss_linker integration.

Schema (bin-based redesign): each lookup entry exposes an R_ee histogram
with one representative shape per non-empty bin. Configurations are
identified by ``bin_index``; the loader walks to the nearest occupied
bin when a requested bin is empty.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core import ssdna_fjc


# ── Metadata + schema ────────────────────────────────────────────────────────

def test_metadata_present_and_consistent():
    md = ssdna_fjc.metadata()
    assert md["kuhn_length_nm"] == pytest.approx(1.5)
    assert md["contour_per_nt_nm"] == pytest.approx(0.59)
    assert md["saw_radius_nm"] == pytest.approx(0.6)
    assert md["hist_bins"] == 40
    lo, hi = ssdna_fjc.supported_range()
    assert lo == 1
    assert hi == 100
    assert md["bp_range"] == [1, 100]


def test_every_entry_in_active_range_has_bins():
    from scripts.generate_ssdna_fjc_lookup import MAX_NEW_ALGORITHM_BP
    for n_bp in range(2, MAX_NEW_ALGORITHM_BP + 1):
        assert ssdna_fjc.has_entry(n_bp)
        entry = ssdna_fjc.entry(n_bp)
        assert ssdna_fjc.num_bins(n_bp) == 40
        # At least one bin must be occupied (otherwise we'd have no shape).
        occupied = sum(1 for b in entry["bins"] if b["count"] > 0)
        assert occupied > 0, f"n_bp={n_bp}: no occupied bins"


def test_bin_positions_canonical_frame():
    """Resolved bin positions: first bead at origin, last bead on +x axis."""
    for n_bp in (3, 10, 20, 30, 35):
        # Walk through several bin indices; loader skips empties.
        for raw in range(0, 40, 5):
            idx = ssdna_fjc.resolve_bin_index(n_bp, raw)
            positions = ssdna_fjc.bin_positions(n_bp, idx)
            assert positions.shape == (n_bp, 3)
            assert np.allclose(positions[0], [0.0, 0.0, 0.0], atol=1e-6)
            r_ee = ssdna_fjc.bin_r_ee(n_bp, idx)
            assert positions[-1, 0] == pytest.approx(r_ee, abs=1e-5)
            assert abs(positions[-1, 1]) < 1e-5
            assert abs(positions[-1, 2]) < 1e-5


def test_bin_r_ee_lies_inside_bin():
    """The rep R_ee for each non-empty bin must fall inside that bin's edges."""
    for n_bp in (5, 15, 25, 35):
        entry = ssdna_fjc.entry(n_bp)
        edges = entry["r_ee_bin_edges_nm"]
        for k, b in enumerate(entry["bins"]):
            if b["count"] == 0:
                continue
            r_ee = b["rep_r_ee_nm"]
            assert edges[k] - 1e-6 <= r_ee <= edges[k + 1] + 1e-6, (
                f"n_bp={n_bp} bin {k}: rep R_ee {r_ee} outside [{edges[k]}, {edges[k+1]}]"
            )


def test_rg_subcounts_sum_to_bin_count():
    """For every non-empty R_ee bin, the per-Rg subhistogram counts sum to
    the bin's overall count (used by the frontend to recompute Rg under a
    R_ee crop)."""
    for n_bp in (5, 15, 25, 35):
        entry = ssdna_fjc.entry(n_bp)
        for k, b in enumerate(entry["bins"]):
            if b["count"] == 0:
                continue
            sub_sum = sum(b["rg_subcounts"])
            assert sub_sum == b["count"], (
                f"n_bp={n_bp} bin {k}: rg_subcounts sum {sub_sum} != count {b['count']}"
            )


def test_slab_constraint_holds_for_active_lengths():
    """For n_bp 2..35 every stored rep shape stays inside the slab [0, D]."""
    from scripts.generate_ssdna_fjc_lookup import MAX_NEW_ALGORITHM_BP
    eps = 1e-5
    for n_bp in range(2, MAX_NEW_ALGORITHM_BP + 1):
        entry = ssdna_fjc.entry(n_bp)
        D = entry["wall_separation_nm"]
        for k, b in enumerate(entry["bins"]):
            if b["count"] == 0:
                continue
            positions = np.asarray(b["rep_positions"], dtype=float)
            assert np.all(positions[:, 0] >= -eps), f"n_bp={n_bp} bin {k}: bead behind wall A"
            assert np.all(positions[:, 0] <= D + eps), f"n_bp={n_bp} bin {k}: bead past wall B"


def test_saw_radius_respected_for_active_lengths():
    """SAW: non-adjacent beads >= saw_radius apart, for every rep shape
    in the active n_bp range."""
    from scripts.generate_ssdna_fjc_lookup import MAX_NEW_ALGORITHM_BP
    saw_radius = ssdna_fjc.metadata()["saw_radius_nm"]
    for n_bp in range(3, MAX_NEW_ALGORITHM_BP + 1):
        entry = ssdna_fjc.entry(n_bp)
        for k, b in enumerate(entry["bins"]):
            if b["count"] == 0:
                continue
            positions = np.asarray(b["rep_positions"], dtype=float)
            diff = positions[:, None, :] - positions[None, :, :]
            d2 = np.sum(diff * diff, axis=2)
            n = len(positions)
            band = np.abs(np.subtract.outer(np.arange(n), np.arange(n))) >= 2
            if not band.any():
                continue
            min_d = float(np.sqrt(d2[band].min()))
            assert min_d >= saw_radius - 1e-5, (
                f"n_bp={n_bp} bin {k}: closest non-adjacent pair {min_d:.3f} < saw {saw_radius}"
            )


def test_wall_separation_matches_b_sqrt_N():
    for n_bp in (3, 5, 10, 25, 35):
        entry = ssdna_fjc.entry(n_bp)
        n_kuhn = entry["n_kuhn"]
        assert entry["wall_separation_nm"] == pytest.approx(1.5 * math.sqrt(n_kuhn), abs=1e-3)


def test_default_bin_index_points_to_occupied_bin():
    for n_bp in (5, 15, 25, 35):
        idx = ssdna_fjc.default_bin_index(n_bp)
        bins = ssdna_fjc.entry(n_bp)["bins"]
        assert 0 <= idx < len(bins)
        assert bins[idx]["count"] > 0


def test_resolve_bin_index_walks_to_nearest_occupied():
    """Empty bins resolve to the nearest occupied bin."""
    for n_bp in (10, 20, 30):
        entry = ssdna_fjc.entry(n_bp)
        for k, b in enumerate(entry["bins"]):
            resolved = ssdna_fjc.resolve_bin_index(n_bp, k)
            assert entry["bins"][resolved]["count"] > 0
            if b["count"] > 0:
                # Occupied bins resolve to themselves.
                assert resolved == k


# ── transform_to_chord ───────────────────────────────────────────────────────

def test_transform_to_chord_places_first_bead_on_anchor_a():
    idx = ssdna_fjc.default_bin_index(20)
    positions = ssdna_fjc.bin_positions(20, idx)
    anchor_a = np.array([3.0, -2.0, 5.0])
    anchor_b = np.array([3.0 + 10.0, -2.0, 5.0])
    moved = ssdna_fjc.transform_to_chord(positions, anchor_a, anchor_b)
    assert np.allclose(moved[0], anchor_a, atol=1e-6)
    chord_dir = (anchor_b - anchor_a) / np.linalg.norm(anchor_b - anchor_a)
    r_ee = ssdna_fjc.bin_r_ee(20, idx)
    assert np.allclose(moved[-1], anchor_a + chord_dir * r_ee, atol=1e-5)


def test_out_of_range_raises():
    with pytest.raises(ValueError):
        ssdna_fjc.entry(0)
    with pytest.raises(ValueError):
        ssdna_fjc.entry(101)


# ── relax_ss_linker integration ──────────────────────────────────────────────

def _seed_ss_relax_design(linker_bp: int):
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.lattice import generate_linker_topology
    from backend.core.models import (
        ClusterJoint,
        ClusterRigidTransform,
        Design,
        Domain,
        Helix,
        OverhangConnection,
        OverhangSpec,
        Strand,
        StrandType,
        Direction,
        Vec3,
    )

    oh_helix_a = Helix(
        id="oh_helix_a",
        axis_start=Vec3(x=2.5, y=0.0, z=0.0),
        axis_end=Vec3(x=2.5, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=8, grid_pos=(0, 0),
    )
    oh_helix_b = Helix(
        id="oh_helix_b",
        axis_start=Vec3(x=5.0, y=0.0, z=0.0),
        axis_end=Vec3(x=5.0, y=0.0, z=8 * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=8, grid_pos=(0, 3),
    )
    oh_strand_a = Strand(
        id="oh_strand_a",
        domains=[Domain(helix_id="oh_helix_a", start_bp=0, end_bp=7,
                        direction=Direction.FORWARD, overhang_id="oh_a_5p")],
        strand_type=StrandType.STAPLE,
    )
    oh_strand_b = Strand(
        id="oh_strand_b",
        domains=[Domain(helix_id="oh_helix_b", start_bp=0, end_bp=7,
                        direction=Direction.REVERSE, overhang_id="oh_b_5p")],
        strand_type=StrandType.STAPLE,
    )
    overhangs = [
        OverhangSpec(id="oh_a_5p", helix_id="oh_helix_a", strand_id="oh_strand_a", label="OHA"),
        OverhangSpec(id="oh_b_5p", helix_id="oh_helix_b", strand_id="oh_strand_b", label="OHB"),
    ]
    cluster_a = ClusterRigidTransform(id="cluster_a", name="A", helix_ids=["oh_helix_a"])
    cluster_b = ClusterRigidTransform(id="cluster_b", name="B", helix_ids=["oh_helix_b"])
    joint = ClusterJoint(
        id="joint_a", cluster_id="cluster_a", name="Hinge",
        local_axis_origin=[2.5, 0.0, 0.0],
        local_axis_direction=[0.0, 1.0, 0.0],
    )
    design = Design(
        helices=[oh_helix_a, oh_helix_b],
        strands=[oh_strand_a, oh_strand_b],
        overhangs=overhangs,
        cluster_transforms=[cluster_a, cluster_b],
        cluster_joints=[joint],
    )
    conn = OverhangConnection(
        overhang_a_id="oh_a_5p", overhang_a_attach="free_end",
        overhang_b_id="oh_b_5p", overhang_b_attach="root",
        linker_type="ss", length_value=linker_bp, length_unit="bp",
    )
    design = design.copy_with(overhang_connections=[conn])
    design = generate_linker_topology(design, conn)
    return design, conn


def test_relax_ss_linker_uses_explicit_bin_index():
    """The frontend modal passes an explicit ``bin_index``; the backend must
    honour it (after the loader resolves empties to the nearest occupied)."""
    from backend.core.linker_relax import relax_ss_linker

    n_bp = 15
    design, conn = _seed_ss_relax_design(linker_bp=n_bp)
    # Pick a bin that we know is occupied via the loader.
    requested = ssdna_fjc.resolve_bin_index(n_bp, 20)
    new_design, info = relax_ss_linker(design, conn, bin_index=requested)
    assert info["fjc_bin_index"] == requested
    relaxed = next(c for c in new_design.overhang_connections if c.id == conn.id)
    assert relaxed.bridge_relaxed is True
    assert relaxed.bridge_bin_index == requested
    assert info["target_chord_nm"] == pytest.approx(
        ssdna_fjc.bin_r_ee(n_bp, requested), abs=1e-6,
    )


def test_relax_ss_linker_persists_r_ee_limits():
    """When the modal passes r_ee_min_nm / r_ee_max_nm, they land on the conn."""
    from backend.core.linker_relax import relax_ss_linker

    n_bp = 20
    design, conn = _seed_ss_relax_design(linker_bp=n_bp)
    new_design, info = relax_ss_linker(
        design, conn,
        bin_index=ssdna_fjc.default_bin_index(n_bp),
        r_ee_min_nm=1.5, r_ee_max_nm=4.0,
    )
    relaxed = next(c for c in new_design.overhang_connections if c.id == conn.id)
    assert relaxed.bridge_r_ee_min_nm == pytest.approx(1.5)
    assert relaxed.bridge_r_ee_max_nm == pytest.approx(4.0)
    assert info["fjc_r_ee_min_nm"] == pytest.approx(1.5)
    assert info["fjc_r_ee_max_nm"] == pytest.approx(4.0)


def test_relax_ss_linker_default_bin_when_unrelaxed():
    """Without an explicit bin_index, an unrelaxed linker lands on the
    ensemble-mean bin."""
    from backend.core.linker_relax import relax_ss_linker

    n_bp = 20
    design, conn = _seed_ss_relax_design(linker_bp=n_bp)
    _, info = relax_ss_linker(design, conn)
    assert info["fjc_bin_index"] == ssdna_fjc.default_bin_index(n_bp)


def test_relax_ss_linker_rejects_ds_linker():
    from backend.core.linker_relax import relax_ss_linker

    design, conn = _seed_ss_relax_design(linker_bp=15)
    ds_conn = conn.model_copy(update={"linker_type": "ds"})
    with pytest.raises(ValueError, match="ss linker"):
        relax_ss_linker(design, ds_conn)


def test_fjc_positions_in_design_frame_returns_n_bp_points():
    from backend.core.linker_relax import fjc_positions_in_design_frame

    design, conn = _seed_ss_relax_design(linker_bp=25)
    positions = fjc_positions_in_design_frame(design, conn)
    assert len(positions) == 25
    assert all(len(p) == 3 for p in positions)
