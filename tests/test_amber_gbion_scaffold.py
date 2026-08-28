from pathlib import Path

import pytest

from experiments.exp58_amber_gbion.model import (
    GBIONNaClConfig,
    render_ion_restraints,
    render_production_mdin,
    require_amber26_archive,
)


def test_sltcap_counts_are_neutral_and_include_coions():
    config = GBIONNaClConfig()
    sodium, chloride = config.ion_counts(-40)
    assert sodium - chloride == 40
    assert sodium > 40
    assert chloride > 0


def test_mdin_uses_explicit_ions_without_debye_double_counting():
    mdin = render_production_mdin(GBIONNaClConfig(), steps=500_000)
    for token in (
        "igb=8",
        "gbion=3",
        "alpb=0",
        "gbsa=3",
        "saltcon=0.0",
        "gi_coef_1_n=0.05",
        "intdiel_ion_1_p=54.0",
        "nmropt=1",
        "DISANG=disang_NaCl.txt",
    ):
        assert token in mdin


def test_group_restraints_make_a_flat_40_angstrom_ion_cap():
    text = render_ion_restraints([1, 20, 39], [100, 101], GBIONNaClConfig())
    assert text.count("&rst") == 2
    assert "iat=-1,100" in text
    assert "iat=-1,101" in text
    assert "igr1=1,20,39,0" in text
    assert "r2=0.0, r3=40.000000" in text
    assert "rk2=0.0, rk3=20.000000" in text


def test_archive_preflight_fails_before_provider_work(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no RunPod pod was created"):
        require_amber26_archive(tmp_path / "pmemd26.tar.bz2")


def test_archive_preflight_rejects_wrong_name(tmp_path: Path):
    wrong = tmp_path / "amber.tar.bz2"
    # Filename validation precedes the size check, so this fixture stays tiny.
    wrong.write_bytes(b"x")
    with pytest.raises(ValueError, match="expected.*pmemd26.tar.bz2"):
        require_amber26_archive(wrong)
