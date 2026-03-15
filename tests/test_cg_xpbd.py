"""
Tests for coarse-grained helix-level physics (backend/physics/cg_xpbd.py).

Validation requirements:
  - CGSimState builds correctly from a design (particle count, bond structure).
  - Backbone rest lengths encode loop/skip modifications.
  - Crossover bonds are detected from strand topology.
  - cg_xpbd_step reduces constraint energy on a perturbed structure.
  - cg_positions_to_updates returns correctly shaped FORWARD+REVERSE updates.
  - A design with loop/skip mods shows non-zero crossover bonds and energy.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.constants import BDNA_RISE_PER_BP, HELIX_RADIUS, HONEYCOMB_HELIX_SPACING
from backend.core.models import (
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    LoopSkip,
    Strand,
    Vec3,
)
from backend.physics.cg_xpbd import (
    CGSimState,
    build_cg_simulation,
    cg_positions_to_updates,
    cg_sim_energy,
    cg_xpbd_step,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _single_helix_design(length_bp: int = 21) -> Design:
    """One helix with two strands (no crossovers)."""
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    return Design(
        id="single",
        helices=[helix],
        strands=[
            Strand(id="scaf", is_scaffold=True, domains=[
                Domain(helix_id="h0", start_bp=0, end_bp=length_bp - 1,
                       direction=Direction.FORWARD),
            ]),
            Strand(id="stpl", domains=[
                Domain(helix_id="h0", start_bp=length_bp - 1, end_bp=0,
                       direction=Direction.REVERSE),
            ]),
        ],
        lattice_type=LatticeType.FREE,
        metadata=DesignMetadata(name="single helix"),
    )


def _two_helix_design(length_bp: int = 42) -> Design:
    """Two helices with one crossover between them (scaffold crosses at midpoint)."""
    mid = length_bp // 2
    h0 = Helix(id="h0", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
               axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=length_bp)
    h1 = Helix(id="h1", axis_start=Vec3(x=HONEYCOMB_HELIX_SPACING, y=0.0, z=0.0),
               axis_end=Vec3(x=HONEYCOMB_HELIX_SPACING, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=length_bp)
    # Scaffold: h0 0..mid, then crosses to h1 mid..end
    scaffold = Strand(id="scaf", is_scaffold=True, domains=[
        Domain(helix_id="h0", start_bp=0,   end_bp=mid, direction=Direction.FORWARD),
        Domain(helix_id="h1", start_bp=mid, end_bp=length_bp - 1, direction=Direction.FORWARD),
    ])
    # Simple staples (no crossovers)
    stpl0 = Strand(id="stpl0", domains=[
        Domain(helix_id="h0", start_bp=length_bp - 1, end_bp=0, direction=Direction.REVERSE),
    ])
    stpl1 = Strand(id="stpl1", domains=[
        Domain(helix_id="h1", start_bp=length_bp - 1, end_bp=0, direction=Direction.REVERSE),
    ])
    return Design(id="two", helices=[h0, h1], strands=[scaffold, stpl0, stpl1],
                  lattice_type=LatticeType.FREE)


def _two_helix_with_loop_skip(length_bp: int = 42) -> Design:
    """Two helices with crossover + loop on h0 / skip on h1 at midpoint."""
    design = _two_helix_design(length_bp)
    mid = length_bp // 2
    new_helices = []
    for h in design.helices:
        if h.id == "h0":
            new_helices.append(h.model_copy(update={"loop_skips": [LoopSkip(bp_index=mid, delta=1)]}))
        elif h.id == "h1":
            new_helices.append(h.model_copy(update={"loop_skips": [LoopSkip(bp_index=mid, delta=-1)]}))
        else:
            new_helices.append(h)
    return design.model_copy(update={"helices": new_helices})


# ── Build tests ────────────────────────────────────────────────────────────────


class TestBuildCGSimulation:
    def test_particle_count_single_helix(self):
        design = _single_helix_design(21)
        sim = build_cg_simulation(design)
        # One CP per bp per helix: 21 CPs
        assert len(sim.particles) == 21
        assert sim.positions.shape == (21, 3)

    def test_particle_count_two_helices(self):
        design = _two_helix_design(42)
        sim = build_cg_simulation(design)
        # 42 CPs per helix × 2 helices = 84 CPs
        assert len(sim.particles) == 84

    def test_backbone_bond_count_single_helix(self):
        design = _single_helix_design(21)
        sim = build_cg_simulation(design)
        # 20 backbone bonds for 21 CPs
        assert len(sim.backbone_ij) == 20

    def test_backbone_rest_lengths_default(self):
        """Without loop/skip, all backbone bonds = BDNA_RISE_PER_BP."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        expected = BDNA_RISE_PER_BP
        assert np.allclose(sim.backbone_rest, expected, atol=1e-9), (
            f"Expected all rests = {expected:.4f}, got min={sim.backbone_rest.min():.4f} "
            f"max={sim.backbone_rest.max():.4f}"
        )

    def test_loop_increases_rest_length(self):
        """A loop (+1) at bp k must increase the rest length of bond k→k+1 by BDNA_RISE_PER_BP."""
        design = _single_helix_design(10)
        mid = 5
        new_h = design.helices[0].model_copy(
            update={"loop_skips": [LoopSkip(bp_index=mid, delta=1)]}
        )
        design = design.model_copy(update={"helices": [new_h]})
        sim = build_cg_simulation(design)
        # Find the bond connecting mid → mid+1.
        for bond_idx in range(len(sim.backbone_ij)):
            ia, ib = sim.backbone_ij[bond_idx]
            hi_a, k_a = sim.particles[ia]
            hi_b, k_b = sim.particles[ib]
            if hi_a == "h0" and min(k_a, k_b) == mid:
                rest = sim.backbone_rest[bond_idx]
                assert abs(rest - 2 * BDNA_RISE_PER_BP) < 1e-9, (
                    f"Loop bond rest should be 2×BDNA_RISE_PER_BP={2*BDNA_RISE_PER_BP:.4f}, "
                    f"got {rest:.4f}"
                )
                return
        pytest.fail("Loop-modified bond k→k+1 not found in backbone bonds")

    def test_skip_reduces_rest_length(self):
        """A skip (-1) at bp k must reduce the rest length of bond k→k+1 to 0."""
        design = _single_helix_design(10)
        mid = 5
        new_h = design.helices[0].model_copy(
            update={"loop_skips": [LoopSkip(bp_index=mid, delta=-1)]}
        )
        design = design.model_copy(update={"helices": [new_h]})
        sim = build_cg_simulation(design)
        for bond_idx in range(len(sim.backbone_ij)):
            ia, ib = sim.backbone_ij[bond_idx]
            hi_a, k_a = sim.particles[ia]
            hi_b, k_b = sim.particles[ib]
            if hi_a == "h0" and min(k_a, k_b) == mid:
                rest = sim.backbone_rest[bond_idx]
                assert rest == 0.0, f"Skip bond rest should be 0, got {rest:.4f}"
                return
        pytest.fail("Skip-modified bond k→k+1 not found in backbone bonds")

    def test_crossover_bonds_detected(self):
        """A two-helix design with scaffold crossing at mid should have >= 1 crossover bond."""
        design = _two_helix_design(42)
        sim = build_cg_simulation(design)
        assert len(sim.crossover_ij) >= 1, (
            f"Expected crossover bonds, got {len(sim.crossover_ij)}"
        )

    def test_crossover_rest_near_helix_spacing(self):
        """Crossover between adjacent honeycomb helices: rest ≈ HONEYCOMB_HELIX_SPACING."""
        design = _two_helix_design(42)
        sim = build_cg_simulation(design)
        assert len(sim.crossover_ij) >= 1
        # All crossover rests should be close to helix spacing (2.25 nm for this geometry).
        for rest in sim.crossover_rest:
            assert abs(rest - HONEYCOMB_HELIX_SPACING) < 0.1, (
                f"Crossover rest {rest:.4f} nm far from helix spacing {HONEYCOMB_HELIX_SPACING}"
            )

    def test_bending_bonds_exist(self):
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        # 10 CPs → 8 bending bonds (2nd-neighbour: k→k+2 for k in 0..7)
        assert len(sim.bending_ij) == 8

    def test_normals_are_unit_vectors(self):
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        fwd_lengths = np.linalg.norm(sim.fwd_normals, axis=1)
        rev_lengths = np.linalg.norm(sim.rev_normals, axis=1)
        assert np.allclose(fwd_lengths, 1.0, atol=1e-10)
        assert np.allclose(rev_lengths, 1.0, atol=1e-10)

    def test_normals_perpendicular_to_axis(self):
        """For a Z-axis helix, all normals should lie in the XY plane."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        # Axis direction is [0, 0, 1]; normals should have ~0 z-component.
        z_fwd = sim.fwd_normals[:, 2]
        z_rev = sim.rev_normals[:, 2]
        assert np.allclose(z_fwd, 0.0, atol=1e-10)
        assert np.allclose(z_rev, 0.0, atol=1e-10)

    def test_positions_on_axis(self):
        """CPs should lie on the straight helix axis (no helix-radius offset)."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        # Axis is Z; all CPs should have x=0, y=0.
        assert np.allclose(sim.positions[:, 0], 0.0, atol=1e-10)
        assert np.allclose(sim.positions[:, 1], 0.0, atol=1e-10)

    def test_empty_design(self):
        design = Design(id="empty", lattice_type=LatticeType.FREE)
        sim = build_cg_simulation(design)
        assert len(sim.particles) == 0

    def test_loop_skip_design_has_extra_crossover_strain(self):
        """Loop/skip design: backbone bond at loop site has rest != BDNA_RISE_PER_BP."""
        design = _two_helix_with_loop_skip(42)
        sim = build_cg_simulation(design)
        # Find any backbone bond with non-default rest length.
        non_default = np.where(
            ~np.isclose(sim.backbone_rest, BDNA_RISE_PER_BP, atol=1e-9)
        )[0]
        assert len(non_default) > 0, "Expected at least one non-default backbone rest length"


