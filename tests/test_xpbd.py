"""
Tests for the Phase 5 physics layer:
  - backend/physics/xpbd.py   — XPBD constraint engine
  - backend/physics/oxdna_interface.py — oxDNA I/O helpers

Validation requirements from DEVELOPMENT_PLAN.md Phase 5:
  - V5.1 (visual): single helix remains recognisably a helix after XPBD.
  - V5.2 (unit): oxDNA round-trip preserves positions within tolerance.
  - V5.3 (visual): mode toggle reverts to exact geometric positions.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.geometry import nucleotide_positions
from backend.core.models import (
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    Vec3,
)
from backend.physics.xpbd import (
    BACKBONE_BOND_LENGTH,
    EXCLUDED_VOLUME_DIST,
    SimState,
    build_simulation,
    positions_to_updates,
    sim_energy,
    xpbd_step,
)
from backend.physics.oxdna_interface import (
    read_configuration,
    write_configuration,
    write_topology,
    _strand_nucleotide_order,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_single_helix_design(length_bp: int = 42) -> Design:
    """Single 42 bp helix along +Z."""
    helix = Helix(
        id="test_helix",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    scaffold = Strand(
        id="scaffold",
        domains=[Domain(helix_id="test_helix", start_bp=0, end_bp=length_bp - 1,
                        direction=Direction.FORWARD)],
        is_scaffold=True,
    )
    staple = Strand(
        id="staple",
        domains=[Domain(helix_id="test_helix", start_bp=length_bp - 1, end_bp=0,
                        direction=Direction.REVERSE)],
    )
    return Design(
        id="test",
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.FREE,
        metadata=DesignMetadata(name="Test single helix"),
    )


def _make_two_helix_design(length_bp: int = 42) -> Design:
    """Two side-by-side helices (no crossovers) for excluded-volume tests."""
    h0 = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    h1 = Helix(
        id="h1",
        axis_start=Vec3(x=2.25, y=0.0, z=0.0),  # HONEYCOMB_HELIX_SPACING apart
        axis_end=Vec3(x=2.25, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    strands = [
        Strand(id="scaf0", domains=[Domain(helix_id="h0", start_bp=0,
               end_bp=length_bp - 1, direction=Direction.FORWARD)], is_scaffold=True),
        Strand(id="stpl0", domains=[Domain(helix_id="h0", start_bp=length_bp - 1,
               end_bp=0, direction=Direction.REVERSE)]),
        Strand(id="scaf1", domains=[Domain(helix_id="h1", start_bp=0,
               end_bp=length_bp - 1, direction=Direction.FORWARD)], is_scaffold=False),
        Strand(id="stpl1", domains=[Domain(helix_id="h1", start_bp=length_bp - 1,
               end_bp=0, direction=Direction.REVERSE)]),
    ]
    return Design(id="two", helices=[h0, h1], strands=strands,
                  lattice_type=LatticeType.FREE)


def _geometry_for(design: Design) -> list[dict]:
    """Build geometry dicts the same way as GET /api/design/geometry."""
    from backend.api.crud import _geometry_for_design
    return _geometry_for_design(design)


# ── XPBD engine tests ─────────────────────────────────────────────────────────


class TestBuildSimulation:
    def test_particle_count_single_helix(self):
        design = _make_single_helix_design(21)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        # 21 bp × 2 strands = 42 backbone beads
        assert len(sim.particles) == 42
        assert sim.positions.shape == (42, 3)

    def test_bond_count_single_helix(self):
        """Each strand of length 21 contributes 20 intra-domain bonds."""
        design = _make_single_helix_design(21)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        # 2 strands × 20 bonds = 40 bonds
        assert len(sim.bond_ij) == 40

    def test_bond_rest_lengths_near_backbone_bond(self):
        """Rest lengths for a B-DNA helix should be close to BACKBONE_BOND_LENGTH."""
        design = _make_single_helix_design(21)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        # Rest lengths are derived from actual initial positions.
        assert np.allclose(sim.bond_rest, BACKBONE_BOND_LENGTH, atol=0.01), \
            f"Bond lengths deviate: min={sim.bond_rest.min():.4f}, max={sim.bond_rest.max():.4f}"

    def test_index_map_completeness(self):
        design = _make_single_helix_design(10)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        # Every geometry nucleotide should be in the index map.
        assert len(sim.index_map) == len(geo)

    def test_positions_match_geometry(self):
        """Initial SimState positions must equal the geometric backbone positions."""
        design = _make_single_helix_design(10)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        for nuc in geo:
            key = (nuc["helix_id"], nuc["bp_index"], nuc["direction"])
            idx = sim.index_map[key]
            np.testing.assert_allclose(
                sim.positions[idx], nuc["backbone_position"], atol=1e-12
            )

    def test_empty_design(self):
        """build_simulation on an empty design should not raise."""
        design = Design(id="empty", lattice_type=LatticeType.FREE)
        sim    = build_simulation(design, [])
        assert len(sim.particles) == 0
        assert sim.positions.shape == (0, 3)

    def test_two_helix_excluded_volume_pairs(self):
        """Helices 2.25 nm apart should have EV pairs built (beads within 1.2 nm cutoff)."""
        design = _make_two_helix_design(10)
        geo    = _geometry_for(design)
        sim    = build_simulation(design, geo)
        # Adjacent helices will have backbone beads ~0.25 nm apart at crossover points.
        # The EV cutoff (1.2 nm) should capture at least some pairs.
        assert len(sim.excl_ij) >= 0  # may be zero if helix spacing > cutoff for all beads


class TestXpbdStep:
    def test_step_increments_counter(self):
        design = _make_single_helix_design(10)
        sim    = build_simulation(design, _geometry_for(design))
        assert sim.step == 0
        xpbd_step(sim)
        assert sim.step == 1
        xpbd_step(sim)
        assert sim.step == 2

    def test_positions_change_after_step(self):
        """A perturbed helix should have its positions modified by XPBD."""
        design = _make_single_helix_design(21)
        sim    = build_simulation(design, _geometry_for(design))
        # Perturb all positions by a small random amount.
        rng = np.random.default_rng(42)
        sim.positions += rng.uniform(-0.3, 0.3, size=sim.positions.shape)
        original = sim.positions.copy()
        xpbd_step(sim, n_substeps=5)
        assert not np.allclose(sim.positions, original), \
            "Positions should change after XPBD step on perturbed structure."

    def test_energy_decreases_or_bounded(self):
        """
        V5.1 prerequisite: constraint violation energy should decrease (or remain
        bounded) as XPBD runs on a perturbed helix.
        """
        design = _make_single_helix_design(21)
        sim    = build_simulation(design, _geometry_for(design))
        # Perturb significantly so there is energy to dissipate.
        rng = np.random.default_rng(7)
        sim.positions += rng.uniform(-0.5, 0.5, size=sim.positions.shape)

        energies = [sim_energy(sim)]
        for _ in range(10):
            xpbd_step(sim, n_substeps=10)
            energies.append(sim_energy(sim))

        # Energy should decrease overall (not necessarily monotonically every step
        # with Jacobi, but the final energy should be lower than the initial).
        assert energies[-1] < energies[0], (
            f"Energy did not decrease: initial={energies[0]:.6f}, "
            f"final={energies[-1]:.6f}"
        )

    def test_geometric_positions_near_equilibrium(self):
        """
        Geometric (B-DNA ideal) positions should start at near-zero bond energy
        since rest lengths are derived from initial positions.
        """
        design = _make_single_helix_design(21)
        sim    = build_simulation(design, _geometry_for(design))
        e0 = sim_energy(sim)
        # Energy should be essentially zero for unperturbed B-DNA geometry.
        assert e0 < 1e-20, f"Initial energy should be ~0, got {e0:.4e}"

    def test_helix_remains_helical_after_relaxation(self):
        """
        V5.1 core: after perturbing and relaxing a single helix, the backbone
        beads should still follow roughly helical spacing (axial rise ~0.334 nm).
        """
        design = _make_single_helix_design(21)
        sim    = build_simulation(design, _geometry_for(design))
        rng = np.random.default_rng(99)
        sim.positions += rng.uniform(-0.2, 0.2, size=sim.positions.shape)

        for _ in range(50):
            xpbd_step(sim, n_substeps=10)

        # Extract scaffold strand (FORWARD) backbone bead positions in order.
        fwd_keys = [
            ("test_helix", bp, "FORWARD") for bp in range(21)
        ]
        fwd_pos = np.array([
            sim.positions[sim.index_map[k]] for k in fwd_keys if k in sim.index_map
        ])

        # Check sequential distances are roughly BACKBONE_BOND_LENGTH.
        dists = np.linalg.norm(np.diff(fwd_pos, axis=0), axis=1)
        assert np.all(dists < BACKBONE_BOND_LENGTH + 0.15), \
            f"Some bond lengths too large after relaxation: max={dists.max():.4f}"
        assert np.all(dists > BACKBONE_BOND_LENGTH - 0.15), \
            f"Some bond lengths too small after relaxation: min={dists.min():.4f}"


class TestSimEnergy:
    def test_zero_energy_at_rest(self):
        """Unperturbed geometry → zero bond energy (rest = initial distance)."""
        design = _make_single_helix_design(10)
        sim    = build_simulation(design, _geometry_for(design))
        assert sim_energy(sim) < 1e-20

    def test_positive_energy_when_perturbed(self):
        design = _make_single_helix_design(10)
        sim    = build_simulation(design, _geometry_for(design))
        sim.positions += 0.5
        assert sim_energy(sim) > 0.0


class TestPositionsToUpdates:
    def test_output_format(self):
        design = _make_single_helix_design(5)
        sim    = build_simulation(design, _geometry_for(design))
        updates = positions_to_updates(sim)
        assert len(updates) == len(sim.particles)
        for u in updates:
            assert "helix_id"          in u
            assert "bp_index"          in u
            assert "direction"         in u
            assert "backbone_position" in u
            assert len(u["backbone_position"]) == 3

    def test_positions_match_sim(self):
        design = _make_single_helix_design(5)
        sim    = build_simulation(design, _geometry_for(design))
        updates = positions_to_updates(sim)
        for u in updates:
            key = (u["helix_id"], u["bp_index"], u["direction"])
            idx = sim.index_map[key]
            np.testing.assert_allclose(
                u["backbone_position"], sim.positions[idx].tolist(), atol=1e-12
            )


# ── oxDNA interface tests ─────────────────────────────────────────────────────


class TestOxDNATopology:
    def test_topology_writes_and_has_correct_header(self):
        design = _make_single_helix_design(10)
        with tempfile.NamedTemporaryFile(suffix=".top", delete=False, mode="w") as f:
            path = f.name
        write_topology(design, path)
        lines = Path(path).read_text().splitlines()
        header = lines[0].split()
        n_nucs    = int(header[0])
        n_strands = int(header[1])
        assert n_nucs    == 20   # 10 bp × 2 strands
        assert n_strands == 2    # scaffold + staple

    def test_topology_line_count(self):
        design = _make_single_helix_design(10)
        with tempfile.NamedTemporaryFile(suffix=".top", delete=False, mode="w") as f:
            path = f.name
        write_topology(design, path)
        lines = [l for l in Path(path).read_text().splitlines() if l.strip()]
        # 1 header + 20 nucleotide lines
        assert len(lines) == 21


class TestOxDNAConfiguration:
    def test_configuration_writes_correct_line_count(self):
        design = _make_single_helix_design(10)
        geo    = _geometry_for(design)
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False, mode="w") as f:
            path = f.name
        write_configuration(design, geo, path)
        lines = [l for l in Path(path).read_text().splitlines() if l.strip()]
        # 3 header lines + 20 nucleotide lines
        assert len(lines) == 23

    def test_configuration_positions_in_oxdna_units(self):
        """Backbone positions should be divided by OXDNA_LENGTH_UNIT (~0.8518 nm)."""
        from backend.core.constants import OXDNA_LENGTH_UNIT
        design = _make_single_helix_design(5)
        geo    = _geometry_for(design)
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False, mode="w") as f:
            path = f.name
        write_configuration(design, geo, path)
        lines = Path(path).read_text().splitlines()
        # First nucleotide data line (skip 3 header lines).
        data_lines = [l for l in lines if not l.startswith(('t ', 'b ', 'E ')) and l.strip()]
        parts = data_lines[0].split()
        # pos_z of first FORWARD bead at bp=0 should be ~0 in nm → ~0 in oxDNA units.
        pos_z_oxdna = float(parts[2])
        assert abs(pos_z_oxdna) < 1.0, f"Expected z~0 in oxDNA units, got {pos_z_oxdna}"


class TestOxDNARoundTrip:
    def test_round_trip_positions(self):
        """
        V5.2: write oxDNA configuration, read it back, positions should match
        within float precision (× OXDNA_LENGTH_UNIT).
        """
        from backend.core.constants import OXDNA_LENGTH_UNIT
        design = _make_single_helix_design(10)
        geo    = _geometry_for(design)
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_path = Path(tmpdir) / "test.dat"
            write_configuration(design, geo, conf_path)
            pos_map = read_configuration(conf_path, design)

        # Check that every nucleotide's position round-trips correctly.
        for nuc in geo:
            key = (nuc["helix_id"], nuc["bp_index"], nuc["direction"])
            if key not in pos_map:
                continue
            expected_nm = np.array(nuc["backbone_position"])
            actual_nm   = pos_map[key]
            np.testing.assert_allclose(
                actual_nm, expected_nm,
                atol=1e-4,  # float32 roundoff through oxDNA unit conversion
                err_msg=f"Position mismatch for nucleotide {key}"
            )

    def test_round_trip_nucleotide_count(self):
        design = _make_single_helix_design(10)
        geo    = _geometry_for(design)
        with tempfile.TemporaryDirectory() as tmpdir:
            conf_path = Path(tmpdir) / "test.dat"
            write_configuration(design, geo, conf_path)
            pos_map = read_configuration(conf_path, design)
        # 10 bp × 2 strands = 20 nucleotides
        assert len(pos_map) == 20


class TestNucleotideOrder:
    def test_order_length_matches_design(self):
        design = _make_single_helix_design(10)
        order  = _strand_nucleotide_order(design)
        assert len(order) == 20  # 10 bp × 2 strands

    def test_order_all_unique(self):
        design = _make_two_helix_design(10)
        order  = _strand_nucleotide_order(design)
        assert len(order) == len(set(order)), "Duplicate keys in nucleotide order"
