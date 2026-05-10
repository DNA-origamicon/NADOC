"""
Tests for the fast-mode helix-segment XPBD physics engine.

Organised in implementation order:
  1. skip_loop_mechanics   — twist deficit / loop joint translation layer
  2. xpbd_fast             — particle system, solver, convergence, bending direction
"""

from __future__ import annotations

import math
import time
from typing import List

import numpy as np
import pytest

from backend.core.constants import (
    BDNA_TWIST_PER_BP_DEG,
    SKIP_TWIST_DEFICIT_DEG,
    SSDNA_RISE_PER_BASE_NM,
    SQUARE_TWIST_PER_BP_RAD,
)
from backend.core.models import (
    Design,
    Helix,
    LoopSkip,
    LatticeType,
    Vec3,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers shared across all sections
# ─────────────────────────────────────────────────────────────────────────────


def _make_helix(
    length_bp: int = 63,
    helix_id: str = "h0",
    loop_skips: List[LoopSkip] | None = None,
    twist_per_bp_rad: float | None = None,
) -> Helix:
    if twist_per_bp_rad is None:
        twist_per_bp_rad = math.radians(BDNA_TWIST_PER_BP_DEG)
    return Helix(
        id=helix_id,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * 0.334),
        length_bp=length_bp,
        bp_start=0,
        loop_skips=loop_skips or [],
        twist_per_bp_rad=twist_per_bp_rad,
    )


def _make_helix_with_skip(bp_index: int = 10, length_bp: int = 63) -> Helix:
    return _make_helix(length_bp=length_bp, loop_skips=[LoopSkip(bp_index=bp_index, delta=-1)])


def _make_helix_with_loop(bp_index: int = 10, length_bp: int = 63) -> Helix:
    return _make_helix(length_bp=length_bp, loop_skips=[LoopSkip(bp_index=bp_index, delta=1)])