# ── Step and energy tests ──────────────────────────────────────────────────────


class TestCGXpbdStep:
    def test_step_increments_counter(self):
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        assert sim.step == 0
        cg_xpbd_step(sim)
        assert sim.step == 1

    def test_positions_change_on_perturbed(self):
        design = _single_helix_design(21)
        sim = build_cg_simulation(design)
        sim.positions += np.random.default_rng(42).uniform(-0.3, 0.3, sim.positions.shape)
        original = sim.positions.copy()
        cg_xpbd_step(sim, n_substeps=5)
        assert not np.allclose(sim.positions, original)

    def test_energy_decreases_on_perturbed(self):
        design = _single_helix_design(21)
        sim = build_cg_simulation(design)
        sim.positions += np.random.default_rng(7).uniform(-0.5, 0.5, sim.positions.shape)
        e_init = cg_sim_energy(sim)
        for _ in range(20):
            cg_xpbd_step(sim, n_substeps=10)
        e_final = cg_sim_energy(sim)
        assert e_final < e_init, (
            f"Energy should decrease: initial={e_init:.4f}, final={e_final:.4f}"
        )

    def test_unperturbed_stays_at_rest(self):
        """Straight helix with default rest lengths (no loop/skip): near-zero energy after steps."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        e_init = cg_sim_energy(sim)
        cg_xpbd_step(sim, n_substeps=50)
        e_final = cg_sim_energy(sim)
        # Should stay near zero (the straight geometry IS the rest geometry).
        assert e_final < 1e-20, f"Energy should be ~0, got {e_final:.4e}"

    def test_loop_skip_design_has_nonzero_initial_energy(self):
        """
        With loop/skip: backbone bonds at modification sites are strained in
        the straight initial geometry → positive energy immediately on build.
        """
        design = _two_helix_with_loop_skip(42)
        sim = build_cg_simulation(design)
        e = cg_sim_energy(sim)
        assert e > 0.0, "Loop/skip design should have non-zero initial energy"

    def test_crossover_weight_affects_step(self):
        """Higher crossover_weight should produce larger corrections per step."""
        design = _two_helix_design(42)
        sim_low  = build_cg_simulation(design)
        sim_high = build_cg_simulation(design)
        # Perturb both identically.
        rng = np.random.default_rng(0)
        noise = rng.uniform(-0.5, 0.5, sim_low.positions.shape)
        sim_low.positions  += noise.copy()
        sim_high.positions += noise.copy()
        sim_low.crossover_weight  = 1.0
        sim_high.crossover_weight = 50.0
        orig_low  = sim_low.positions.copy()
        orig_high = sim_high.positions.copy()
        cg_xpbd_step(sim_low,  n_substeps=1)
        cg_xpbd_step(sim_high, n_substeps=1)
        # Measure delta positions at crossover CPs.
        if len(sim_high.crossover_ij) > 0:
            idxs = np.unique(sim_high.crossover_ij)
            delta_low  = np.linalg.norm(sim_low.positions[idxs]  - orig_low[idxs],  axis=1).mean()
            delta_high = np.linalg.norm(sim_high.positions[idxs] - orig_high[idxs], axis=1).mean()
            assert delta_high > delta_low, (
                f"Higher crossover_weight should produce larger corrections: "
                f"low={delta_low:.4f}, high={delta_high:.4f}"
            )


# ── Output expansion tests ─────────────────────────────────────────────────────


class TestCGPositionsToUpdates:
    def test_output_count(self):
        """Each CP produces one FORWARD and one REVERSE update."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        updates = cg_positions_to_updates(sim)
        assert len(updates) == 2 * len(sim.particles)

    def test_output_has_required_fields(self):
        design = _single_helix_design(5)
        sim = build_cg_simulation(design)
        for u in cg_positions_to_updates(sim):
            assert "helix_id"          in u
            assert "bp_index"          in u
            assert "direction"         in u
            assert "backbone_position" in u
            assert len(u["backbone_position"]) == 3

    def test_forward_reverse_directions(self):
        design = _single_helix_design(5)
        sim = build_cg_simulation(design)
        updates = cg_positions_to_updates(sim)
        directions = {u["direction"] for u in updates}
        assert "FORWARD" in directions
        assert "REVERSE" in directions

    def test_bead_offset_from_axis(self):
        """Backbone beads should be HELIX_RADIUS from their CP axis position."""
        design = _single_helix_design(10)
        sim = build_cg_simulation(design)
        updates = cg_positions_to_updates(sim)
        for u in updates:
            key = (u["helix_id"], u["bp_index"])
            cp_idx = sim.index_map[key]
            cp_pos = sim.positions[cp_idx]
            bead_pos = np.array(u["backbone_position"])
            dist = np.linalg.norm(bead_pos - cp_pos)
            assert abs(dist - HELIX_RADIUS) < 1e-9, (
                f"Bead at {u['direction']} bp={u['bp_index']} is {dist:.4f} nm from axis; "
                f"expected {HELIX_RADIUS}"
            )

    def test_fwd_rev_beads_at_different_positions(self):
        """FORWARD and REVERSE beads at the same bp should be at different positions."""
        design = _single_helix_design(5)
        sim = build_cg_simulation(design)
        updates = cg_positions_to_updates(sim)
        by_bp: dict[tuple, dict] = {}
        for u in updates:
            key = (u["helix_id"], u["bp_index"], u["direction"])
            by_bp[key] = u["backbone_position"]
        for h_id, bp_idx in sim.particles:
            fwd = np.array(by_bp.get((h_id, bp_idx, "FORWARD"), [0, 0, 0]))
            rev = np.array(by_bp.get((h_id, bp_idx, "REVERSE"), [0, 0, 0]))
            dist = np.linalg.norm(fwd - rev)
            assert dist > 0.1, f"FWD and REV beads at bp={bp_idx} are too close ({dist:.4f} nm)"
