"""Fractional natural-terminal crops keep charges and fail closed on drift."""

import copy

import pytest

from backend.core.md_charge import audit_psf
from backend.core.namd_submodel_charge import (
    audit_options, charge_policy, record_charge_policy,
)
from backend.core.namd_solvate import ion_counts


def psf(charges):
    # Parser-only fixture: each residue includes a hydrogen, not molecular geometry.
    rows = []
    for i, q in enumerate(charges):
        rows.extend([
            f"{2*i+1} DNA {i+1} ADE P P {q} 30.974 0",
            f"{2*i+2} DNA {i+1} ADE H H 0 1.008 0",
        ])
    return f"PSF\n\n{len(rows)} !NATOM\n" + "\n".join(rows) + "\n"


def test_fractional_crop_preserves_charge_and_audits_counterions():
    source, crop = psf([-.47, -1, -.53]), psf([-.47, -1])
    policy = record_charge_policy(source, crop)
    assert policy["dna_charge_e"] == pytest.approx(-1.47)
    assert policy["counterion_charge_e"] == 1
    assert policy["residual_charge_e"] == pytest.approx(-.47)
    assert not audit_psf(crop).passed  # Whole-model default remains strict.
    assert audit_psf(crop, **audit_options(policy)).passed
    assert charge_policy({"submodel": {"charge_policy": policy}}, crop) == policy
    final = psf([-.47])  # Same net charge as crop plus one monovalent cation.
    assert audit_psf(final, **audit_options(policy, final=True)).passed
    assert not audit_psf(final, require_neutral=True, **audit_options(policy, final=True)).passed
    assert not audit_psf(psf([-.46]), **audit_options(policy, final=True)).passed


def test_invalid_source_and_unrecorded_or_changed_crop_rejected():
    with pytest.raises(ValueError, match="Invalid submodel source"):
        record_charge_policy(psf([-.47]), psf([-.47]))
    with pytest.raises(ValueError, match="recorded charge policy"):
        charge_policy({"submodel": {"version": 2}}, psf([-1]))
    policy = record_charge_policy(psf([-.47, -.53]), psf([-.47]))
    with pytest.raises(ValueError, match="does not match"):
        charge_policy({"submodel": {"charge_policy": policy}}, psf([-.53]))
    bad = copy.deepcopy(policy)
    bad["residual_charge_e"] = 0
    with pytest.raises(ValueError, match="accounting"):
        charge_policy({"submodel": {"charge_policy": bad}}, psf([-.47]))
    assert charge_policy({}, psf([-1])) is None
    assert audit_options(None) == {}


@pytest.mark.parametrize("charge", [-386.47, -386.53, -386.0])
@pytest.mark.parametrize("mg", [0, 12.5])
def test_counterions_leave_only_nearest_integer_residual(charge, mg):
    ions = ion_counts(33000, charge, box_nm=(10, 10, 10), nacl_mM=0, mgcl2_mM=mg)
    assert charge + ions.n_na + 2 * ions.n_mg - ions.n_cl == pytest.approx(charge - round(charge))


def test_package_passes_fractional_crop_to_solvation_only_with_receipt(monkeypatch):
    from backend.core.models import Design
    from backend.core.namd_topology import CharmmTopologyBuild
    from backend.core import namd_solvate

    class ReachedSolvation(Exception):
        pass

    def solvate(*args, **kwargs):
        raise ReachedSolvation

    monkeypatch.setattr(namd_solvate, "_gmx_solvate", solvate)
    crop = psf([-.47, -1])
    policy = record_charge_policy(psf([-.47, -1, -.53]), crop)
    top = CharmmTopologyBuild(pdb_text="END\n", psf_text=crop, metadata={})
    with pytest.raises(RuntimeError, match="not close to an integer"):
        namd_solvate.build_namd_solvated_package(Design(), topology_override=top, require_full_topology=True)
    top.metadata["submodel"] = {"charge_policy": policy}
    with pytest.raises(ReachedSolvation):
        namd_solvate.build_namd_solvated_package(Design(), topology_override=top, require_full_topology=True)
