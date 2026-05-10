"""
Tests for backend/core/cg_to_atomistic.py.

Coverage backfill — Refactor 12-A. Pre-coverage: 0% (Finding #16).

Module overview
---------------
cg_to_atomistic.py provides two CG-to-atomistic bridges:

  * Phase 3a — _refit_helix_axes / build_atomistic_model_from_cg
                PCA axis fitting; kept for reference (validated insufficient).
  * Phase 3b — _smooth_cg_positions_per_domain / build_atomistic_model_from_cg_spline
                Per-domain Gaussian smoothing of CG backbone positions used as
                nuc_pos_override in build_atomistic_model.

All tests build self-contained fixtures (small honeycomb bundle designs) and
verify ACTUAL OUTPUT VALUES — no "no exception raised" assertions, no mocking
of the SUT. Per precondition #21 (Pass 11-B refinement): real numpy.allclose,
column-anchored numerical assertions, and reference-data comparisons.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.core.atomistic import AtomisticModel
from backend.core.cg_to_atomistic import (
    _fit_helix_axis,
    _project_onto_axis,
    _refit_helix_axes,
    _smooth_cg_positions_per_domain,
    build_atomistic_model_from_cg,
    build_atomistic_model_from_cg_spline,
)
from backend.core.constants import NM_TO_OXDNA
from backend.core.lattice import make_bundle_design
from backend.core.models import Design
from backend.core.sequences import domain_bp_range
from backend.physics.oxdna_interface import (
    _strand_nucleotide_order,
    write_configuration,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


_CELLS_2HB = [(0, 0), (0, 1)]


def _small_design() -> Design:
    """2HB 30-bp design — minimum to exercise multi-helix paths."""
    return make_bundle_design(cells=_CELLS_2HB, length_bp=30, plane="XY")


def _ideal_geometry(design: Design) -> list[dict]:
    """Build geometry list (one entry per (helix, bp, direction)) using the
    same internal helper that write_configuration uses for missing geometry —
    yields ideal B-DNA backbone positions. Sufficient input for the synthetic
    .dat fixture (write_configuration falls back to _compute_nuc_geometry
    when its passed-in geometry list is missing keys, so an empty list works).
    """
    return []


def _write_synthetic_conf(design: Design, conf_path: Path) -> None:
    """Use the production write_configuration with empty external geometry,
    forcing the internal _compute_nuc_geometry fallback.  Result: a valid
    .dat file with ideal B-DNA backbone positions, suitable for round-trip
    tests of read_configuration + the smoothing/refit helpers.
    """
    write_configuration(design, geometry=_ideal_geometry(design), path=conf_path)


def _ideal_cg_positions_dict(
    design: Design,
) -> dict[tuple[str, int, str], np.ndarray]:
    """Build a CG-positions dict directly (no .dat round-trip) using the
    canonical _strand_nucleotide_order.  All positions are ideal B-DNA values
    plus a controlled perturbation for smoothing tests.
    """
    from backend.physics.oxdna_interface import _compute_nuc_geometry

    cg: dict[tuple[str, int, str], np.ndarray] = {}
    order = _strand_nucleotide_order(design)
    for key in order:
        if len(key) != 3:
            continue  # skip loop-copy keys for these unit fixtures
        h_id, bp, dir_str = key
        nuc = _compute_nuc_geometry(design, h_id, bp, dir_str)
        if nuc is None:
            continue
        cg[(h_id, bp, dir_str)] = np.asarray(nuc["backbone_position"], dtype=float)
    return cg


# ── _fit_helix_axis ──────────────────────────────────────────────────────────


class TestFitHelixAxis:
    def test_pca_recovers_known_axis_direction(self):
        """Cloud of points on the +x axis with small noise → fitted direction
        should be (±1, 0, 0) and centroid near the cloud mean."""
        rng = np.random.default_rng(42)
        n = 50
        t = np.linspace(0.0, 10.0, n)
        # Points along x with tiny y/z noise so SVD has a clear principal axis.
        pts = np.stack(
            [t, 0.01 * rng.standard_normal(n), 0.01 * rng.standard_normal(n)],
            axis=1,
        )
        centroid, direction = _fit_helix_axis(pts)
        # Centroid should be near (5, 0, 0) (mean of t = 5).
        assert np.allclose(centroid, [5.0, 0.0, 0.0], atol=0.05)
        # Direction should be unit-length.
        assert abs(np.linalg.norm(direction) - 1.0) < 1e-9
        # Principal axis should align with x (sign is arbitrary).
        assert abs(abs(direction[0]) - 1.0) < 1e-3

    def test_pca_recovers_diagonal_axis(self):
        """Points along (1,1,1)/sqrt(3) — fitted direction must align with
        that diagonal up to sign."""
        n = 40
        s = np.linspace(-5.0, 5.0, n)
        unit = np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0)
        pts = s[:, None] * unit[None, :]  # exact line, no noise
        centroid, direction = _fit_helix_axis(pts)
        assert np.allclose(centroid, [0.0, 0.0, 0.0], atol=1e-9)
        # |direction · unit| ≈ 1 (sign is free).
        assert abs(abs(float(np.dot(direction, unit))) - 1.0) < 1e-9


# ── _project_onto_axis ───────────────────────────────────────────────────────


class TestProjectOntoAxis:
    def test_projection_origin_axis_returns_x_component(self):
        """For axis through origin along +x, projection of (3, 7, -2) is 3."""
        centroid = np.array([0.0, 0.0, 0.0])
        direction = np.array([1.0, 0.0, 0.0])
        s = _project_onto_axis(np.array([3.0, 7.0, -2.0]), centroid, direction)
        assert s == pytest.approx(3.0, abs=1e-12)

    def test_projection_relative_to_centroid(self):
        """For axis through (10, 0, 0) along +y, projection of (12, 4, 0) is 4."""
        centroid = np.array([10.0, 0.0, 0.0])
        direction = np.array([0.0, 1.0, 0.0])
        s = _project_onto_axis(np.array([12.0, 4.0, 0.0]), centroid, direction)
        assert s == pytest.approx(4.0, abs=1e-12)


# ── _smooth_cg_positions_per_domain ──────────────────────────────────────────


class TestSmoothCgPositionsPerDomain:
    def test_returns_dict_with_same_keys_as_input(self):
        design = _small_design()
        cg = _ideal_cg_positions_dict(design)
        smoothed = _smooth_cg_positions_per_domain(design, cg, sigma=2.0)
        # Every input key reachable through a strand domain should appear in the
        # output (the helper iterates strands × domains × bp_range).
        keys_via_domains: set[tuple[str, int, str]] = set()
        for strand in design.strands:
            for domain in strand.domains:
                for bp in domain_bp_range(domain):
                    key = (domain.helix_id, bp, domain.direction.value)
                    if key in cg:
                        keys_via_domains.add(key)
        assert set(smoothed.keys()) == keys_via_domains
        assert len(smoothed) > 0

    def test_returns_3d_vectors(self):
        design = _small_design()
        cg = _ideal_cg_positions_dict(design)
        smoothed = _smooth_cg_positions_per_domain(design, cg, sigma=2.0)
        for key, pos in smoothed.items():
            assert pos.shape == (3,), f"{key}: shape {pos.shape} != (3,)"

    def test_sigma_zero_returns_raw_positions(self):
        """sigma <= 0 path: smoothed[key] == cg[key] (copy semantics)."""
        design = _small_design()
        cg = _ideal_cg_positions_dict(design)
        smoothed = _smooth_cg_positions_per_domain(design, cg, sigma=0.0)
        for key, pos in smoothed.items():
            assert np.allclose(pos, cg[key], atol=1e-12), (
                f"{key}: sigma=0 should pass-through but got delta "
                f"{np.linalg.norm(pos - cg[key]):.3e}"
            )

    def test_smoothing_reduces_noise_within_domain(self):
        """Inject high-frequency noise into a domain's positions; Gaussian
        smoothing must reduce the per-bp position variance vs the noisy input
        AND keep the domain mean position approximately invariant."""
        design = _small_design()
        cg_clean = _ideal_cg_positions_dict(design)
        rng = np.random.default_rng(0)
        cg_noisy: dict[tuple[str, int, str], np.ndarray] = {}
        for k, v in cg_clean.items():
            cg_noisy[k] = v + 0.5 * rng.standard_normal(3)  # 5 Å noise

        # Pick a domain with at least 5 nucleotides.
        target_strand = design.strands[0]
        target_domain = next(
            d
            for d in target_strand.domains
            if abs(d.end_bp - d.start_bp) + 1 >= 5
        )
        keys = [
            (target_domain.helix_id, bp, target_domain.direction.value)
            for bp in domain_bp_range(target_domain)
        ]
        keys = [k for k in keys if k in cg_noisy]
        assert len(keys) >= 5

        smoothed = _smooth_cg_positions_per_domain(design, cg_noisy, sigma=2.0)

        noisy_arr    = np.array([cg_noisy[k] for k in keys])
        smoothed_arr = np.array([smoothed[k] for k in keys])

        # Variance of bp-to-bp position differences along the domain is the
        # right measure (domain-mean differences cancel; we want curvature/
        # noise reduction).
        noisy_diffs    = np.diff(noisy_arr,    axis=0)
        smoothed_diffs = np.diff(smoothed_arr, axis=0)
        assert np.var(smoothed_diffs) < np.var(noisy_diffs), (
            f"Smoothing failed to reduce diff-variance: "
            f"noisy={np.var(noisy_diffs):.4f}, smoothed={np.var(smoothed_diffs):.4f}"
        )
        # Mean position of the domain should be ~preserved by Gaussian smoothing
        # with mode='nearest' (small drift acceptable).
        assert np.allclose(noisy_arr.mean(axis=0), smoothed_arr.mean(axis=0), atol=0.3)

    def test_short_domain_uses_raw_positions(self):
        """When a domain has < 3 valid CG positions, the helper takes the
        short-circuit branch and copies raw positions verbatim."""
        design = _small_design()
        # Only keep the first 2 bp of the first domain in cg_positions; all
        # other domains will have 0 valid positions and be skipped.
        first_strand = design.strands[0]
        first_domain = first_strand.domains[0]
        full_cg = _ideal_cg_positions_dict(design)
        keep_keys = [
            (first_domain.helix_id, bp, first_domain.direction.value)
            for bp in list(domain_bp_range(first_domain))[:2]
        ]
        cg_partial = {k: full_cg[k] for k in keep_keys if k in full_cg}
        assert len(cg_partial) == 2

        smoothed = _smooth_cg_positions_per_domain(design, cg_partial, sigma=2.0)
        # Exactly the 2 input keys come back, with identical positions.
        assert set(smoothed.keys()) == set(cg_partial.keys())
        for k in cg_partial:
            assert np.allclose(smoothed[k], cg_partial[k], atol=1e-12)


# ── _refit_helix_axes ────────────────────────────────────────────────────────


class TestRefitHelixAxes:
    def test_helix_with_no_cg_positions_is_unchanged(self):
        """Helices missing from cg_positions retain their original axis."""
        design = _small_design()
        # Empty cg_positions: every helix should be returned untouched.
        new_design = _refit_helix_axes(design, {})
        assert len(new_design.helices) == len(design.helices)
        for orig, new in zip(design.helices, new_design.helices):
            assert orig.axis_start == new.axis_start
            assert orig.axis_end == new.axis_end

    def test_axis_refit_preserves_helix_ids(self):
        design = _small_design()
        cg = _ideal_cg_positions_dict(design)
        new_design = _refit_helix_axes(design, cg)
        assert [h.id for h in new_design.helices] == [h.id for h in design.helices]

    def test_axis_refit_aligns_with_input_cloud(self):
        """Build a synthetic cloud aligned with the original helix axis but
        with a small perpendicular offset added; refit should produce an axis
        with direction equal to the original (up to sign)."""
        design = _small_design()
        helix = design.helices[0]
        start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
        end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
        orig_dir = (end - start) / (np.linalg.norm(end - start) + 1e-14)

        # Generate 10 points along the axis with tiny radial noise.
        pts = [start + t * (end - start) for t in np.linspace(0.05, 0.95, 10)]
        rng = np.random.default_rng(7)
        cg: dict[tuple[str, int, str], np.ndarray] = {}
        for i, p in enumerate(pts):
            jitter = 0.005 * rng.standard_normal(3)
            cg[(helix.id, i, "FORWARD")] = p + jitter

        new_design = _refit_helix_axes(design, cg)
        new_helix = next(h for h in new_design.helices if h.id == helix.id)
        new_start = np.array([new_helix.axis_start.x, new_helix.axis_start.y, new_helix.axis_start.z])
        new_end   = np.array([new_helix.axis_end.x,   new_helix.axis_end.y,   new_helix.axis_end.z])
        new_dir = (new_end - new_start) / (np.linalg.norm(new_end - new_start) + 1e-14)

        # New direction must be close to original (the sign-correction branch
        # ensures we never get the antiparallel solution).
        assert float(np.dot(new_dir, orig_dir)) > 0.9999

    def test_axis_refit_handles_single_point_helix(self):
        """A helix with only one CG sample (< 2) should be left unchanged."""
        design = _small_design()
        helix = design.helices[0]
        cg = {
            (helix.id, 0, "FORWARD"): np.array(
                [helix.axis_start.x, helix.axis_start.y, helix.axis_start.z]
            )
        }
        new_design = _refit_helix_axes(design, cg)
        # First helix unchanged because only 1 cg point (< 2).
        new_helix = next(h for h in new_design.helices if h.id == helix.id)
        assert new_helix.axis_start == helix.axis_start
        assert new_helix.axis_end == helix.axis_end

    def test_axis_refit_corrects_flipped_pca_direction(self):
        """When the SVD principal direction points opposite to the original
        axis, the helper must flip it.  Force this by feeding cg points sorted
        in reverse order (PCA sign is then determined by the data layout —
        either way, the dot-product guard kicks in).  Verify new_dir · orig_dir > 0.
        """
        design = _small_design()
        helix = design.helices[0]
        start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
        end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
        orig_dir = (end - start) / (np.linalg.norm(end - start) + 1e-14)

        # Generate strict-line points (no noise) so PCA is deterministic.
        n = 12
        pts = [start + t * (end - start) for t in np.linspace(0.0, 1.0, n)]
        # Insert into dict: dict insertion order matters for the helper's
        # cg_positions.items() iteration.  Use reversed order to force a
        # potential sign-flip branch.
        cg: dict[tuple[str, int, str], np.ndarray] = {}
        for i in range(n - 1, -1, -1):
            cg[(helix.id, i, "FORWARD")] = pts[i]

        new_design = _refit_helix_axes(design, cg)
        new_helix = next(h for h in new_design.helices if h.id == helix.id)
        new_dir = np.array(
            [new_helix.axis_end.x - new_helix.axis_start.x,
             new_helix.axis_end.y - new_helix.axis_start.y,
             new_helix.axis_end.z - new_helix.axis_start.z]
        )
        new_dir /= np.linalg.norm(new_dir) + 1e-14
        # Guarantee: new_dir is in the same half-space as orig_dir.
        assert float(np.dot(new_dir, orig_dir)) > 0.0


# ── build_atomistic_model_from_cg_spline (orchestrator) ──────────────────────


class TestBuildAtomisticModelFromCgSpline:
    def test_returns_atomistic_model_with_atoms(self, tmp_path: Path):
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg_spline(design, conf, sigma=2.0)
        assert isinstance(model, AtomisticModel)
        assert len(model.atoms) > 0
        assert len(model.bonds) > 0

    def test_serials_are_unique_and_dense(self, tmp_path: Path):
        """Serials are 0-based and contiguous — the standard build_atomistic_model
        invariant should propagate through the spline orchestrator."""
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg_spline(design, conf, sigma=2.0)
        serials = sorted(a.serial for a in model.atoms)
        assert serials[0] == 0
        assert serials[-1] == len(model.atoms) - 1
        assert len(set(serials)) == len(serials)

    def test_atom_positions_finite(self, tmp_path: Path):
        """No NaN/Inf in atom coordinates — guards against bad smoothing or
        empty position-override propagation."""
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg_spline(design, conf, sigma=2.0)
        coords = np.array([[a.x, a.y, a.z] for a in model.atoms])
        assert np.all(np.isfinite(coords)), "non-finite atom coordinates"

    def test_sigma_zero_path_runs_and_returns_model(self, tmp_path: Path):
        """sigma=0 hits the short-circuit pass-through branch in
        _smooth_cg_positions_per_domain.  Output must still be a valid model."""
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg_spline(design, conf, sigma=0.0)
        assert isinstance(model, AtomisticModel)
        assert len(model.atoms) > 0


# ── build_atomistic_model_from_cg (PCA orchestrator) ─────────────────────────


class TestBuildAtomisticModelFromCg:
    def test_returns_atomistic_model_with_atoms(self, tmp_path: Path):
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg(design, conf)
        assert isinstance(model, AtomisticModel)
        assert len(model.atoms) > 0
        assert len(model.bonds) > 0

    def test_atom_count_matches_spline_orchestrator(self, tmp_path: Path):
        """Phase 3a (PCA refit) and Phase 3b (spline override) must produce
        the same number of atoms and bonds — both reuse build_atomistic_model
        underneath, just with different geometric inputs."""
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model_pca    = build_atomistic_model_from_cg(design, conf)
        model_spline = build_atomistic_model_from_cg_spline(design, conf, sigma=2.0)
        assert len(model_pca.atoms)    == len(model_spline.atoms)
        assert len(model_pca.bonds)    == len(model_spline.bonds)

    def test_atom_positions_finite(self, tmp_path: Path):
        design = _small_design()
        conf = tmp_path / "ideal.dat"
        _write_synthetic_conf(design, conf)

        model = build_atomistic_model_from_cg(design, conf)
        coords = np.array([[a.x, a.y, a.z] for a in model.atoms])
        assert np.all(np.isfinite(coords))


# ── End-to-end honesty: override actually drives backbone positions ─────────


class TestSplineOverrideDrivesBackbonePositions:
    """When sigma=0, _smooth_cg_positions_per_domain returns the raw .dat
    positions verbatim.  Those positions are then injected as nuc_pos.position
    in build_atomistic_model.  This test verifies the override is actually
    consumed by perturbing the input .dat values and observing a corresponding
    change in atom coordinates — proving the orchestrator wires through.
    """

    def test_axial_perturbation_propagates_to_atoms(self, tmp_path: Path):
        """Helices in this fixture run along the Z axis (plane='XY').  A uniform
        +Z shift of every CG position is therefore an *axial* shift (parallel to
        the helix axis) — which survives _atom_frame's axis-projection step in
        build_atomistic_model.  The mean atom-Z shift must equal the input
        shift to within numerical precision.
        """
        from backend.core.constants import OXDNA_LENGTH_UNIT

        design = _small_design()
        # Confirm fixture invariant: helices along Z.
        h = design.helices[0]
        assert h.axis_start.x == pytest.approx(h.axis_end.x)
        assert h.axis_start.y == pytest.approx(h.axis_end.y)
        assert h.axis_start.z != h.axis_end.z

        conf_a = tmp_path / "a.dat"
        conf_b = tmp_path / "b.dat"
        _write_synthetic_conf(design, conf_a)

        shift_oxdna = 5.0  # ~4.26 nm along z
        new_lines: list[str] = []
        for line in conf_a.read_text().splitlines():
            if line.startswith(("t ", "b ", "E ")) or not line.strip():
                new_lines.append(line)
                continue
            parts = line.split()
            parts[2] = f"{float(parts[2]) + shift_oxdna:.6f}"  # shift z component
            new_lines.append("  ".join(parts))
        conf_b.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        model_a = build_atomistic_model_from_cg_spline(design, conf_a, sigma=0.0)
        model_b = build_atomistic_model_from_cg_spline(design, conf_b, sigma=0.0)
        assert len(model_a.atoms) == len(model_b.atoms)

        zs_a = np.array([a.z for a in model_a.atoms])
        zs_b = np.array([a.z for a in model_b.atoms])
        mean_dz = float((zs_b - zs_a).mean())
        expected_shift_nm = shift_oxdna * OXDNA_LENGTH_UNIT
        # Axial shift survives _atom_frame projection exactly (modulo round-trip
        # noise on the order of 1e-5 nm from "%.6f" oxDNA-unit precision).
        assert mean_dz == pytest.approx(expected_shift_nm, abs=0.05), (
            f"Axial Δz expected ≈ {expected_shift_nm:.3f} nm, got {mean_dz:.4f}"
        )

    def test_smoothing_path_propagates_axial_shift(self, tmp_path: Path):
        """Same axial shift but through the sigma=2 Gaussian-smoothing path.
        mode='nearest' boundary handling preserves a uniform translation."""
        from backend.core.constants import OXDNA_LENGTH_UNIT

        design = _small_design()
        conf_a = tmp_path / "a.dat"
        conf_b = tmp_path / "b.dat"
        _write_synthetic_conf(design, conf_a)

        shift_oxdna = 3.0
        new_lines: list[str] = []
        for line in conf_a.read_text().splitlines():
            if line.startswith(("t ", "b ", "E ")) or not line.strip():
                new_lines.append(line)
                continue
            parts = line.split()
            parts[2] = f"{float(parts[2]) + shift_oxdna:.6f}"
            new_lines.append("  ".join(parts))
        conf_b.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        model_a = build_atomistic_model_from_cg_spline(design, conf_a, sigma=2.0)
        model_b = build_atomistic_model_from_cg_spline(design, conf_b, sigma=2.0)
        zs_a = np.array([a.z for a in model_a.atoms])
        zs_b = np.array([a.z for a in model_b.atoms])
        mean_dz = float((zs_b - zs_a).mean())
        expected_shift_nm = shift_oxdna * OXDNA_LENGTH_UNIT
        assert mean_dz == pytest.approx(expected_shift_nm, abs=0.05), (
            f"sigma=2 path Δz expected ≈ {expected_shift_nm:.3f} nm, got {mean_dz:.4f}"
        )


# ── Constants reference (sanity) ─────────────────────────────────────────────


def test_oxdna_length_unit_round_trip_is_reciprocal():
    """Sanity guard: the conversion factor used by read_configuration
    (OXDNA_LENGTH_UNIT, 0.8518 nm) is the reciprocal of NM_TO_OXDNA used by
    write_configuration.  If this ever drifts, every test in this file
    silently corrupts."""
    from backend.core.constants import OXDNA_LENGTH_UNIT

    assert OXDNA_LENGTH_UNIT * NM_TO_OXDNA == pytest.approx(1.0, abs=1e-12)
