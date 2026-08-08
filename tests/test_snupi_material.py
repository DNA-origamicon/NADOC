"""Phase-2 foundation pin: SNUPI 6x6 sectional constitutive matrices.

Guards backend/physics/snupi_material.py (assembles the transcribed SNUPI params
into per-motif / per-family 6x6 D matrices). Formulation-independent — no element
or NADOC-frame mapping here. See memory/project_snupi_mimic.md (Phase 2).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.physics import snupi_material as sm


def test_dof_order_axial_is_dx():
    # SNUPI axial DOF is dx (Rise); torsion is theta_x about it.
    assert sm.DOF_ORDER[0] == "dx"
    assert sm.DOF_ORDER[3] == "theta_x"


def test_motif_D_symmetric_and_diag_matches_rigidity():
    D = sm.motif_D("regular_bp", "AA/TT")
    assert D.shape == (6, 6)
    assert np.allclose(D, D.T)
    # diagonal == the tabulated rigidities (EA=1920.9, GJ=400.39, EIy=172.67 for AA/TT)
    assert D[0, 0] == pytest.approx(1920.9)  # EA
    assert D[3, 3] == pytest.approx(400.39)  # GJ
    assert D[4, 4] == pytest.approx(172.67)  # EIy
    # twist-stretch coupling sits at (dx, theta_x) = (0, 3)
    assert D[0, 3] == pytest.approx(-300.81)
    assert D[3, 0] == pytest.approx(-300.81)


def test_family_mean_matches_si_mean_column():
    rig = sm.family_mean_rigidity("regular_bp")
    # SI Table S1 Mean column
    assert rig["EA"] == pytest.approx(1825.2, abs=0.1)
    assert rig["GJ"] == pytest.approx(313.83, abs=0.1)
    assert rig["EIy"] == pytest.approx(158.33, abs=0.1)
    assert rig["EIz"] == pytest.approx(245.79, abs=0.1)
    # mean twist-stretch coupling ~ -277
    D = sm.family_mean_D("regular_bp")
    assert D[0, 3] == pytest.approx(-277.39, abs=0.1)


def test_all_families_present_and_mean_D_finite():
    for fam in sm.MOTIF_FAMILIES:
        D = sm.family_mean_D(fam)
        assert D.shape == (6, 6)
        assert np.all(np.isfinite(D))
        assert np.allclose(D, D.T)


def _is_pd(D: np.ndarray) -> bool:
    try:
        np.linalg.cholesky(D)
        return True
    except np.linalg.LinAlgError:
        return False


def test_non_pd_is_confined_to_single_co():
    """Documented SNUPI limitation, NOT a transcription error: a single crossover is
    barely constrained, so its covariance inversion is unstable and ~half the single-CO
    per-motif D matrices are indefinite (e.g. AT|AT has g(dx,dy)=636.5 pN > sqrt(EA*GAy)).
    Every OTHER family is fully PD. Verified against SI raw values. This pins that the
    indefiniteness stays confined to single_co (a new non-PD motif elsewhere => a real
    transcription/assembly regression)."""
    from backend.physics.snupi_material import _load

    non_pd = {}
    for fam, entries in _load()["motifs"].items():
        bad = [m for m in entries if not _is_pd(sm.motif_D(fam, m))]
        if bad:
            non_pd[fam] = bad
    assert set(non_pd) <= {"single_co"}, (
        f"non-PD outside single_co (regression!): {non_pd}"
    )
    # the 4 non-floppy families are entirely PD
    for fam in ("regular_bp", "nicked_bp", "co_nick", "double_co"):
        assert fam not in non_pd


def test_family_mean_D_positive_definite():
    # mean over a family regularizes the noisy single-CO fits => every family MEAN is PD.
    # This is the material actually used by the Phase-2 'MEAN first' FEM path.
    for fam in sm.MOTIF_FAMILIES:
        assert _is_pd(sm.family_mean_D(fam)), f"{fam} mean D not PD"


def test_motif_families_ordered_by_stiffness_sanity():
    # CO steps (span to neighbour helix) are axially far stiffer than a regular BP step;
    # nicked is softer torsionally. Sanity ordering, not a tight tolerance.
    ea = {f: sm.family_mean_rigidity(f)["EA"] for f in sm.MOTIF_FAMILIES}
    assert ea["double_co"] > ea["regular_bp"]
    gj = {f: sm.family_mean_rigidity(f)["GJ"] for f in sm.MOTIF_FAMILIES}
    assert gj["nicked_bp"] < gj["regular_bp"]
