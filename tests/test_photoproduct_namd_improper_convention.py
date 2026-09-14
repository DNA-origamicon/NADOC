import shutil
from pathlib import Path

import pytest

from backend.parameterization.photoproduct_improper_convention import (
    audit_namd_improper_convention,
)


pytestmark = pytest.mark.slow


def test_real_namd_charmm_improper_distinguishes_mirrored_center(tmp_path: Path):
    psfgen = shutil.which("psfgen")
    namd = shutil.which("namd3") or shutil.which("namd2") or shutil.which("namd")
    if not psfgen or not namd:
        pytest.skip("real psfgen and NAMD executables are required")

    report = audit_namd_improper_convention(
        output_dir=tmp_path / "audit",
        psfgen_path=Path(psfgen),
        namd_path=Path(namd),
    )

    assert report["status"] == "passed_convention_only"
    assert report["passed"] is True
    assert report["gate_effect"] == "none"
    assert report["product_parameter_authority"] is False
    assert report["checks"] == {
        "bond_energy_invariant": True,
        "angle_energy_invariant": True,
        "improper_distinguishes_reflection": True,
        "declared_positive_z_hand_is_lower": True,
    }
    assert report["energies_kcal_mol"]["plus"]["IMPRP"] < report[
        "energies_kcal_mol"
    ]["minus"]["IMPRP"]
    assert report["engine"]["identity_lines"]
    assert (tmp_path / "audit" / "improper_convention_audit.json").is_file()
