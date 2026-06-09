from __future__ import annotations

import pytest

from backend.core.md_charge import audit_psf
from backend.core.namd_topology import (
    _ATOM_TO_CHARMM,
    _RESNAME_TO_CHARMM,
    _psfgen_script,
    build_charmm_psfgen_topology,
    find_psfgen,
)


def _has_psfgen() -> bool:
    try:
        find_psfgen()
    except RuntimeError:
        return False
    return True


def test_psfgen_name_maps_cover_nadoc_dna_names() -> None:
    assert _RESNAME_TO_CHARMM == {
        "DA": "ADE",
        "DC": "CYT",
        "DG": "GUA",
        "DT": "THY",
    }
    assert _ATOM_TO_CHARMM["OP1"] == "O1P"
    assert _ATOM_TO_CHARMM["OP2"] == "O2P"
    assert _ATOM_TO_CHARMM["C7"] == "C5M"


def test_psfgen_script_applies_auto_namd_style_deoxy_patches(tmp_path) -> None:
    script = _psfgen_script([
        {
            "segid": "DNAA",
            "path": tmp_path / "DNAA.pdb",
            "first_resid": 1,
            "last_resid": 3,
        }
    ], tmp_path / "out")

    assert "segment DNAA" in script
    assert "first 5TER" in script
    assert "last 3TER" in script
    assert "patch DEO5 DNAA:1" in script
    assert "patch DEOX DNAA:2" in script
    assert "patch DEOX DNAA:3" in script
    assert "guesscoord" in script
    assert "writepsf" in script


@pytest.mark.skipif(
    not _has_psfgen(),
    reason="psfgen is not installed",
)
def test_charmm_psfgen_topology_builds_hydrogenated_neutral_small_design() -> None:
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design(
        cells=[(0, 0)],
        length_bp=4,
        name="psfgen_smoke",
        strand_filter="scaffold",
    )

    built = build_charmm_psfgen_topology(design)
    audit = audit_psf(
        built.psf_text,
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )

    assert audit.passed
    assert audit.dna_hydrogens > 0
    assert audit.dna_residues == 4
    assert "REMARKS segment DNA" in built.psf_text
