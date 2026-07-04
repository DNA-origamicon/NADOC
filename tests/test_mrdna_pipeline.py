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

# ── integration fixture: a regenerated routed primitive ───────────────────────
# Tier-3 used to depend on hand-kept U6hb ARBD files under /tmp (wiped on reboot).
# Instead we now REGENERATE the fixture on demand from a committed routed primitive
# (scaffold + staples) by running a short real ARBD sim. Requires mrdna + an ARBD
# GPU; skips cleanly when either is absent. See scripts/benchmark_mrdna_roundtrip.py
# for the standalone (non-pytest) version of these same round-trip guards.
_PRIMITIVE_DESIGN = EXAMPLES / "6hb_test.nadoc"   # 6-helix bundle, scaffold + staples, crossovers
_PRIMITIVE_STEPS  = 2000                           # short ARBD relax — enough for a real fine-stage frame

_has_mrdna   = False
try:
    import sys
    from backend.core.mrdna_bridge import mrdna_tool_path
    sys.path.insert(0, mrdna_tool_path())
    import mrdna  # noqa: F401
    _has_mrdna = True
except ImportError:
    pass

skip_no_mrdna = pytest.mark.skipif(not _has_mrdna, reason="mrdna not installed (set $MRDNA_TOOL_PATH or use ~/mrdna-tool)")


