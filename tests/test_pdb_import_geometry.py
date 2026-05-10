"""
Pure-math helper tests for backend/core/pdb_import.py.

Coverage backfill (Refactor 06-A): exercises the seven deterministic geometry
helpers in pdb_import.py — _dihedral, fit_helix_axis, compute_nucleotide_frame,
sugar_pucker_phase, chi_angle, analyze_wc_pair, analyze_duplex.

Fixture strategy
----------------
* `_dihedral` and `fit_helix_axis` take only ndarrays — tested with hand-built
  geometry (collinear, perpendicular, axis-aligned stacks).
* The frame / pucker / chi / WC tests use `Residue` stubs assembled from the
  calibrated 1ZEW B-DNA atomistic templates already shipped in
  `backend.core.atomistic` (`_SUGAR`, `_DT_BASE`, `_DA_BASE`, …). These are the
  project's canonical B-DNA atom positions in the NADOC synthetic frame, so the
  expected numerical outputs are derived empirically from those same constants
  rather than from ideal-B-DNA literature values (see comments inline).
* `analyze_duplex` requires file I/O — a tiny 4-bp synthetic duplex PDB is
  generated from the same templates into a temporary file (no fixture file
  shipped).

These tests assert math callability, output shape, finiteness, orthonormality,
and self-consistent numeric ranges; they do not validate against external
crystallographic literature. The point is to lift `pdb_import.py` from 0%
coverage by exercising every branch of the 7 helpers' bodies.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.atomistic import (
    _DA_BASE,
    _DC_BASE,
    _DG_BASE,
    _DT_BASE,
    _SUGAR,
)
from backend.core.pdb_import import (
    PDBAtom,
    Residue,
    WCPairGeometry,
    _dihedral,
    analyze_duplex,
    analyze_wc_pair,
    chi_angle,
    compute_nucleotide_frame,
    fit_helix_axis,
    sugar_pucker_phase,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _residue_from_template(
    *,
    resName: str,
    sugar=_SUGAR,
    base=None,
    chainID: str = "A",
    resSeq: int = 1,
    rotate_z_rad: float = 0.0,
    translate_z_nm: float = 0.0,
    mirror_xy: bool = False,
) -> Residue:
    """Build a synthetic Residue from atomistic-template tuples.

    Optionally rotate around z (helix axis), translate along z (rise), and
    mirror across the helix axis (for the antiparallel-partner stub).
    """
    c, s = math.cos(rotate_z_rad), math.sin(rotate_z_rad)
    res = Residue(chainID=chainID, resSeq=resSeq, resName=resName)
    parts = list(sugar)
    if base is not None:
        parts += list(base)
    for name, elem, n, y, z in parts:
        if mirror_xy:
            n, y = -n, -y
        n_world = c * n - s * y
        y_world = s * n + c * y
        z_world = z + translate_z_nm
        res.atoms[name] = PDBAtom(
            serial=0,
            name=name,
            resName=resName,
            chainID=chainID,
            resSeq=resSeq,
            x=n_world,
            y=y_world,
            z=z_world,
            element=elem,
        )
    return res


# ── _dihedral ────────────────────────────────────────────────────────────────


class TestDihedral:
    def test_collinear_returns_zero(self):
        # Four points on the x-axis → cross products vanish → return 0.0 per
        # the explicit small-norm fallback in _dihedral.
        p1 = np.array([0.0, 0.0, 0.0])
        p2 = np.array([1.0, 0.0, 0.0])
        p3 = np.array([2.0, 0.0, 0.0])
        p4 = np.array([3.0, 0.0, 0.0])
        assert _dihedral(p1, p2, p3, p4) == 0.0

    def test_cis_zero_radians(self):
        # b1 and b3 anti-parallel-projected → cis → 0 rad
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 0.0, 0.0])
        p3 = np.array([0.0, 1.0, 0.0])
        p4 = np.array([1.0, 1.0, 0.0])
        assert math.isclose(_dihedral(p1, p2, p3, p4), 0.0, abs_tol=1e-9)

    def test_trans_pi_radians(self):
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 0.0, 0.0])
        p3 = np.array([0.0, 1.0, 0.0])
        p4 = np.array([-1.0, 1.0, 0.0])
        assert math.isclose(abs(_dihedral(p1, p2, p3, p4)), math.pi, abs_tol=1e-9)

    def test_perpendicular_planes_pi_over_two(self):
        # Hand-constructed +90° dihedral around the y-axis (b2 = +y).
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 0.0, 0.0])
        p3 = np.array([0.0, 1.0, 0.0])
        p4 = np.array([0.0, 1.0, 1.0])
        assert math.isclose(_dihedral(p1, p2, p3, p4), math.pi / 2, abs_tol=1e-9)

    def test_sign_convention_is_signed(self):
        """Dihedral is signed: flipping p4 across the b2 axis flips the sign."""
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([0.0, 0.0, 0.0])
        p3 = np.array([0.0, 1.0, 0.0])
        p4_pos = np.array([0.0, 1.0, 1.0])
        p4_neg = np.array([0.0, 1.0, -1.0])
        d_pos = _dihedral(p1, p2, p3, p4_pos)
        d_neg = _dihedral(p1, p2, p3, p4_neg)
        assert math.isclose(d_pos, -d_neg, abs_tol=1e-9)

    def test_returns_radians_in_pi_range(self):
        # Random non-degenerate geometry: result ∈ (-π, π].
        rng = np.random.default_rng(seed=42)
        for _ in range(5):
            pts = rng.standard_normal((4, 3))
            ang = _dihedral(pts[0], pts[1], pts[2], pts[3])
            assert -math.pi - 1e-9 <= ang <= math.pi + 1e-9


# ── fit_helix_axis ───────────────────────────────────────────────────────────


class TestFitHelixAxis:
    def test_z_axis_stack(self):
        """Pure +z stack → axis direction along z, centroid at column mean."""
        midpoints = np.array([[0.0, 0.0, float(i)] for i in range(5)])
        centroid, direction = fit_helix_axis(midpoints)
        assert np.allclose(centroid, [0.0, 0.0, 2.0])
        # Direction is unit length, parallel to z (sign is arbitrary from SVD)
        assert math.isclose(np.linalg.norm(direction), 1.0, abs_tol=1e-9)
        assert math.isclose(abs(direction[2]), 1.0, abs_tol=1e-9)
        assert math.isclose(direction[0], 0.0, abs_tol=1e-9)
        assert math.isclose(direction[1], 0.0, abs_tol=1e-9)

    def test_rotated_stack(self):
        """Stack along (1, 1, 1)/√3 — fit returns a parallel direction."""
        ax = np.array([1.0, 1.0, 1.0]) / math.sqrt(3.0)
        midpoints = np.array([i * ax for i in range(-2, 3)])
        _, direction = fit_helix_axis(midpoints)
        # Sign is arbitrary; |dot product| ≈ 1
        assert math.isclose(abs(float(np.dot(direction, ax))), 1.0, abs_tol=1e-9)

    def test_centroid_matches_mean(self):
        rng = np.random.default_rng(seed=7)
        # Random points along an axis with small jitter
        ax = np.array([0.0, 0.0, 1.0])
        base = np.array([1.0, 2.0, 3.0])
        midpoints = np.array([base + i * ax + rng.standard_normal(3) * 0.01 for i in range(10)])
        centroid, _ = fit_helix_axis(midpoints)
        assert np.allclose(centroid, midpoints.mean(axis=0))

    def test_unit_direction(self):
        """Returned direction is always unit length."""
        rng = np.random.default_rng(seed=11)
        midpoints = rng.standard_normal((6, 3))
        _, direction = fit_helix_axis(midpoints)
        assert math.isclose(np.linalg.norm(direction), 1.0, abs_tol=1e-9)


# ── compute_nucleotide_frame ─────────────────────────────────────────────────


class TestComputeNucleotideFrame:
    def test_returns_orthonormal_rotation(self):
        """R^T @ R == I, det(R) == 1 for a synthetic DT–DA pair."""
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        partner = _residue_from_template(
            resName="DA", base=_DA_BASE, chainID="B", mirror_xy=True
        )
        e_z = np.array([0.0, 0.0, 1.0])
        origin, R = compute_nucleotide_frame(residue, partner, e_z)
        assert origin.shape == (3,)
        assert R.shape == (3, 3)
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)
        assert math.isclose(np.linalg.det(R), 1.0, abs_tol=1e-9)

    def test_origin_is_residue_P(self):
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        partner = _residue_from_template(
            resName="DA", base=_DA_BASE, chainID="B", mirror_xy=True
        )
        e_z = np.array([0.0, 0.0, 1.0])
        origin, _R = compute_nucleotide_frame(residue, partner, e_z)
        assert np.allclose(origin, residue.pos("P"))

    def test_e_z_column_is_axis(self):
        """Third column of R equals the supplied axis direction."""
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        partner = _residue_from_template(
            resName="DA", base=_DA_BASE, chainID="B", mirror_xy=True
        )
        e_z = np.array([0.0, 0.0, 1.0])
        _origin, R = compute_nucleotide_frame(residue, partner, e_z)
        assert np.allclose(R[:, 2], e_z, atol=1e-9)

    def test_degenerate_axis_raises(self):
        """If axis is parallel to (partner.C1' - residue.C1'), e_y is degenerate."""
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        partner = _residue_from_template(
            resName="DA", base=_DA_BASE, chainID="B", mirror_xy=True
        )
        # Use the C1'→C1' direction itself as the "axis" — must raise.
        c1_self = residue.pos("C1'")
        c1_partner = partner.pos("C1'")
        bad_axis = (c1_partner - c1_self) / np.linalg.norm(c1_partner - c1_self)
        with pytest.raises(ValueError):
            compute_nucleotide_frame(residue, partner, bad_axis)


# ── sugar_pucker_phase ───────────────────────────────────────────────────────


class TestSugarPuckerPhase:
    def test_returns_phase_amplitude_label(self):
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        P_deg, tau_m_deg, label = sugar_pucker_phase(residue)
        # Phase ∈ [0, 360); amplitude finite; label is a non-empty string.
        assert 0.0 <= P_deg < 360.0
        assert math.isfinite(tau_m_deg)
        assert tau_m_deg >= 0.0
        assert isinstance(label, str)
        assert label != ""

    def test_calibrated_template_pucker(self):
        """The shipped 1ZEW-derived calibrated _SUGAR template falls in the
        C2'-exo sector (P ≈ 334°, amplitude ≈ 40°). Documented as the actual
        post-NADOC-frame-rotation value, not the canonical ideal B-DNA value;
        per feedback_interrupt_before_doubting_user we don't second-guess the
        calibrated coordinates.
        """
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        P_deg, tau_m_deg, label = sugar_pucker_phase(residue)
        # Empirically computed from the shipped template
        assert 320.0 < P_deg < 350.0
        assert 30.0 < tau_m_deg < 50.0
        assert label == "C2'-exo"

    def test_label_consistency_across_residue_types(self):
        """All four residue types share the same _SUGAR template, so they must
        return the same pucker label & phase (sugar atoms are identical)."""
        labels = set()
        phases = []
        for resname, base in [("DT", _DT_BASE), ("DA", _DA_BASE), ("DC", _DC_BASE), ("DG", _DG_BASE)]:
            res = _residue_from_template(resName=resname, base=base)
            P_deg, _tau, label = sugar_pucker_phase(res)
            labels.add(label)
            phases.append(P_deg)
        assert len(labels) == 1
        assert all(math.isclose(p, phases[0], abs_tol=1e-6) for p in phases)


# ── chi_angle ────────────────────────────────────────────────────────────────


class TestChiAngle:
    def test_purine_uses_N9_C4(self):
        """DA → χ via O4'-C1'-N9-C4 (purine path)."""
        residue = _residue_from_template(resName="DA", base=_DA_BASE)
        chi = chi_angle(residue)
        assert math.isfinite(chi)
        # Result is in degrees, within (-180, 180]
        assert -180.0 - 1e-9 <= chi <= 180.0 + 1e-9

    def test_pyrimidine_uses_N1_C2(self):
        """DT → χ via O4'-C1'-N1-C2 (pyrimidine path)."""
        residue = _residue_from_template(resName="DT", base=_DT_BASE)
        chi = chi_angle(residue)
        assert math.isfinite(chi)
        assert -180.0 - 1e-9 <= chi <= 180.0 + 1e-9

    def test_DA_DG_take_purine_branch(self):
        """DA and DG both reach for N9/C4 (purine atom names). Stripping the
        N9 atom forces a KeyError; pyrimidines (DC/DT) would fall through to
        the N1/C2 branch instead."""
        residue = _residue_from_template(resName="DA", base=_DA_BASE)
        # Remove N9 → purine path must fail; pyrimidine path would not.
        del residue.atoms["N9"]
        with pytest.raises(KeyError):
            chi_angle(residue)

    def test_DC_DT_take_pyrimidine_branch(self):
        """Conversely DC takes the N1/C2 branch — stripping N9 has no effect."""
        residue = _residue_from_template(resName="DC", base=_DC_BASE)
        # DC has no N9 to begin with; chi_angle must still work via N1/C2.
        chi = chi_angle(residue)
        assert math.isfinite(chi)


# ── analyze_wc_pair ──────────────────────────────────────────────────────────


class TestAnalyzeWCPair:
    def test_AT_pair_returns_geometry(self):
        """A·T pair: dataclass populated, C1'-C1' near canonical, two H-bonds."""
        dt = _residue_from_template(resName="DT", base=_DT_BASE)
        # Mirror DA across helix axis for an antiparallel partner.
        da = _residue_from_template(
            resName="DA", base=_DA_BASE, chainID="B", mirror_xy=True
        )
        result = analyze_wc_pair(dt, da)
        assert isinstance(result, WCPairGeometry)
        assert "DT" in result.pair_label and "DA" in result.pair_label
        # C1'-C1' distance: synthetic mirror gives ~0.98 nm; canonical B-DNA
        # is ~1.04 nm; the test stub is close enough to validate the math
        # without being a literature benchmark.
        assert 0.5 < result.c1_c1_distance_nm < 1.5
        # AT has two WC H-bonds: O4...N6 and N3...N1
        assert "O4...N6" in result.hbond_distances_nm
        assert "N3...N1" in result.hbond_distances_nm
        for d in result.hbond_distances_nm.values():
            assert math.isfinite(d) and d > 0.0
        assert math.isfinite(result.propeller_twist_deg)
        # Propeller is computed from acos(|cos|) → always ∈ [0, 90]
        assert 0.0 <= result.propeller_twist_deg <= 90.0

    def test_GC_pair_three_hbonds(self):
        """G·C pair has three WC H-bonds (vs two for A·T)."""
        dg = _residue_from_template(resName="DG", base=_DG_BASE)
        dc = _residue_from_template(
            resName="DC", base=_DC_BASE, chainID="B", mirror_xy=True
        )
        result = analyze_wc_pair(dg, dc)
        assert len(result.hbond_distances_nm) == 3
        # Expected GC bond identifiers per _WC_HBONDS table
        for key in ("O6...N4", "N1...N3", "N2...O2"):
            assert key in result.hbond_distances_nm

    def test_mismatch_pair_no_hbonds(self):
        """A·G mismatch has no entry in the WC H-bond table → empty dict."""
        da = _residue_from_template(resName="DA", base=_DA_BASE)
        dg = _residue_from_template(
            resName="DG", base=_DG_BASE, chainID="B", mirror_xy=True
        )
        result = analyze_wc_pair(da, dg)
        # The H-bond table flags the mismatch by being empty.
        assert result.hbond_distances_nm == {}
        # C1'-C1' distance still reported (geometric quantity).
        assert math.isfinite(result.c1_c1_distance_nm)


# ── analyze_duplex ───────────────────────────────────────────────────────────


def _write_synthetic_duplex_pdb(path: str, n_bp: int = 4) -> None:
    """Write a tiny synthetic AT/AT/.../AT duplex PDB for analyze_duplex.

    Chain A: TTTT (resSeq 1..N), 5'→3' along +z.
    Chain B: AAAA (resSeq 1..N), antiparallel; resSeq 1 pairs with chain A's
             last residue (canonical antiparallel WC convention).
    Each bp is rotated by B-DNA twist (34.3°) and translated by 0.334 nm.
    """
    rise_nm = 0.334
    twist_rad = math.radians(34.3)

    def write_atom(f, serial, name, resName, chainID, resSeq, x, y, z, elem):
        # PDB ATOM record (Angstroms = nm × 10)
        line = (
            "ATOM  "
            f"{serial:>5d} "
            f"{name:<4s} "
            f"{resName:<3s} "
            f"{chainID}"
            f"{resSeq:>4d}    "
            f"{x*10:>8.3f}{y*10:>8.3f}{z*10:>8.3f}"
            f"  1.00  0.00           {elem:<2s}\n"
        )
        f.write(line)

    def write_residue(f, atoms_template, resName, chainID, resSeq, twist, dz, mirror, serial):
        c, s = math.cos(twist), math.sin(twist)
        for name, elem, n, y, z in atoms_template:
            if mirror:
                n, y = -n, -y
            x_w = c * n - s * y
            y_w = s * n + c * y
            z_w = z + dz
            write_atom(f, serial, name, resName, chainID, resSeq, x_w, y_w, z_w, elem)
            serial += 1
        return serial

    with open(path, "w") as f:
        serial = 1
        # Chain A: TTTT (resSeq 1..N) along +z
        for i in range(n_bp):
            seq = i + 1
            serial = write_residue(f, _SUGAR, "DT", "A", seq, i * twist_rad, i * rise_nm, False, serial)
            serial = write_residue(f, _DT_BASE, "DT", "A", seq, i * twist_rad, i * rise_nm, False, serial)
        # Chain B: AAAA (resSeq 1..N), antiparallel: B:1 ↔ A:N
        for i in range(n_bp):
            seq = i + 1
            a_seq = n_bp - i  # B:1 pairs with A:N
            serial = write_residue(
                f, _SUGAR, "DA", "B", seq,
                (a_seq - 1) * twist_rad, (a_seq - 1) * rise_nm, True, serial,
            )
            serial = write_residue(
                f, _DA_BASE, "DA", "B", seq,
                (a_seq - 1) * twist_rad, (a_seq - 1) * rise_nm, True, serial,
            )
        f.write("END\n")


class TestAnalyzeDuplex:
    def test_synthetic_4bp_duplex(self, tmp_path):
        """4-bp AT-tract duplex through the full pipeline.

        Inner residues = 2 (one per strand after exclude_terminal=1), so:
          - 1 backbone step on chain A
          - 2 WC pairs (one per inner residue × 1 strand pair logic)
        Per-bp geometry should match the synthetic generation parameters:
          rise ≈ 0.334 nm, twist ≈ 34.3°.
        """
        pdb_path = tmp_path / "synthetic_4bp.pdb"
        _write_synthetic_duplex_pdb(str(pdb_path), n_bp=4)
        assert pdb_path.exists()
        assert pdb_path.stat().st_size < 20_000  # < 20 KB sanity guard

        analysis = analyze_duplex(str(pdb_path), chain_a="A", chain_b="B", exclude_terminal=1)

        # Backbone step: one inner→inner step on chain A
        assert len(analysis.backbone_steps) == 1
        step = analysis.backbone_steps[0]
        assert math.isclose(step.rise_nm, 0.334, abs_tol=0.01)
        assert math.isclose(step.twist_deg, 34.3, abs_tol=1.0)
        # Slide & shift: finite and bounded. Magnitudes for a synthetic duplex
        # built from the calibrated NADOC-frame templates are non-trivial
        # (~0.1 nm) — the templates were rotated for NADOC geometry, not for
        # crystal-ideal slide/shift. Loose bounds — we're exercising the math,
        # not validating against literature B-DNA.
        assert math.isfinite(step.slide_nm)
        assert math.isfinite(step.shift_nm)
        assert abs(step.slide_nm) < 0.3
        assert abs(step.shift_nm) < 0.3

        # WC pairs
        assert len(analysis.wc_pairs) >= 2
        for pair in analysis.wc_pairs:
            assert 0.5 < pair.c1_c1_distance_nm < 1.5
            assert "DT" in pair.pair_label and "DA" in pair.pair_label

        # Sugar template aggregated (11 atoms in _SUGAR)
        assert len(analysis.sugar_template) == 11
        # Base templates collected per residue type
        assert "DT" in analysis.base_templates
        assert "DA" in analysis.base_templates
        # C1' z-shift convention applied → C1' template at z=0
        assert math.isclose(analysis.sugar_template["C1'"][2], 0.0, abs_tol=1e-9)

        # Per-residue diagnostics populated for inner residues only
        assert len(analysis.chi_angles) >= 2
        assert len(analysis.sugar_puckers) >= 2
        assert len(analysis.ribose_base_rotations) >= 2
        assert len(analysis.bond_distances) >= 2
        # Each chi entry is a list of one float (inner residue only)
        for chi_list in analysis.chi_angles.values():
            assert len(chi_list) == 1
            assert math.isfinite(chi_list[0])