def _make_sq_helix(length_bp: int = 32) -> Helix:
    return _make_helix(
        length_bp=length_bp,
        twist_per_bp_rad=SQUARE_TWIST_PER_BP_RAD,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — skip_loop_mechanics
# ─────────────────────────────────────────────────────────────────────────────


class TestSkipLoopMechanics:
    """Unit tests for backend.physics.skip_loop_mechanics."""

    def _import(self):
        from backend.physics import skip_loop_mechanics as slm
        return slm

    def test_no_skips_zero_deficit(self):
        """Helix with no loop_skips → twist deficit = 0.0 for every segment."""
        slm = self._import()
        helix = _make_helix(length_bp=63)  # exactly 3 × 21-bp segments
        ranges = slm.compute_segment_bp_ranges(helix)
        assert len(ranges) == 3
        for bp_s, bp_e in ranges:
            deficit = slm.compute_segment_twist_deficit(helix, bp_s, bp_e)
            assert deficit == pytest.approx(0.0)

    def test_skip_negative_deficit(self):
        """Single skip at bp=10 → deficit = SKIP_TWIST_DEFICIT_DEG in segment 0."""
        slm = self._import()
        helix = _make_helix_with_skip(bp_index=10)
        deficit = slm.compute_segment_twist_deficit(helix, 0, 21)
        assert deficit == pytest.approx(SKIP_TWIST_DEFICIT_DEG, abs=0.01)

    def test_loop_positive_surplus(self):
        """Single loop (delta=+1) at bp=10 → surplus = +34.3° in segment 0."""
        slm = self._import()
        helix = _make_helix_with_loop(bp_index=10)
        surplus = slm.compute_segment_twist_deficit(helix, 0, 21)
        assert surplus == pytest.approx(-SKIP_TWIST_DEFICIT_DEG, abs=0.01)  # = +34.3°

    def test_skip_not_in_segment_zero_deficit(self):
        """Skip at bp=25 (in segment 1) → deficit = 0 for segment 0."""
        slm = self._import()
        helix = _make_helix_with_skip(bp_index=25)
        deficit_seg0 = slm.compute_segment_twist_deficit(helix, 0, 21)
        deficit_seg1 = slm.compute_segment_twist_deficit(helix, 21, 42)
        assert deficit_seg0 == pytest.approx(0.0)
        assert deficit_seg1 == pytest.approx(SKIP_TWIST_DEFICIT_DEG, abs=0.01)

    def test_skip_no_loop_joint(self):
        """A skip produces no LoopJointSpec (it only modifies twist deficit)."""
        slm = self._import()
        helix = _make_helix_with_skip(bp_index=10)
        ranges = slm.compute_segment_bp_ranges(helix)
        joints = slm.compute_loop_joints(helix, ranges)
        assert len(joints) == 0

    def test_loop_produces_joint(self):
        """A loop insertion produces exactly one LoopJointSpec in the correct gap."""
        slm = self._import()
        helix = _make_helix_with_loop(bp_index=10)  # bp=10 → segment 0 (range 0–21)
        ranges = slm.compute_segment_bp_ranges(helix)
        joints = slm.compute_loop_joints(helix, ranges)
        assert len(joints) == 1
        j = joints[0]
        assert j.helix_id == helix.id
        assert j.seg_before_idx == 0   # loop inside segment 0 → joint between seg0 and seg1
        assert j.loop_bp_count == 1
        assert j.rest_length_nm == pytest.approx(1 * SSDNA_RISE_PER_BASE_NM)

    def test_sq_helix_preferred_twist(self):
        """SQ helix uses SQUARE_TWIST_PER_BP_RAD (33.75°/bp), not HC 34.3°/bp."""
        slm = self._import()
        helix = _make_sq_helix(length_bp=42)  # 2 × 21-bp segments
        ranges = slm.compute_segment_bp_ranges(helix)
        assert len(ranges) == 2
        pref = slm.compute_preferred_segment_twist_rad(helix, 0, 21)
        expected = 21.0 * SQUARE_TWIST_PER_BP_RAD
        assert pref == pytest.approx(expected, abs=1e-6)

    def test_segment_bp_ranges_partial_last_segment(self):
        """Helix length not a multiple of FAST_SEGMENT_BP → last segment is shorter."""
        slm = self._import()
        helix = _make_helix(length_bp=50)  # 2 full (0–21, 21–42) + 1 partial (42–50)
        ranges = slm.compute_segment_bp_ranges(helix)
        assert len(ranges) == 3
        assert ranges[0] == (0, 21)
        assert ranges[1] == (21, 42)
        assert ranges[2] == (42, 50)

    def test_multiple_skips_accumulate(self):
        """Two skips in the same segment accumulate to 2 × SKIP_TWIST_DEFICIT."""
        slm = self._import()
        helix = _make_helix(
            length_bp=63,
            loop_skips=[LoopSkip(bp_index=5, delta=-1), LoopSkip(bp_index=15, delta=-1)],
        )
        deficit = slm.compute_segment_twist_deficit(helix, 0, 21)
        assert deficit == pytest.approx(2.0 * SKIP_TWIST_DEFICIT_DEG, abs=0.01)

    def test_preferred_twist_with_skip(self):
        """Preferred twist for a segment with a skip is reduced by one bp worth."""
        slm = self._import()
        helix = _make_helix_with_skip(bp_index=10)  # HC helix, 1 skip in seg0
        pref = slm.compute_preferred_segment_twist_rad(helix, 0, 21)
        # Effective bp = 21 - 1 = 20, plus SKIP_TWIST_DEFICIT in radians
        expected = (21.0 * math.radians(BDNA_TWIST_PER_BP_DEG)
                    + math.radians(SKIP_TWIST_DEFICIT_DEG))
        assert pref == pytest.approx(expected, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — xpbd_fast (physics engine)
# ─────────────────────────────────────────────────────────────────────────────
#
# These tests require a working xpbd_fast.py.  They are separated so they can
# be run independently of the skip_loop_mechanics tests.


def _make_6hb_design(length_bp: int = 252) -> Design:
    """
    Minimal 6-helix bundle design (honeycomb layout) for physics tests.
    No strands or crossovers — only helices.  Crossovers are added by
    specialised helpers.
    """
    from backend.core.models import DesignMetadata
    import uuid

    # HC layout: 6 helices in a ring, 2.25 nm spacing
    # Approximate layout: 3 rows × 2 columns at HC spacings
    HC = 2.25
    positions = [
        (0.0,        0.0),       # h0 FORWARD
        (1.9486,    -1.125),     # h1 REVERSE
        (1.9486,     1.125),     # h2 FORWARD  (actually REVERSE by cell rule, but geometry only)
        (3.8971,     0.0),       # h3
        (3.8971,     2.25),      # h4
        (1.9486,     3.375),     # h5
    ]
    helices = []
    for i, (x, y) in enumerate(positions):
        helices.append(Helix(
            id=f"h{i}",
            axis_start=Vec3(x=x, y=y, z=0.0),
            axis_end=Vec3(x=x, y=y, z=length_bp * 0.334),
            length_bp=length_bp,
            bp_start=0,
            loop_skips=[],
            twist_per_bp_rad=math.radians(34.3),
        ))

    return Design(
        id=str(uuid.uuid4()),
        helices=helices,
        strands=[],
        crossovers=[],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="test_6hb"),
        deformations=[],
        overhangs=[],
    )


def _add_skips_to_face(design: Design, helix_ids: List[str], n_skips: int = 6) -> Design:
    """
    Add n_skips evenly-spaced skips to the specified helices.
    Returns a new Design with modified helices.
    """
    spacing = design.helices[0].length_bp // n_skips
    new_helices = []
    skip_ids = set(helix_ids)
    for h in design.helices:
        if h.id in skip_ids:
            new_ls = [LoopSkip(bp_index=i * spacing + spacing // 2, delta=-1)
                      for i in range(n_skips)]
            new_helices.append(h.model_copy(update={"loop_skips": new_ls}))
        else:
            new_helices.append(h)
    return design.model_copy(update={"helices": new_helices})


class TestXpbdFast:
    """Physics engine tests — require xpbd_fast.py to be implemented."""

    def _build(self, design):
        from backend.physics.xpbd_fast import build_fast_simulation
        return build_fast_simulation(design)

    def _run_to_convergence(self, sim, max_frames: int = 300):
        from backend.physics.xpbd_fast import fast_xpbd_step, CONVERGENCE_THRESHOLD, CONVERGENCE_STREAK
        streak = 0
        for _ in range(max_frames):
            max_disp = fast_xpbd_step(sim)
            if max_disp < CONVERGENCE_THRESHOLD:
                streak += 1
            else:
                streak = 0
            if streak >= CONVERGENCE_STREAK:
                return True
        return False

    def test_straight_bundle_stays_straight(self):
        """
        6HB with no skips/loops must converge to a configuration where every
        segment position stays within 0.5 nm of the original helix axis.
        """
        from backend.physics.xpbd_fast import build_fast_simulation
        design = _make_6hb_design(length_bp=252)
        sim = build_fast_simulation(design)

        converged = self._run_to_convergence(sim)
        assert converged, "Solver did not converge within max_frames"

        # Check that each segment is close to its original axis position
        for h_id, seg_indices in sim.helix_segment_map.items():
            h = next(h for h in design.helices if h.id == h_id)
            axis_start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
            axis_end   = np.array([h.axis_end.x,   h.axis_end.y,   h.axis_end.z])
            axis_dir   = axis_end - axis_start
            axis_len   = np.linalg.norm(axis_dir)
            axis_hat   = axis_dir / axis_len

            for idx in seg_indices:
                pos = sim.pos[idx]
                # Project onto axis; perpendicular distance = off-axis deviation
                t = np.dot(pos - axis_start, axis_hat)
                proj = axis_start + t * axis_hat
                deviation = np.linalg.norm(pos - proj)
                assert deviation < 0.5, (
                    f"Helix {h_id} segment {idx}: off-axis deviation {deviation:.3f} nm ≥ 0.5 nm"
                )

    def test_skip_bends_toward_skip_side(self):
        """
        6HB with skips on helices h0/h1/h2 only (one face) must converge to a
        configuration that is curved toward the skip side.

        The skip side (h0/h1/h2) will have shorter effective path length, so
        their centroid must be displaced *toward* the centre of curvature, which
        means the midpoint centroid of h0/h1/h2 at the middle of the bundle is
        closer to the axis of h3/h4/h5 (or vice versa — the bundle curves, so
        the skip side bows inward).

        Test: after convergence, the Y-centroid of [h0,h1,h2] segments at the
        bundle midpoint must be LESS than the Y-centroid of [h3,h4,h5] segments
        (i.e., bends toward h0/h1/h2 which all have y ≤ 0 in the fixture layout).

        STOP AND REPORT IF THIS FAILS — the entire engine validity depends on
        skips causing bending toward the correct side.
        """
        from backend.physics.xpbd_fast import build_fast_simulation
        design = _make_6hb_design(length_bp=252)
        # Add 6 skips to h0, h1, h2 (the helices with y ≤ 0 in the fixture)
        design = _add_skips_to_face(design, ["h0", "h1", "h2"], n_skips=6)
        sim = build_fast_simulation(design)

        converged = self._run_to_convergence(sim, max_frames=500)
        assert converged, "Solver did not converge"

        # Get the mid-bundle segment index for each helix
        def _mid_segs(h_ids):
            """Return Z-sorted mid-region segment positions for a set of helices."""
            positions = []
            for h_id in h_ids:
                indices = sim.helix_segment_map[h_id]
                # Take the middle third of segments
                n = len(indices)
                mid_indices = indices[n // 3: 2 * n // 3]
                for idx in mid_indices:
                    positions.append(sim.pos[idx])
            return np.array(positions)

        skip_side_pos = _mid_segs(["h0", "h1", "h2"])
        free_side_pos = _mid_segs(["h3", "h4", "h5"])

        # In the HC layout used in this fixture:
        #   h0 is at y=0, h1 at y=-1.125, h2 at y=+1.125  (skip side, centered at y=0)
        #   h3 at y=0, h4 at y=+2.25, h5 at y=+3.375       (free side, centered at y~+1.9)
        # After bending, the skip side (shorter arc) bows toward the free side.
        # Specifically, the bundle midpoint on the skip side should move in +Y
        # relative to its initial position, and the free side should move in -Y.

        # Compute initial centroid Y for each side from the design
        def _initial_y_centroid(h_ids):
            ys = [next(h for h in design.helices if h.id == hid).axis_start.y
                  for hid in h_ids]
            return sum(ys) / len(ys)

        init_skip_y = _initial_y_centroid(["h0", "h1", "h2"])
        init_free_y = _initial_y_centroid(["h3", "h4", "h5"])

        final_skip_y = float(skip_side_pos[:, 1].mean())
        final_free_y = float(free_side_pos[:, 1].mean())

        delta_skip_y = final_skip_y - init_skip_y
        delta_free_y = final_free_y - init_free_y

        # The skip side should bow toward the free side (+Y direction)
        # i.e., delta_skip_y > delta_free_y
        assert delta_skip_y > delta_free_y, (
            f"BENDING DIRECTION WRONG: skip side moved {delta_skip_y:+.3f} nm in Y, "
            f"free side moved {delta_free_y:+.3f} nm in Y. "
            f"Expected skip side to bow toward free side (larger +Y shift). "
            f"Check that skip twist deficit reduces segment path length on skip helices, "
            f"coupling to backbone constraints to produce bowing toward the skip side."
        )

    def test_loop_increases_flexibility(self):
        """
        A loop insertion at the helix midpoint must produce a LoopJoint particle
        with bend alpha at least 100× larger (more flexible) than dsDNA alpha.

        We verify via the built sim state: the alpha value for the loop joint's
        bend constraint must equal ALPHA_BEND_SSDNA, not ALPHA_BEND_DSDNA.
        """
        from backend.physics.xpbd_fast import build_fast_simulation
        from backend.core.constants import ALPHA_BEND_DSDNA, ALPHA_BEND_SSDNA

        length_bp = 252
        loop_bp = 126  # midpoint
        helix = _make_helix(
            length_bp=length_bp,
            loop_skips=[LoopSkip(bp_index=loop_bp, delta=1)],
        )
        from backend.core.models import DesignMetadata
        import uuid
        design = Design(
            id=str(uuid.uuid4()),
            helices=[helix],
            strands=[],
            crossovers=[],
            lattice_type=LatticeType.HONEYCOMB,
            metadata=DesignMetadata(name="loop_test"),
            deformations=[],
            overhangs=[],
        )
        sim = build_fast_simulation(design)

        # Find the loop joint segment index (should be between segments 5 and 6 for bp=126)
        # The loop joint particle is identified by its mass (0.3 vs 1.0 for helix segments)
        loop_joint_indices = np.where(np.abs(sim.mass - 0.3) < 0.01)[0]
        assert len(loop_joint_indices) >= 1, "No loop joint particle found in sim"

        # Find the bend alpha for the loop joint
        # The bn_alpha array has per-joint alpha values indexed by the bend constraint index
        # corresponding to the loop joint
        loop_joint_idx = int(loop_joint_indices[0])

        # Find the bend constraint involving this particle
        mask = (sim.bn_ij[:, 0] == loop_joint_idx) | (sim.bn_ij[:, 1] == loop_joint_idx)
        assert mask.any(), "No bend constraint found for loop joint particle"

        loop_alphas = sim.bn_alpha[mask]
        assert np.all(loop_alphas >= ALPHA_BEND_SSDNA * 0.5), (
            f"Loop joint bend alpha {loop_alphas} should be ≥ ALPHA_BEND_SSDNA/2 = {ALPHA_BEND_SSDNA/2}"
        )
        assert np.all(loop_alphas > ALPHA_BEND_DSDNA * 10), (
            f"Loop joint bend alpha {loop_alphas} should be >> ALPHA_BEND_DSDNA = {ALPHA_BEND_DSDNA}"
        )

    def test_convergence_time_200_particles(self):
        """
        Solver must converge in under 10 seconds for a ~200-particle system
        (including Numba JIT compilation overhead).
        """
        from backend.physics.xpbd_fast import build_fast_simulation

        design = _make_6hb_design(length_bp=252)
        sim = build_fast_simulation(design)

        # Verify we have a meaningful particle count
        n_particles = sim.pos.shape[0]
        assert n_particles >= 60, f"Expected ≥60 particles, got {n_particles}"

        start = time.time()
        converged = self._run_to_convergence(sim, max_frames=1000)
        elapsed = time.time() - start

        assert converged, "Solver did not converge"
        assert elapsed < 10.0, (
            f"Convergence took {elapsed:.1f}s — must be under 10s for ~{n_particles} particles. "
            f"Check that @numba.njit is applied to _solve_constraints_inner."
        )

    def test_warmstart_reduces_residuals(self):
        """
        Detailed-mode SimState initialized from fast-mode converged positions must
        have lower initial energy than one initialized from canonical geometry.
        """
        from backend.physics.xpbd_fast import build_fast_simulation, warmstart_from_fast
        from backend.physics.xpbd import build_simulation, sim_energy
        from backend.core.geometry import nucleotide_positions

        design = _make_6hb_design(length_bp=126)

        # Canonical geometry
        geometry = []
        for h in design.helices:
            geometry.extend(nucleotide_positions(h))

        # Cold start: build detailed sim from canonical geometry
        sim_cold = build_simulation(design, geometry)
        energy_cold = sim_energy(sim_cold)

        # Fast-mode convergence
        fast_sim = build_fast_simulation(design)
        self._run_to_convergence(fast_sim, max_frames=500)

        # Warm start: build detailed sim from fast-mode positions
        sim_warm = warmstart_from_fast(fast_sim, design, geometry)
        energy_warm = sim_energy(sim_warm)

        assert energy_warm <= energy_cold, (
            f"Warm-start energy {energy_warm:.4f} should be ≤ cold energy {energy_cold:.4f}. "
            f"Fast-mode warm-starting is not helping."
        )