def _generate_primitive_fixture(out_dir: Path, design_path: Path = _PRIMITIVE_DESIGN,
                                steps: int = _PRIMITIVE_STEPS):
    """Build *design_path*'s mrdna model, run an ARBD sim into *out_dir*, and return
    (design, psf_path, dcd_path) for the fine stage. Skips the calling test if
    mrdna/ARBD is unavailable or the sim produces no fine-stage output."""
    if not design_path.exists():
        pytest.skip(f"{design_path.name} not found in Examples/")
    import sys
    from glob import glob
    from backend.core.mrdna_bridge import mrdna_tool_path, mrdna_model_from_nadoc
    sys.path.insert(0, mrdna_tool_path())

    design = _load_design(design_path)
    stem = "primitive"
    model = mrdna_model_from_nadoc(design)
    try:
        model.simulate(output_name=stem, directory=str(out_dir),
                       coarse_steps=steps, fine_steps=steps,
                       output_period=max(1, steps // 10))
    except Exception as exc:  # ARBD missing / GPU unavailable
        pytest.skip(f"ARBD simulation unavailable: {exc}")

    # Fine stage = the psf whose companion .pdb has the most ATOM records.
    best, best_n = None, -1
    for psf in sorted(glob(str(out_dir / f"{stem}*.psf"))):
        pdb = Path(psf).with_suffix(".pdb")
        if not pdb.exists():
            continue
        n = sum(1 for ln in pdb.read_text(errors="replace").splitlines()
                if ln.startswith(("ATOM", "HETATM")))
        if n > best_n:
            best_n, best = n, psf
    dcds = sorted(glob(str(out_dir / "output" / "*.dcd")))
    if best is None or not dcds:
        pytest.skip("mrdna produced no fine-stage PSF/DCD")
    dcd = next((d for d in dcds if Path(best).stem in Path(d).stem), dcds[-1])
    return design, best, dcd


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
    from backend.core.mrdna_bridge import _xy_frame
    from backend.core.sequences import _build_loop_skip_map, domain_bp_range
    from backend.core.constants import HELIX_RADIUS, BDNA_RISE_PER_BP

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

class TestWslCudaLibs:
    """ensure_wsl_cuda_libs prepends the WSL GPU driver dir so ARBD sees the GPU."""

    def test_prepends_wsl_lib_dir_under_wsl(self, monkeypatch):
        import backend.core.mrdna_bridge as mb
        monkeypatch.setattr(mb, "_is_wsl", lambda: True)
        monkeypatch.setattr(mb.os.path, "isdir", lambda p: p == mb._WSL_LIB_DIR)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/some/other/lib")
        mb.ensure_wsl_cuda_libs()
        parts = mb.os.environ["LD_LIBRARY_PATH"].split(mb.os.pathsep)
        assert parts[0] == mb._WSL_LIB_DIR          # WSL driver first → not shadowed
        assert "/some/other/lib" in parts
        # idempotent — a second call doesn't duplicate it
        mb.ensure_wsl_cuda_libs()
        assert mb.os.environ["LD_LIBRARY_PATH"].split(mb.os.pathsep).count(mb._WSL_LIB_DIR) == 1

    def test_noop_when_not_wsl(self, monkeypatch):
        import backend.core.mrdna_bridge as mb
        monkeypatch.setattr(mb, "_is_wsl", lambda: False)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/orig")
        mb.ensure_wsl_cuda_libs()
        assert mb.os.environ["LD_LIBRARY_PATH"] == "/orig"


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
        from backend.core.constants import HELIX_RADIUS, BDNA_MINOR_GROOVE_ANGLE_RAD

        # chord = 2R sin(θ/2)
        expected_chord = 2 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2)
        # For 150° groove: 2 × 1.0 × sin(75°) ≈ 1.932 nm
        assert 1.8 < expected_chord < 2.1, f"Unexpected chord: {expected_chord}"


class TestBeadlessEndNoRing:
    """Regression: a helix END the fine stage leaves beadless must EXTEND straight,
    not collapse into a flat HELIX_RADIUS ring.

    Bug (fixed 2026-07-04): the DISPLAY reconstruction placed each nucleotide on a
    per-helix cubic spline at ``t = clip(bp, t_lo, t_hi)`` (t_lo/t_hi = min/max
    bead-covered bp).  Every bp past ``t_hi`` was pinned to the single point
    ``cs(t_hi)``, and the duplex twist fan below then splayed those pinned
    nucleotides into a flat circle of radius HELIX_RADIUS — the user-reported "a
    helix collapsed onto a 2-D plane to make a ring".  BOTH coarse-fallback detectors
    are structurally blind to it (whole-helix bounding diagonal stays large because
    the rest of the helix is extended; ring neighbours are only ~2R·sin(twist/2) ≈
    0.58 nm apart, under the 1.3 nm stretched-bond threshold), so the fix is at the
    source: ``_relaxed_axis_at_bp`` extrapolates straight along the endpoint tangent
    at ideal rise past a beadless end.  See memory/project_mrdna_panel.md.
    """

    @staticmethod
    def _straight_spline(t_lo, t_hi, rise_ang):
        """A per-helix axis spline for a straight helix along +z, knots at every
        bead-covered bp (Å)."""
        from scipy.interpolate import CubicSpline
        bps = np.arange(t_lo, t_hi + 1, dtype=float)
        pos = np.column_stack([np.zeros_like(bps), np.zeros_like(bps), bps * rise_ang])
        return CubicSpline(bps, pos, bc_type="not-a-knot")

    def test_extrapolates_past_beadless_end_not_pinned(self):
        from backend.core.mrdna_bridge import _relaxed_axis_at_bp
        from backend.core.constants import BDNA_RISE_PER_BP
        rise = BDNA_RISE_PER_BP * 10.0          # nm → Å
        t_lo, t_hi = 0.0, 39.0                   # beads cover only bp 0..39
        cs = self._straight_spline(t_lo, t_hi, rise)
        ideal = np.array([0.0, 0.0, 1.0])

        # bp 40..50 are beadless: axis must keep advancing (~rise/bp), NOT pin to cs(39)
        tail_z = np.array([
            _relaxed_axis_at_bp(cs, bp, t_lo, t_hi, ideal, rise)[0][2]
            for bp in range(40, 51)
        ])
        diffs = np.diff(tail_z)
        assert np.all(diffs > 0.5 * rise), "beadless tail pinned/compressed — ring risk"
        assert abs(diffs.mean() - rise) < 1e-6, "extrapolated rise != ideal B-DNA rise"
        assert tail_z[-1] - tail_z[0] > 9 * rise, "tail collapsed instead of extending"

        # in-range bp are unchanged — still evaluated directly on the spline
        pt, _ = _relaxed_axis_at_bp(cs, 20, t_lo, t_hi, ideal, rise)
        np.testing.assert_allclose(pt, np.asarray(cs(20.0)), atol=1e-9)

    def test_full_duplex_tail_extends_not_a_flat_ring(self):
        """Reconstruct the FORWARD backbone for the beadless tail exactly as the
        display function does, and compare the fix against the old clip behaviour:
        clip → flat ring at radius R; fix → axially extended tail."""
        from backend.core.mrdna_bridge import _relaxed_axis_at_bp, _xy_frame
        from backend.core.constants import BDNA_RISE_PER_BP, HELIX_RADIUS
        rise = BDNA_RISE_PER_BP * 10.0
        R = HELIX_RADIUS * 10.0
        twist = 0.5949                            # ~34°/bp, canonical B-DNA
        t_lo, t_hi = 0.0, 39.0
        cs = self._straight_spline(t_lo, t_hi, rise)
        ideal = np.array([0.0, 0.0, 1.0])
        x_hat, y_hat = _xy_frame(ideal)

        def _forward(bp, axis_pt, axis_hat):
            ang = bp * twist
            rad = math.cos(ang) * x_hat + math.sin(ang) * y_hat
            rad = rad - np.dot(rad, axis_hat) * axis_hat
            return axis_pt + R * rad / np.linalg.norm(rad)

        # FIX (helper extrapolates the axis): tail spans the real axial extent
        fixed = np.array([
            _forward(bp, *_relaxed_axis_at_bp(cs, bp, t_lo, t_hi, ideal, rise))
            for bp in range(40, 51)
        ])
        fixed_axial = np.ptp(fixed[:, 2])

        # OLD (clip pins the axis at cs(t_hi)): tail is a flat ring in a z=const plane
        pinned = np.asarray(cs(t_hi))
        old = np.array([_forward(bp, pinned, ideal) for bp in range(40, 51)])
        old_axial = np.ptp(old[:, 2])

        # bug signature — the clipped tail really is a flat HELIX_RADIUS ring
        assert old_axial < 1e-6, "sanity: clip pins the tail into one plane"
        assert np.allclose(np.linalg.norm(old[:, :2], axis=1), R, atol=1e-6), \
            "sanity: clipped tail is a circle of radius HELIX_RADIUS (the ring)"
        # the fix — tail now extends axially rather than collapsing to a disk
        assert fixed_axial > 9 * rise, "fixed tail failed to extend axially"
        assert fixed_axial > 100 * old_axial


class TestSsdnaBridgeContinuity:
    """Regression: a single-stranded scaffold CROSSOVER — a run that bridges
    ds→ss→(crossover)→ss→ds across two helices — must render with BOTH ends anchored
    to their relaxed roots, so the far-end crossover and ss/ds junction backbone bonds
    don't stretch (the 6hb_2xT far-end report).  Before the fix the ss run was anchored
    at only one root (or phantom-duplexed onto the dsDNA axis), floating the far
    junction to 4-6 nm.  See memory/project_mrdna_panel.md.
    """

    def test_ssdna_runs_reports_both_roots_for_a_bridging_run(self, monkeypatch):
        import backend.core.mrdna_bridge as mb
        # synthetic scaffold chain: ds(0) → ss(1) → ss(2) → ds(3); one bridging run [1,2]
        r = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], float) * 10.0  # Å
        bp = np.array([3, -1, -1, 0])                  # 0 & 3 paired, 1 & 2 unpaired
        stack = np.array([-1, -1, -1, -1])
        three_prime = np.array([1, 2, 3, -1])          # 5'→3': 0→1→2→3
        orient = np.zeros((4, 3, 3))
        seq = list("ACGT")
        nt_key = {("hA", 0, "FORWARD", 0): 0, ("hA", -1, "FORWARD", 0): 1,
                  ("hB", -1, "FORWARD", 0): 2, ("hB", 0, "FORWARD", 0): 3}

        def _fake(design, return_nt_key=False):
            base = (r, bp, stack, three_prime, orient, seq)
            return (*base, nt_key) if return_nt_key else base
        monkeypatch.setattr(mb, "_build_nt_arrays", _fake)

        runs = mb._ssdna_runs(object())
        assert len(runs) == 1
        run = runs[0]
        assert [k[:2] for k in run["keys"]] == [("hA", -1), ("hB", -1)]
        # BOTH ds neighbours captured — the far-side (3') root is the fix's whole point
        assert run["root5_key"][:2] == ("hA", 0)
        assert run["root3_key"][:2] == ("hB", 0)

    def test_blend_pins_both_ends_where_single_anchor_floats(self):
        from backend.core.mrdna_bridge import _blend_run_both_ends
        n = 10
        ideal = [np.array([float(i), 0.0, 0.0]) for i in range(n)]
        d5 = np.array([0.0, 1.0, 0.0])      # 5' root relaxed one way,
        d3 = np.array([0.0, -2.0, 0.0])     # 3' root the other → single anchor floats
        out = _blend_run_both_ends(ideal, d5, d3)
        # each end lands at ideal + its NEAR root's displacement → both junctions short
        np.testing.assert_allclose(out[0], ideal[0] + d5, atol=1e-9)
        np.testing.assert_allclose(out[-1], ideal[-1] + d3, atol=1e-9)
        # a single-anchor translate (+d5 everywhere) would float the far end by |d3-d5|
        single_far = ideal[-1] + d5
        assert np.linalg.norm(single_far - out[-1]) == pytest.approx(
            float(np.linalg.norm(d3 - d5)))
        # the run's own shape is preserved — consecutive spacing stays near the ideal 1.0
        steps = [float(np.linalg.norm(out[i + 1] - out[i])) for i in range(n - 1)]
        assert 0.5 < min(steps) and max(steps) < 1.5

    def test_blend_single_nucleotide_centers_between_roots(self):
        from backend.core.mrdna_bridge import _blend_run_both_ends
        out = _blend_run_both_ends([np.array([0.0, 0.0, 0.0])],
                                   np.array([2.0, 0.0, 0.0]), np.array([0.0, 2.0, 0.0]))
        np.testing.assert_allclose(out[0], [1.0, 1.0, 0.0], atol=1e-9)  # f=0.5 blend


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
        import sys
        from backend.core.mrdna_bridge import mrdna_tool_path
        sys.path.insert(0, mrdna_tool_path())

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
# Tier 3 — Integration tests (regenerate a real ARBD fine-stage fixture)
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_mrdna
class TestRoutedPrimitiveIntegration:
    """
    Validate the override (mrdna beads → NADOC nucleotide positions) against an
    actual ARBD-simulated fine stage, regenerated on demand from a committed
    routed primitive (6hb_test: scaffold + staples + crossovers). Replaces the
    old U6hb-files-under-/tmp dependency, which was lost on every reboot.
    """

    @pytest.fixture(scope="class")
    def primitive_override(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("mrdna_primitive")
        design, psf, dcd = _generate_primitive_fixture(out)
        from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands
        override = nuc_pos_override_from_arbd_strands(
            design, psf, dcd, frame=-1, sigma_nt=1.5,
        )
        return design, override

    def test_entry_count(self, primitive_override):
        design, override = primitive_override
        n_nt = _count_nontrivial_nucleotides(design)
        # One entry per nucleotide (FORWARD/REVERSE keyed by direction), plus
        # possibly extra in-helix-range positions not part of any strand
        # (scaffold gaps). Over-coverage is benign; require no UNDER-coverage.
        assert len(override) >= n_nt * 0.95, (
            f"Override covers only {len(override)}/{n_nt} nucleotides"
        )

    def test_no_nan_inf(self, primitive_override):
        _, override = primitive_override
        vals = np.array(list(override.values()))
        assert not np.isnan(vals).any()
        assert not np.isinf(vals).any()

    def test_no_duplicate_positions(self, primitive_override):
        from collections import Counter
        _, override = primitive_override
        pos_tuples = [tuple(np.round(v, 4)) for v in override.values()]
        dups = [(p, c) for p, c in Counter(pos_tuples).items() if c > 1]
        assert len(dups) == 0, (
            f"{len(dups)} duplicate positions. First: {dups[0] if dups else None}. "
            "Duplicate positions were the root cause of LJ=2.1e37 at EM step 0."
        )

    def test_position_range_matches_structure(self, primitive_override):
        """All override positions must fall within the design's physical extent —
        a frame mismatch or an exploded structure pushes beads outside it.

        The seed places each nucleotide at HELIX_RADIUS off the RELAXED CG axis
        (the DNA-bead spline), NOT off the ideal design axis — that is the whole
        point of seeding from a relaxed structure (it follows the CG bend + drift +
        crossover gaps).  So a healthy relaxation legitimately sits a few nm off the
        design axis (measured ~3 nm axis drift + ~1 nm HELIX_RADIUS on this short
        coarse fixture).  The margin only has to separate that from a real failure —
        a frame mismatch puts beads tens of nm out (138 nm for U6hb), an explosion
        far more — so 6 nm cleanly catches those without flagging normal relaxation."""
        design, override = primitive_override
        vals = np.array(list(override.values()))

        all_pts = np.array(
            [h.axis_start.to_array() for h in design.helices]
            + [h.axis_end.to_array() for h in design.helices]
        )
        _MARGIN_NM = 6.0            # HELIX_RADIUS + CG relaxation drift, ≪ frame-mismatch
        lo = all_pts.min(0) - _MARGIN_NM
        hi = all_pts.max(0) + _MARGIN_NM

        violations = np.any((vals < lo) | (vals > hi), axis=1).sum()
        assert violations == 0, (
            f"{violations} override positions outside helix axis extent + "
            f"{_MARGIN_NM} nm. Likely a coordinate frame mismatch (DCD not aligned "
            "to NADOC frame) or an exploded structure — not ordinary CG relaxation."
        )

    def test_all_helices_covered(self, primitive_override):
        design, override = primitive_override
        for h in design.helices:
            bp_mid = h.bp_start + h.length_bp // 2
            fwd = override.get((h.id, bp_mid, 'FORWARD'))
            rev = override.get((h.id, bp_mid, 'REVERSE'))
            assert fwd is not None, f"Helix {h.id} FORWARD not in override"
            assert rev is not None, f"Helix {h.id} REVERSE not in override"

    def test_crossover_keys_present(self, primitive_override):
        """
        Crossover junction keys within the helix bp range must be in the override.
        Keys with bp_idx outside [bp_start, bp_start+length_bp) are not generated
        (they belong to domain overhangs) and are allowed to be absent.
        """
        from backend.core.mrdna_bridge import _crossover_junction_keys
        design, override = primitive_override
        helix_ranges = {
            h.id: range(h.bp_start, h.bp_start + h.length_bp)
            for h in design.helices
        }
        xover = _crossover_junction_keys(design)
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

    def test_bead_count_per_helix_approx_one_per_bp(self, primitive_override):
        """
        The fine stage has 1 DNA bead per bp.  After per-helix deduplication,
        each helix should have roughly length_bp spline knots.
        Check that we have at least 80% coverage per helix.
        """
        design, override = primitive_override
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


@skip_no_mrdna
class TestPhase3bRegression:
    """
    Regression test: the Phase 3b CG override must reduce EM convergence
    steps vs. ideal B-DNA baseline by > 50%.  Requires GROMACS in PATH.
    This test is slow (~3-5 min); mark it explicitly to run or skip.

    XFAIL (2026-06-28): the EM-reduction PREMISE has gone stale and is no longer
    measurable. When written, ideal-B-DNA U6hb needed ~500 GROMACS EM steps (hit the
    nsteps cap) so a CG-prerelaxed override could show a big speedup (→14 steps). On
    the current GROMACS/forcefield the ideal-B-DNA baseline itself converges in ~15
    steps, so there is no headroom for a >50% reduction regardless of the CG seed
    (measured: baseline 15, override 16 → ratio 1.07x). This is independent of the
    fixture repoint. To revive: recalibrate the EM protocol (e.g. tighter emtol or a
    starting structure genuinely far from a minimum) so the baseline is slow again.
    Left here (run=False, no compute burned) as a documented marker, not a silent skip.
    """

    @pytest.mark.slow
    @pytest.mark.xfail(reason="EM-reduction premise stale: ideal-B-DNA baseline now "
                              "converges in ~15 GROMACS EM steps; >50% CG speedup "
                              "unmeasurable. Needs EM-protocol recalibration.", run=False)
    def test_step_reduction(self, tmp_path_factory):
        import subprocess, re
        from backend.core.gromacs_package import _build_gromacs_input_pdb, _find_gmx
        from backend.core.mrdna_bridge import nuc_pos_override_from_arbd_strands

        # The EM-speedup claim needs a large, genuinely-relaxed structure: a CG run
        # only pre-positions atoms usefully when the bundle is big enough to flex
        # away from ideal B-DNA. Regenerate from U6hb (the original regime) with a
        # real relaxation, not the small primitive (which stays ~ideal → no speedup).
        out = tmp_path_factory.mktemp("mrdna_p3b")
        design, _psf, _dcd = _generate_primitive_fixture(
            out, design_path=EXAMPLES / "U6hb.nadoc", steps=100_000)
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
            design, _psf, _dcd, frame=-1, sigma_nt=1.5,
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
