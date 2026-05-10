"""
Tests for backend/checkers/openmm_checker.py — Phase 9.

Three tiers:

Tier 1 — pure unit tests (no OpenMM required, always run)
    _rename_charmm_to_amber_pdb, _build_c1prime_reference,
    _compute_drift_metrics — tested against synthetic data.

Tier 2 — smoke tests (@skip_no_openmm, not @slow)
    verify_design_with_openmm on a 21 bp single helix, CPU only,
    50-step minimise + 100 NVT steps. Checks return type, field
    presence, and basic sanity (finite energy, n_missing == 0).
    Each test < 60 s on CPU.

Tier 3 — full MD (@pytest.mark.slow + @skip_no_openmm)
    10 ps NVT runs on single-helix and two-helix designs.
    Checks drift thresholds and inter-helix COM stability.
"""

from __future__ import annotations

import pytest
import numpy as np

# ── OpenMM availability guard ────────────────────────────────────────────────────

_has_openmm = False
try:
    import openmm  # noqa: F401
    _has_openmm = True
except ImportError:
    pass

skip_no_openmm = pytest.mark.skipif(
    not _has_openmm, reason="openmm not installed (conda install -c conda-forge openmm)"
)


# ── Design helper functions (NOT pytest fixtures — project convention) ────────────


def _make_single_helix_design(length_bp: int = 42):
    """Single helix along +Z, scaffold FORWARD + staple REVERSE."""
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import (
        Design, DesignMetadata, Direction, Domain, Helix,
        LatticeType, Strand, StrandType, Vec3,
    )
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
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="staple",
        domains=[Domain(helix_id="test_helix", start_bp=length_bp - 1, end_bp=0,
                        direction=Direction.REVERSE)],
    )
    return Design(
        id="test_single",
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Test single helix"),
    )


