"""
Unit and integration tests for the mrdna CG→atomistic pipeline.

Organised in three tiers:

  Tier 1 — Pure unit tests
    No mrdna, no ARBD, no MDAnalysis.  Tests internal helpers and the
    geometry assumptions that the override function relies on.

  Tier 2 — Synthetic round-trip tests  (require mrdna + MDAnalysis)
    Generate the mrdna initial fine-stage PDB for a small design, then
    use that PDB as both the "init" and the "DCD" (zero-step round-trip).
    The override should reproduce ideal B-DNA positions to within spline
    interpolation error (~0.1–0.2 nm).

  Tier 3 — Integration tests  (require U6hb PSF/DCD at /tmp)
    Validate against the actual ARBD-simulated U6hb fine stage.  These
    tests are skipped automatically when the fixture files are absent.

Key insight tested throughout:
  mrdna fine stage has 1 DNA bead per BASE PAIR (not per nucleotide).
  The DNA bead sits at the FORWARD backbone position.  There is no
  separate REVERSE bead.  Direction assignment per-bead is wrong and
  produces duplicate positions → LJ overflow at EM step 0.
  See memory/project_mrdna_bead_model.md for the full explanation.

Usage:
    pytest tests/test_mrdna_pipeline.py -v
    pytest tests/test_mrdna_pipeline.py -v -m "not integration"
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "Examples"

# ── fixture paths ─────────────────────────────────────────────────────────────
# Integration tests use the U6hb ARBD fine-stage files produced by a prior run.
# Skip automatically when absent.
_U6HB_DIR   = Path("/tmp/mrdna_u6hb_rerun")
_U6HB_STEM  = "u6hb_loop_fix"
_U6HB_STAGE = 2
_U6HB_PSF   = _U6HB_DIR / f"{_U6HB_STEM}-{_U6HB_STAGE}.psf"
_U6HB_PDB   = _U6HB_DIR / f"{_U6HB_STEM}-{_U6HB_STAGE}.pdb"
_U6HB_DCD   = _U6HB_DIR / "output" / f"{_U6HB_STEM}-{_U6HB_STAGE}.dcd"
_U6HB_DESIGN = EXAMPLES / "U6hb.nadoc"

_has_u6hb    = _U6HB_PSF.exists() and _U6HB_DCD.exists() and _U6HB_PDB.exists()
_has_mrdna   = False
try:
    import sys
    sys.path.insert(0, "/tmp/mrdna-tool")
    import mrdna  # noqa: F401
    _has_mrdna = True
except ImportError:
    pass

skip_no_u6hb  = pytest.mark.skipif(not _has_u6hb,  reason="U6hb PSF/DCD not found at /tmp")
skip_no_mrdna = pytest.mark.skipif(not _has_mrdna, reason="mrdna not installed at /tmp/mrdna-tool")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_design(path: Path):
    import sys; sys.path.insert(0, str(ROOT))
    from backend.core.models import Design
    return Design.model_validate_json(path.read_text())


def _count_nontrivial_nucleotides(design) -> int:
    """Total nucleotides excluding skip sites (loop_skip delta <= -1)."""
    from backend.core.sequences import _build_loop_skip_map, domain_bp_range
    ls = _build_loop_skip_map(design)
    count = 0
    for strand in design.strands:
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                if ls.get((domain.helix_id, bp), 0) > -1:
                    count += 1
    return count


def _ideal_positions(design) -> "dict[tuple, np.ndarray]":
    """Return ideal B-DNA positions for all nucleotides as an override-shaped dict."""
    from backend.core.mrdna_bridge import _build_nt_arrays, _xy_frame
    from backend.core.sequences import _build_loop_skip_map, domain_bp_range
    from backend.core.constants import HELIX_RADIUS, BDNA_RISE_PER_BP
    import math

    ls = _build_loop_skip_map(design)
    result: dict[tuple, np.ndarray] = {}
    for strand in design.strands:
        for domain in strand.domains:
            h = next(h for h in design.helices if h.id == domain.helix_id)
            ax_s = h.axis_start.to_array()
            ax_e = h.axis_end.to_array()
            v = ax_e - ax_s
            axis_hat = v / np.linalg.norm(v)
            x_hat, y_hat = _xy_frame(axis_hat)
            for bp_idx in domain_bp_range(domain):
                if ls.get((domain.helix_id, bp_idx), 0) <= -1:
                    continue
                local_i = bp_idx - h.bp_start
                fwd_angle = h.phase_offset + local_i * h.twist_per_bp_rad
                if domain.direction.value == 'FORWARD':
                    angle = fwd_angle
                else:
                    from backend.core.constants import BDNA_MINOR_GROOVE_ANGLE_RAD
                    angle = fwd_angle + BDNA_MINOR_GROOVE_ANGLE_RAD
                rad = math.cos(angle) * x_hat + math.sin(angle) * y_hat
                axis_pt = ax_s + local_i * BDNA_RISE_PER_BP * axis_hat
                pos = axis_pt + HELIX_RADIUS * rad
                result[(domain.helix_id, bp_idx, domain.direction.value)] = pos
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — Pure geometry unit tests (no external tools required)
# ─────────────────────────────────────────────────────────────────────────────

class TestInternalHelpers:
    """_xy_frame and _rotate helpers used throughout the override function."""

    def test_xy_frame_orthogonal_to_axis(self):
        from backend.core.mrdna_bridge import _xy_frame
        for axis in [
            np.array([0., 0., 1.]),
            np.array([1., 0., 0.]),
            np.array([0., 1., 0.]),
            np.array([1., 1., 1.]) / np.sqrt(3),
        ]:
            x, y = _xy_frame(axis)
            assert abs(np.dot(x, axis)) < 1e-10, "x_hat not perpendicular to axis"
            assert abs(np.dot(y, axis)) < 1e-10, "y_hat not perpendicular to axis"
            assert abs(np.dot(x, y))    < 1e-10, "x_hat not perpendicular to y_hat"
            assert abs(np.linalg.norm(x) - 1) < 1e-10
            assert abs(np.linalg.norm(y) - 1) < 1e-10

    def test_xy_frame_cached(self):
        from backend.core.mrdna_bridge import _xy_frame
        axis = np.array([0., 0., 1.])
        x1, y1 = _xy_frame(axis)
        x2, y2 = _xy_frame(axis.copy())
        np.testing.assert_array_equal(x1, x2)
        np.testing.assert_array_equal(y1, y2)

    def test_rotate_preserves_length(self):
        """Rodrigues rotation should preserve vector magnitude."""
        from backend.core.mrdna_bridge import _xy_frame
        import math

        def _rotate(v, axis, angle):
            c, s = math.cos(angle), math.sin(angle)
            return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1 - c)

        axis = np.array([0., 0., 1.])
        v    = np.array([1., 0., 0.])
        for angle in [0, math.pi / 6, math.pi / 2, math.pi, 2 * math.pi]:
            rv = _rotate(v, axis, angle)
            assert abs(np.linalg.norm(rv) - 1) < 1e-10

    def test_minor_groove_separation(self):
        """FORWARD and REVERSE for the same bp should be ~HELIX_RADIUS*1.73 nm apart."""
        import math
        from backend.core.constants import HELIX_RADIUS, BDNA_MINOR_GROOVE_ANGLE_RAD

        # chord = 2R sin(θ/2)
        expected_chord = 2 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2)
        # For 150° groove: 2 × 1.0 × sin(75°) ≈ 1.932 nm
        assert 1.8 < expected_chord < 2.1, f"Unexpected chord: {expected_chord}"


class TestDesignGeometry:
    """Verify design-level geometric invariants used by the override function."""

    @pytest.fixture(scope="class")
    def small_design(self):
        path = EXAMPLES / "2hb_xover_val.nadoc"
        if not path.exists():
            pytest.skip("2hb_xover_val.nadoc not found in Examples/")
        return _load_design(path)

    def test_all_helices_have_nonzero_length(self, small_design):
        for h in small_design.helices:
            assert h.length_bp > 0, f"Helix {h.id} has zero length"

    def test_axis_hat_is_unit_vector(self, small_design):
        for h in small_design.helices:
            ax = h.axis_end.to_array() - h.axis_start.to_array()
            assert abs(np.linalg.norm(ax) - 1) > 1e-3, "axis start≈end"
            ax_hat = ax / np.linalg.norm(ax)
            assert abs(np.linalg.norm(ax_hat) - 1) < 1e-10

    def test_ideal_positions_no_nan(self, small_design):
        pos = _ideal_positions(small_design)
        vals = np.array(list(pos.values()))
        assert not np.isnan(vals).any()
        assert not np.isinf(vals).any()

    def test_ideal_positions_count(self, small_design):
        pos    = _ideal_positions(small_design)
        n_nt   = _count_nontrivial_nucleotides(small_design)
        assert len(pos) == n_nt, f"Expected {n_nt} positions, got {len(pos)}"


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — Synthetic round-trip tests (require mrdna + MDAnalysis)
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_mrdna
class TestSyntheticRoundTrip:
    """
    Zero-step round-trip: generate mrdna initial fine-stage PDB for a small
    design, then use that PDB as both the 'init' and the 'DCD' (no ARBD run).
    The override must reproduce ideal B-DNA positions to within spline
    interpolation error (tolerance ≤ 0.25 nm per nucleotide, mean ≤ 0.10 nm).
    """

    @pytest.fixture(scope="class")
    def roundtrip_fixture(self):
        """
        Build mrdna model, save initial PDB to a temp dir, return
        (design, override, ideal_positions).
        Uses 2hb_xover_val.nadoc (small: ~2 helices, ~100 bp, fast mrdna init).
        """
        import MDAnalysis as mda
        import sys
        sys.path.insert(0, "/tmp/mrdna-tool")

        design_path = EXAMPLES / "2hb_xover_val.nadoc"
        if not design_path.exists():
            pytest.skip("2hb_xover_val.nadoc not found in Examples/")

        design = _load_design(design_path)

        from backend.core.mrdna_bridge import mrdna_model_from_nadoc, nuc_pos_override_from_arbd_strands

        with tempfile.TemporaryDirectory(prefix="nadoc_test_mrdna_") as d:
            tmpdir = Path(d)
            stem   = "test_design"

            # simulate(output_name, directory) writes:
            #   stem-0.psf, stem-0.pdb  (coarse)
            #   stem-1.psf, stem-1.pdb  (intermediate fine)
            #   stem-2.psf, stem-2.pdb  (fine)
            model = mrdna_model_from_nadoc(design)
            model.simulate(output_name=stem, directory=str(tmpdir),
                           run_coarse=False, run_fine=True,
                           num_steps_fine=[0])   # 0 ARBD steps → init PDB only

            psf = tmpdir / f"{stem}-2.psf"
            pdb = tmpdir / f"{stem}-2.pdb"

            if not psf.exists() or not pdb.exists():
                pytest.skip("mrdna did not produce fine-stage PSF/PDB")

            # Use the initial PDB as the 'DCD' (zero-step round-trip)
            override = nuc_pos_override_from_arbd_strands(
                design, str(psf), str(pdb), frame=0, sigma_nt=0.0,
            )
            ideal    = _ideal_positions(design)

        return design, override, ideal

    def test_full_coverage(self, roundtrip_fixture):
        """Every non-skip nucleotide must have an override entry."""
        design, override, ideal = roundtrip_fixture
        n_nt = _count_nontrivial_nucleotides(design)
        assert len(override) >= n_nt * 0.95, (
            f"Override covers only {len(override)}/{n_nt} nucleotides"
        )

    def test_no_nan_inf(self, roundtrip_fixture):
        _, override, _ = roundtrip_fixture
        vals = np.array(list(override.values()))
        assert not np.isnan(vals).any(), "NaN in override positions"
        assert not np.isinf(vals).any(), "Inf in override positions"

    def test_no_duplicate_positions(self, roundtrip_fixture):
        """Duplicate positions caused the original LJ=2e37 failure."""
        from collections import Counter
        _, override, _ = roundtrip_fixture
        pos_tuples = [tuple(np.round(v, 4)) for v in override.values()]
        dups = [(p, c) for p, c in Counter(pos_tuples).items() if c > 1]
        assert len(dups) == 0, (
            f"{len(dups)} duplicate positions found. "
            f"First: {dups[0] if dups else None}\n"
            "This is the root cause of LJ=2e37 at EM step 0."
        )

    def test_zero_step_position_accuracy(self, roundtrip_fixture):
        """
        With 0 ARBD steps (sigma_nt=0), override positions must be within
        0.25 nm of ideal B-DNA positions (spline interpolation error only).
        """
        _, override, ideal = roundtrip_fixture
        errors = []
        for key, ideal_pos in ideal.items():
            if key in override:
                errors.append(np.linalg.norm(override[key] - ideal_pos))

        assert len(errors) > 0, "No overlapping keys between override and ideal"
        mean_err = np.mean(errors)
        max_err  = np.max(errors)
        assert mean_err < 0.10, f"Mean position error {mean_err:.3f} nm > 0.10 nm"
        assert max_err  < 0.25, f"Max position error {max_err:.3f} nm > 0.25 nm"

    def test_forward_reverse_separation(self, roundtrip_fixture):
        """
        FORWARD and REVERSE override positions for the same bp must be
        separated by 2R sin(groove/2) ± 0.3 nm.
        """
        import math
        from backend.core.constants import HELIX_RADIUS, BDNA_MINOR_GROOVE_ANGLE_RAD
        design, override, _ = roundtrip_fixture

        expected = 2 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2)
        errors: list[float] = []

        for h in design.helices:
            for bp_idx in range(h.bp_start, h.bp_start + h.length_bp):
                fwd = override.get((h.id, bp_idx, 'FORWARD'))
                rev = override.get((h.id, bp_idx, 'REVERSE'))
                if fwd is not None and rev is not None:
                    errors.append(abs(np.linalg.norm(fwd - rev) - expected))

        assert len(errors) > 0, "No FORWARD/REVERSE pairs found"
        mean_err = np.mean(errors)
        assert mean_err < 0.05, (
            f"Mean FWD-REV separation error {mean_err:.4f} nm > 0.05 nm"
        )

    def test_sequential_backbone_distance(self, roundtrip_fixture):
        """
        Consecutive nucleotides within the same helix domain must be
        within 1.0 nm (ideal B-DNA backbone is ~0.6 nm P–P distance).
        """
        from backend.core.sequences import _build_loop_skip_map, domain_bp_range
        design, override, _ = roundtrip_fixture
        ls = _build_loop_skip_map(design)
        violations: list[tuple] = []

        for strand in design.strands:
            for domain in strand.domains:
                prev_pos: Optional[np.ndarray] = None
                for bp_idx in domain_bp_range(domain):
                    if ls.get((domain.helix_id, bp_idx), 0) <= -1:
                        continue
                    key = (domain.helix_id, bp_idx, domain.direction.value)
                    pos = override.get(key)
                    if pos is not None and prev_pos is not None:
                        d = np.linalg.norm(pos - prev_pos)
                        if d > 1.0:
                            violations.append((key, d))
                    if pos is not None:
                        prev_pos = pos

        assert len(violations) == 0, (
            f"{len(violations)} backbone distance violations > 1.0 nm: "
            f"{violations[:3]}"
        )

    def test_crossover_keys_included(self, roundtrip_fixture):
        """
        Crossover terminal bp must have override entries.
        This is the primary improvement over nuc_pos_override_from_mrdna.
        """
        from backend.core.mrdna_bridge import _crossover_junction_keys
        design, override, _ = roundtrip_fixture

        xover_keys = _crossover_junction_keys(design)
        if len(xover_keys) == 0:
            pytest.skip("Design has no crossovers")

        covered = sum(1 for k in xover_keys if k in override)
        assert covered == len(xover_keys), (
            f"Only {covered}/{len(xover_keys)} crossover keys covered. "
            "nuc_pos_override_from_arbd_strands should include ALL crossover keys."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — Integration tests (require U6hb PSF/DCD at /tmp)
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_u6hb
class TestU6hbIntegration:
    """
    Validate the override function against the actual ARBD-simulated U6hb
    fine-stage output.  These run directly against the kept files from
    validate_phase3b.py --keep.
    """

    @pytest.fixture(scope="class")
    def u6hb_override(self):
        design = _load_design(_U6HB_DESIGN)
        from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands
        return design, nuc_pos_override_from_arbd_strands(
            design, str(_U6HB_PSF), str(_U6HB_DCD), frame=-1, sigma_nt=1.5,
        )

    def test_entry_count(self, u6hb_override):
        design, override = u6hb_override
        n_nt = _count_nontrivial_nucleotides(design)
        # override has one entry per nucleotide (FORWARD or REVERSE keyed by direction).
        # It can also include extra positions for bp within helix range but not part of
        # any strand (scaffold gaps), so allow ±5%.
        assert abs(len(override) - n_nt) < n_nt * 0.05, (
            f"Expected ~{n_nt} override entries (one per nucleotide), got {len(override)}"
        )

    def test_no_nan_inf(self, u6hb_override):
        _, override = u6hb_override
        vals = np.array(list(override.values()))
        assert not np.isnan(vals).any()
        assert not np.isinf(vals).any()

    def test_no_duplicate_positions(self, u6hb_override):
        from collections import Counter
        _, override = u6hb_override
        pos_tuples = [tuple(np.round(v, 4)) for v in override.values()]
        dups = [(p, c) for p, c in Counter(pos_tuples).items() if c > 1]
        assert len(dups) == 0, (
            f"{len(dups)} duplicate positions. First: {dups[0] if dups else None}. "
            "This was the root cause of LJ=2.1e37 at Phase 3b step 0."
        )

    def test_position_range_matches_structure(self, u6hb_override):
        """
        U6hb is ~139 nm tall (6 parallel helices each ~2518 bp × 0.034 nm/bp).
        All override positions must fall within the physical extent of the design.
        """
        design, override = u6hb_override
        vals = np.array(list(override.values()))

        # Helix axis extent from NADOC geometry
        all_pts = np.array(
            [h.axis_start.to_array() for h in design.helices]
            + [h.axis_end.to_array() for h in design.helices]
        )
        lo = all_pts.min(0) - 2.0   # 2 nm margin (HELIX_RADIUS + some)
        hi = all_pts.max(0) + 2.0

        violations = np.any((vals < lo) | (vals > hi), axis=1).sum()
        assert violations == 0, (
            f"{violations} override positions outside helix axis extent. "
            "Likely a coordinate frame mismatch (DCD not aligned to NADOC frame)."
        )

    def test_all_helices_covered(self, u6hb_override):
        design, override = u6hb_override
        for h in design.helices:
            bp_mid = h.bp_start + h.length_bp // 2
            fwd = override.get((h.id, bp_mid, 'FORWARD'))
            rev = override.get((h.id, bp_mid, 'REVERSE'))
            assert fwd is not None, f"Helix {h.id} FORWARD not in override"
            assert rev is not None, f"Helix {h.id} REVERSE not in override"

    def test_crossover_keys_present(self, u6hb_override):
        """
        Crossover junction keys within the helix bp range must be in the override.
        Keys with bp_idx outside [bp_start, bp_start+length_bp) are not generated
        (they belong to domain overhangs) and are allowed to be absent.
        """
        from backend.core.mrdna_bridge import _crossover_junction_keys
        design, override = u6hb_override
        helix_ranges = {
            h.id: range(h.bp_start, h.bp_start + h.length_bp)
            for h in design.helices
        }
        xover = _crossover_junction_keys(design)
        # Only check keys whose bp_idx falls within the helix bp range
        in_range_keys = [
            k for k in xover
            if k[1] in helix_ranges.get(k[0], range(0))
        ]
        missing = [k for k in in_range_keys if k not in override]
        assert len(missing) == 0, (
            f"{len(missing)}/{len(in_range_keys)} in-range crossover keys missing: "
            f"{missing[:5]}\n"
            "nuc_pos_override_from_arbd_strands should include all in-range crossover keys."
        )

    def test_bead_count_per_helix_approx_one_per_bp(self, u6hb_override):
        """
        The fine stage has 1 DNA bead per bp.  After per-helix deduplication,
        each helix should have roughly length_bp spline knots.
        Check that we have at least 80% coverage per helix.
        """
        design, override = u6hb_override
        for h in design.helices:
            covered = sum(
                1 for bp in range(h.bp_start, h.bp_start + h.length_bp)
                if (h.id, bp, 'FORWARD') in override
            )
            frac = covered / h.length_bp
            assert frac > 0.80, (
                f"Helix {h.id}: only {covered}/{h.length_bp} bp covered ({frac:.1%}). "
                "Bead assignment may be failing for this helix."
            )


@skip_no_u6hb
class TestPhase3bRegression:
    """
    Regression test: the Phase 3b CG override must reduce EM convergence
    steps vs. ideal B-DNA baseline by > 50%.  Requires GROMACS in PATH.
    This test is slow (~3-5 min); mark it explicitly to run or skip.
    """

    @pytest.mark.slow
    def test_step_reduction(self):
        import subprocess, re, time
        from backend.core.gromacs_package import _build_gromacs_input_pdb, _find_gmx
        from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands

        design = _load_design(_U6HB_DESIGN)
        gmx    = _find_gmx()
        ff     = "charmm36-feb2026_cgenff-5.0"

        _EM_MDP = (
            "integrator = steep\nnsteps = 500\nemtol = 1000.0\n"
            "emstep = 0.01\nnstxout = 0\nnstlog = 10\nnstenergy = 10\n"
            "coulombtype = PME\nrcoulomb = 1.0\nvdwtype = cut-off\n"
            "rvdw = 1.0\npbc = xyz\n"
        )

        def _run_em(pdb_text: str, label: str, tmpdir: Path) -> int:
            """Write PDB, run pdb2gmx+grompp+mdrun, return step count."""
            (tmpdir / "input.pdb").write_text(pdb_text)
            pdb_lines = [l for l in pdb_text.splitlines() if l.startswith(("ATOM", "HETATM"))]
            n_chains  = 1 + sum(1 for a, b in zip(pdb_lines, pdb_lines[1:]) if a[21] != b[21])

            r = subprocess.run(
                [gmx, "pdb2gmx", "-f", "input.pdb", "-o", "conf.gro", "-p", "topol.top",
                 "-ignh", "-ff", ff, "-water", "none", "-nobackup", "-ter"],
                input="4\n6\n" * n_chains,
                capture_output=True, text=True, cwd=tmpdir,
            )
            assert r.returncode == 0, f"pdb2gmx failed for {label}: {r.stderr[-500:]}"

            (tmpdir / "em.mdp").write_text(_EM_MDP)
            r = subprocess.run(
                [gmx, "grompp", "-f", "em.mdp", "-c", "conf.gro", "-p", "topol.top",
                 "-o", "em.tpr", "-maxwarn", "20", "-nobackup"],
                capture_output=True, text=True, cwd=tmpdir,
            )
            assert r.returncode == 0, f"grompp failed for {label}: {r.stderr[-500:]}"

            ntomp = max(1, int(subprocess.check_output(["nproc", "--all"]).strip()) - 4)
            subprocess.run(
                [gmx, "mdrun", "-v", "-ntmpi", "1", "-ntomp", str(ntomp),
                 "-nb", "gpu", "-deffnm", "em"],
                capture_output=True, text=True, cwd=tmpdir,
            )

            log = (tmpdir / "em.log").read_text(errors='replace')
            steps = re.findall(r'^\s*(\d+)\s+[-\d.e+]', log, re.MULTILINE)
            return int(steps[-1]) if steps else 0

        with tempfile.TemporaryDirectory(prefix="nadoc_p3b_test_baseline_") as d:
            baseline_steps = _run_em(
                _build_gromacs_input_pdb(design, ff=ff),
                "baseline", Path(d),
            )

        override = nuc_pos_override_from_arbd_strands(
            design, str(_U6HB_PSF), str(_U6HB_DCD), frame=-1, sigma_nt=1.5,
        )

        with tempfile.TemporaryDirectory(prefix="nadoc_p3b_test_spline_") as d:
            spline_steps = _run_em(
                _build_gromacs_input_pdb(design, ff=ff, nuc_pos_override=override),
                "phase3b", Path(d),
            )

        assert baseline_steps > 0,  "Baseline EM produced 0 steps — check GROMACS"
        assert spline_steps   > 0,  "Phase 3b EM produced 0 steps — check GROMACS"

        ratio = spline_steps / baseline_steps
        assert ratio < 0.50, (
            f"Phase 3b EM ratio {ratio:.2f}× — expected < 0.50×. "
            f"Baseline {baseline_steps} steps, Phase 3b {spline_steps} steps."
        )