def _make_two_helix_design(length_bp: int = 42):
    """Two side-by-side honeycomb helices (no crossovers)."""
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import (
        Design, DesignMetadata, Direction, Domain, Helix,
        LatticeType, Strand, StrandType, Vec3,
    )
    SPACING = 2.25  # honeycomb nearest-neighbour spacing (nm)
    h0 = Helix(id="h0", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
               axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=length_bp)
    h1 = Helix(id="h1", axis_start=Vec3(x=SPACING, y=0.0, z=0.0),
               axis_end=Vec3(x=SPACING, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=length_bp)
    strands = [
        Strand(id="scaf0", strand_type=StrandType.SCAFFOLD,
               domains=[Domain(helix_id="h0", start_bp=0, end_bp=length_bp - 1,
                               direction=Direction.FORWARD)]),
        Strand(id="stpl0",
               domains=[Domain(helix_id="h0", start_bp=length_bp - 1, end_bp=0,
                               direction=Direction.REVERSE)]),
        Strand(id="scaf1", strand_type=StrandType.STAPLE,
               domains=[Domain(helix_id="h1", start_bp=0, end_bp=length_bp - 1,
                               direction=Direction.FORWARD)]),
        Strand(id="stpl1",
               domains=[Domain(helix_id="h1", start_bp=length_bp - 1, end_bp=0,
                               direction=Direction.REVERSE)]),
    ]
    return Design(
        id="test_two",
        helices=[h0, h1],
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Test two helix"),
    )


# ── Tier 1: pure unit tests ──────────────────────────────────────────────────────


class TestRenameCharmm36ToAmber14:
    """_rename_charmm_to_amber_pdb: atom name and residue name substitutions."""

    def test_op1_renamed_to_o1p(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        # Residue 2 is an inner residue (chain has 1, 2, 3), so OP1 → O1P
        pdb = (
            "ATOM      1  C1'  DA A   1       0.000   1.000   2.000  1.00  0.00           C  \n"
            "ATOM      2  P    DA A   2       1.000   2.000   3.000  1.00  0.00           P  \n"
            "ATOM      3  OP1  DA A   2       1.100   2.100   3.100  1.00  0.00           O  \n"
            "ATOM      4  C1'  DA A   2       1.200   2.200   3.200  1.00  0.00           C  \n"
            "ATOM      5  C1'  DA A   3       2.000   3.000   4.000  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        atom_fields = {line[12:16] for line in result.splitlines()
                       if line.startswith("ATOM")}
        assert " O1P" in atom_fields
        assert " OP1" not in atom_fields

    def test_op2_renamed_to_o2p(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        # Residue 2 is inner; OP2 → O2P
        pdb = (
            "ATOM      1  C1'  DA A   1       0.000   1.000   2.000  1.00  0.00           C  \n"
            "ATOM      2  P    DA A   2       1.000   2.000   3.000  1.00  0.00           P  \n"
            "ATOM      3  OP2  DA A   2       1.100   2.100   3.100  1.00  0.00           O  \n"
            "ATOM      4  C1'  DA A   2       1.200   2.200   3.200  1.00  0.00           C  \n"
            "ATOM      5  C1'  DA A   3       2.000   3.000   4.000  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        atom_fields = {line[12:16] for line in result.splitlines()
                       if line.startswith("ATOM")}
        assert " O2P" in atom_fields
        assert " OP2" not in atom_fields

    def test_c1prime_atom_name_unchanged(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = (
            "ATOM      1  C1'  DA A   1       0.000   1.000   2.000  1.00  0.00           C  \n"
            "ATOM      2  P    DA A   2       1.000   2.000   3.000  1.00  0.00           P  \n"
            "ATOM      3  C1'  DA A   2       1.200   2.200   3.200  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        atom_fields = {line[12:16] for line in result.splitlines()
                       if line.startswith("ATOM")}
        assert " C1'" in atom_fields

    def test_non_atom_lines_not_modified(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = "REMARK  OP1 OP2 — REMARK lines should not be renamed\n"
        result = _rename_charmm_to_amber_pdb(pdb)
        assert "OP1" in result   # REMARK lines pass through unchanged

    def test_conect_records_stripped(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = (
            "ATOM      1  P    DA A   2       1.000   2.000   3.000  1.00  0.00           P  \n"
            "CONECT    1    2    3\n"
            "END\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        assert "CONECT" not in result

    def test_link_records_stripped(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = (
            "ATOM      1  O3'  DA A   2       1.000   2.000   3.000  1.00  0.00           O  \n"
            "LINK         O3'  DA A   2                 P    DA A   3      1.60\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        assert "LINK" not in result

    def test_5prime_terminal_p_removed(self):
        """P, OP1, OP2 must be absent from the first residue per chain."""
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        # Chain A: residues 1 (5'-terminal), 2 (inner)
        pdb = (
            "ATOM      1  P    DA A   1       1.000   2.000   3.000  1.00  0.00           P  \n"
            "ATOM      2  OP1  DA A   1       1.100   2.100   3.100  1.00  0.00           O  \n"
            "ATOM      3  OP2  DA A   1       1.200   2.200   3.200  1.00  0.00           O  \n"
            "ATOM      4  C1'  DA A   1       1.300   2.300   3.300  1.00  0.00           C  \n"
            "ATOM      5  P    DA A   2       2.000   3.000   4.000  1.00  0.00           P  \n"
            "ATOM      6  OP1  DA A   2       2.100   3.100   4.100  1.00  0.00           O  \n"
            "ATOM      7  C1'  DA A   2       2.200   3.200   4.200  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        atom_lines = [l for l in result.splitlines() if l.startswith("ATOM")]
        # Only residue 1 atoms remaining for seq 1 should NOT include P/OP1/OP2
        res1_atoms = {l[12:16].strip() for l in atom_lines if int(l[22:26]) == 1}
        assert "P" not in res1_atoms
        assert "OP1" not in res1_atoms
        assert "OP2" not in res1_atoms
        assert "C1'" in res1_atoms

    def test_5prime_terminal_residue_renamed_to_xx5(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        # Chain A: two residues — first is 5'-terminal
        pdb = (
            "ATOM      1  C1'  DA A   1       1.000   2.000   3.000  1.00  0.00           C  \n"
            "ATOM      2  C1'  DA A   2       2.000   3.000   4.000  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        res_names = {l[17:20] for l in result.splitlines() if l.startswith("ATOM")}
        assert "DA5" in res_names   # first residue

    def test_3prime_terminal_residue_renamed_to_xx3(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = (
            "ATOM      1  C1'  DA A   1       1.000   2.000   3.000  1.00  0.00           C  \n"
            "ATOM      2  C1'  DA A   2       2.000   3.000   4.000  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        res_names = {l[17:20] for l in result.splitlines() if l.startswith("ATOM")}
        assert "DA3" in res_names   # last residue

    def test_inner_residue_keeps_original_name(self):
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        pdb = (
            "ATOM      1  C1'  DA A   1       1.000   2.000   3.000  1.00  0.00           C  \n"
            "ATOM      2  C1'  DA A   2       2.000   3.000   4.000  1.00  0.00           C  \n"
            "ATOM      3  C1'  DA A   3       3.000   4.000   5.000  1.00  0.00           C  \n"
            "TER\n"
        )
        result = _rename_charmm_to_amber_pdb(pdb)
        # Residue 2 is inner: should be " DA"
        inner_lines = [l for l in result.splitlines()
                       if l.startswith("ATOM") and int(l[22:26]) == 2]
        assert all(l[17:20] == " DA" for l in inner_lines)

    def test_roundtrip_on_real_export(self):
        """Export PDB from a real 21 bp design; verify OP1/OP2 fully gone from ATOM lines."""
        from backend.core.pdb_export import export_pdb
        from backend.checkers.openmm_checker import _rename_charmm_to_amber_pdb
        design = _make_single_helix_design(21)
        pdb = export_pdb(design)
        renamed = _rename_charmm_to_amber_pdb(pdb)
        for line in renamed.splitlines():
            if line.startswith("ATOM"):
                assert line[12:16] not in (" OP1", " OP2"), (
                    f"CHARMM36 name survived rename: {line}"
                )
        # O1P and O2P should be present (inner residue phosphate oxygens)
        inner_names = {
            line[12:16] for line in renamed.splitlines()
            if line.startswith("ATOM") and line[17:20].strip() not in
            {"DA5", "DT5", "DC5", "DG5"}  # exclude 5'-terminal (no phosphate)
        }
        assert " O1P" in inner_names
        assert " O2P" in inner_names


class TestBuildC1primeReference:
    """_build_c1prime_reference: positions in nm, one per nucleotide."""

    def test_returns_nonempty_for_valid_design(self):
        from backend.checkers.openmm_checker import _build_c1prime_reference
        design = _make_single_helix_design(21)
        ref = _build_c1prime_reference(design)
        assert len(ref) > 0

    def test_one_entry_per_nucleotide(self):
        """21 bp duplex → 42 nucleotides → 42 C1' atoms."""
        from backend.checkers.openmm_checker import _build_c1prime_reference
        design = _make_single_helix_design(21)
        ref = _build_c1prime_reference(design)
        assert len(ref) == 21 * 2

    def test_positions_are_float_arrays(self):
        from backend.checkers.openmm_checker import _build_c1prime_reference
        design = _make_single_helix_design(21)
        ref = _build_c1prime_reference(design)
        for key, pos in ref.items():
            assert pos.shape == (3,)
            assert pos.dtype in (np.float32, np.float64)

    def test_all_directions_present(self):
        from backend.checkers.openmm_checker import _build_c1prime_reference
        design = _make_single_helix_design(21)
        ref = _build_c1prime_reference(design)
        directions = {k[2] for k in ref}
        assert "FORWARD" in directions
        assert "REVERSE" in directions

    def test_positions_near_expected_z_axis(self):
        """C1' z-coordinates should be near bp_index * BDNA_RISE_PER_BP (within 0.1 nm)."""
        from backend.checkers.openmm_checker import _build_c1prime_reference
        from backend.core.constants import BDNA_RISE_PER_BP
        design = _make_single_helix_design(21)
        ref = _build_c1prime_reference(design)
        for (helix_id, bp_index, direction), pos in ref.items():
            expected_z = bp_index * BDNA_RISE_PER_BP
            assert abs(pos[2] - expected_z) < 0.1, (
                f"C1' z={pos[2]:.3f} nm far from expected z={expected_z:.3f} nm "
                f"(helix={helix_id}, bp={bp_index}, dir={direction})"
            )


class TestComputeDriftMetrics:
    """_compute_drift_metrics: RMSD and COM drift computation with known inputs."""

    def _get_ref(self):
        from backend.checkers.openmm_checker import _build_c1prime_reference
        design = _make_single_helix_design(21)
        return _make_single_helix_design(21), _build_c1prime_reference(design)

    def test_zero_drift_when_positions_match(self):
        from backend.checkers.openmm_checker import _compute_drift_metrics
        design, ref = self._get_ref()
        global_rmsd, _, max_dev, n_missing, _ = _compute_drift_metrics(ref, ref, design)
        assert global_rmsd < 1e-9
        assert max_dev < 1e-9
        assert n_missing == 0

    def test_uniform_translation_removed_by_centroid_alignment(self):
        """A constant +0.3 nm shift in X should be fully cancelled by centroid correction."""
        from backend.checkers.openmm_checker import _compute_drift_metrics
        design, ref = self._get_ref()
        shifted = {k: pos + np.array([0.3, 0.0, 0.0]) for k, pos in ref.items()}
        global_rmsd, _, max_dev, n_missing, _ = _compute_drift_metrics(shifted, ref, design)
        assert global_rmsd < 1e-6, f"Centroid alignment failed: global_rmsd={global_rmsd:.2e}"
        assert n_missing == 0

    def test_random_per_atom_noise_produces_nonzero_rmsd(self):
        from backend.checkers.openmm_checker import _compute_drift_metrics
        design, ref = self._get_ref()
        rng = np.random.default_rng(42)
        noisy = {k: pos + rng.normal(0, 0.1, 3) for k, pos in ref.items()}
        global_rmsd, per_helix, _, _, _ = _compute_drift_metrics(noisy, ref, design)
        assert global_rmsd > 0.0
        assert "test_helix" in per_helix

    def test_missing_keys_counted(self):
        """n_missing = sim keys with no matching ref key (unexpected simulation atoms)."""
        from backend.checkers.openmm_checker import _compute_drift_metrics
        design, ref = self._get_ref()
        # Add a fake key to avg that has no ref counterpart
        extra_sim = {**ref, ("fake_helix", 999, "FORWARD"): np.zeros(3)}
        _, _, _, n_missing, _ = _compute_drift_metrics(extra_sim, ref, design)
        assert n_missing == 1

    def test_pass_threshold_on_zero_drift(self):
        """Zero drift should satisfy max_dev < 0.5 nm and global_rmsd < 0.3 nm."""
        from backend.checkers.openmm_checker import (
            _compute_drift_metrics,
            _MAX_DEVIATION_THRESHOLD_NM,
            _GLOBAL_RMSD_THRESHOLD_NM,
        )
        design, ref = self._get_ref()
        global_rmsd, _, max_dev, _, _ = _compute_drift_metrics(ref, ref, design)
        assert max_dev < _MAX_DEVIATION_THRESHOLD_NM
        assert global_rmsd < _GLOBAL_RMSD_THRESHOLD_NM

    def test_two_helix_com_drift_zero_when_positions_match(self):
        from backend.checkers.openmm_checker import (
            _compute_drift_metrics, _build_c1prime_reference,
        )
        design = _make_two_helix_design(21)
        ref = _build_c1prime_reference(design)
        _, _, _, _, com_drift = _compute_drift_metrics(ref, ref, design)
        for pair_key, drift in com_drift.items():
            assert drift < 1e-9, f"COM drift for {pair_key}: {drift:.2e} nm"


class TestImportError:
    """verify_design_with_openmm raises ImportError when openmm is absent."""

    @pytest.mark.skipif(_has_openmm, reason="openmm is installed; cannot test ImportError")
    def test_raises_import_error_without_openmm(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        with pytest.raises(ImportError, match="openmm"):
            verify_design_with_openmm(design)


# ── Tier 2: smoke tests (require openmm, not slow) ───────────────────────────────


@skip_no_openmm
class TestOpenMMSmoke:
    """Minimal OpenMM run: 50 minimise + 100 NVT steps on 21 bp single helix, CPU."""

    _SMOKE_KWARGS = dict(
        n_steps_minimize=50,
        n_steps_nvt=100,
        reporting_interval=100,
        prefer_gpu=False,
    )

    def test_returns_verification_result(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm, VerificationResult
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert isinstance(result, VerificationResult)

    def test_per_helix_rmsd_has_expected_helix_key(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert "test_helix" in result.per_helix_rmsd_nm

    def test_platform_is_cpu(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert result.platform_used == "CPU"

    def test_ff_description_mentions_amber14_and_gbn2(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        desc = result.ff_description.upper()
        assert "AMBER14" in desc
        assert "GBN" in desc

    def test_n_missing_is_zero_for_valid_design(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert result.n_missing == 0

    def test_potential_energy_is_finite_and_negative(self):
        """GBNeck2 implicit-solvent energy is negative for solvated DNA."""
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert np.isfinite(result.potential_energy_kj_per_mol)
        assert result.potential_energy_kj_per_mol < 0.0

    def test_n_atoms_is_positive(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert result.n_atoms > 0

    def test_global_rmsd_is_finite(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert np.isfinite(result.global_rmsd_nm)

    def test_warnings_is_list(self):
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._SMOKE_KWARGS)
        assert isinstance(result.warnings, list)


# ── Tier 3: full MD integration (slow) ──────────────────────────────────────────


@skip_no_openmm
class TestOpenMMFullMD:
    """Full 10 ps NVT run. Expects drift < thresholds. ~2–5 min on CPU."""

    _NVT_KWARGS = dict(
        n_steps_minimize=500,
        n_steps_nvt=5_000,      # 10 ps at 2 fs/step
        reporting_interval=500,
        prefer_gpu=False,
    )

    @pytest.mark.slow
    def test_single_helix_21bp_passes_drift_threshold(self):
        """
        A 21 bp single helix under 10 ps GBNeck2 MD should stay structurally
        stable (no constraints, purely implicit solvent thermal motion).
        Expected: global_rmsd < 0.3 nm, max_deviation < 0.5 nm.
        """
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_single_helix_design(21)
        result = verify_design_with_openmm(design, **self._NVT_KWARGS)
        assert result.passed, (
            f"Single helix failed drift threshold:\n"
            f"  global_rmsd = {result.global_rmsd_nm:.3f} nm  (threshold 0.3)\n"
            f"  max_dev     = {result.max_deviation_nm:.3f} nm  (threshold 0.5)\n"
            f"  warnings    = {result.warnings}"
        )

    @pytest.mark.slow
    def test_two_helix_inter_helix_com_drift_small(self):
        """
        A 2-helix design (no crossovers) should maintain inter-helix distance
        within 0.5 nm over 10 ps. Larger drift indicates GBNeck2 over-repulsion
        without explicit Mg²⁺ — a known limitation documented in the module.
        """
        from backend.checkers.openmm_checker import verify_design_with_openmm
        design = _make_two_helix_design(42)
        result = verify_design_with_openmm(design, **self._NVT_KWARGS)
        for pair_key, drift in result.inter_helix_com_drift_nm.items():
            assert drift < 0.5, (
                f"Inter-helix COM drift {pair_key}: {drift:.3f} nm > 0.5 nm. "
                "This may indicate implicit-Mg²⁺ repulsion — note limitation in module docstring."
            )
