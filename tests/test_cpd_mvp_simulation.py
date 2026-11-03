"""Provisional six-residue chemistry enters NAMD without changing release gates."""

import hashlib
from pathlib import Path

import pytest
from backend.core.cpd_conversion import convert_thymine_pair
from backend.core.cpd_forcefield import (
    CpdCapabilityError,
    assert_cpd_simulation_supported,
    cpd_capability,
    photoproduct_package_assets,
    photoproduct_parameter_directives,
)
from backend.core.models import Design
from backend.core.namd_topology import build_charmm_psfgen_topology
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.namd_topology import charmm_atom_name


def fixture(stereo="cis-syn"):
    d = Design.from_json(Path("tests/fixtures/cpd_six_residue_1xt.nadoc").read_text())
    keys = [f"__xb__:{x.id}:0" for x in d.crossovers if x.extra_bases == "T"]
    return convert_thymine_pair(d, keys, stereo)[0]


@pytest.mark.parametrize(
    "stereo", ["cis-syn", "trans-syn-I", "trans-syn-II", "cis-anti-I"]
)
def test_provisional_topology_and_chiral_hydrogens(stereo):
    d = fixture(stereo)
    assert_cpd_simulation_supported(d, path="NAMD job creation")
    assert not cpd_capability()["available"]
    assets = photoproduct_package_assets(d)
    for a in assets:
        assert hashlib.sha256(a["source_path"].read_bytes()).hexdigest() == a["sha256"]
    directives = photoproduct_parameter_directives(d)
    assert "00_par_all36_cgenff.prm" in directives[0]
    assert directives[1].endswith("/overlay.prm")
    result = build_charmm_psfgen_topology(d)
    audit = result.metadata["photoproduct_static_topology_audit"]
    assert (
        audit["passed"]
        and len(audit["actual_added_bonds"]) == 2
        and not audit["actual_removed_bonds"]
    )
    assert "experimental MVP" in audit["qualification"]
    positions = {
        (l[72:76].strip(), int(l[22:26]), l[12:16].strip()): [
            float(l[j : j + 8]) for j in (30, 38, 46)
        ]
        for l in result.pdb_text.splitlines()
        if l.startswith(("ATOM  ", "HETATM"))
    }
    patch = result.metadata["photoproduct_patch_audit"]["patches"][0]
    definition = load_chemical_definition("TT-CPD", stereo)
    ends = {e["endpoint"]: e for e in patch["endpoints"]}
    refs = {
        r
        for c in definition["product_stereocenters"]
        for r in [c["atom"], *c["signed_volume_reference_atoms"]]
    }
    coords = {}
    for ref in refs:
        e, n = ref.split(":")
        end = ends[int(e)]
        coords[ref] = positions[(end["segid"], end["resid"], charmm_atom_name(n))]
    assert audit_product_chirality(definition, coords)["passed"]


def test_missing_parent_and_mixed_parameter_sets_fail_closed(monkeypatch, tmp_path):
    d = fixture()
    monkeypatch.setenv("NADOC_CGENFF_PARAMETERS", str(tmp_path / "missing.prm"))
    with pytest.raises(CpdCapabilityError, match="pinned CHARMM CGenFF"):
        assert_cpd_simulation_supported(d, path="test")
    monkeypatch.delenv("NADOC_CGENFF_PARAMETERS")
    mixed = d.copy_with(
        photoproduct_junctions=[
            *d.photoproduct_junctions,
            fixture("trans-syn-I").photoproduct_junctions[0],
        ]
    )
    with pytest.raises(CpdCapabilityError, match="one isomer parameter set"):
        assert_cpd_simulation_supported(mixed, path="test")
    lesion = d.photoproduct_junctions[0].model_copy(update={"bond_relaxation": {}})
    with pytest.raises(CpdCapabilityError, match="reviewed six-residue"):
        assert_cpd_simulation_supported(
            d.copy_with(photoproduct_junctions=[lesion]), path="test"
        )


@pytest.mark.parametrize(
    "stereo", ["cis-syn", "trans-syn-I", "trans-syn-II", "cis-anti-I"]
)
@pytest.mark.parametrize("target", ["local", "alpine", "runpod"])
def test_namd_job_creation_accepts_variants_without_scheduling(stereo, target, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from backend.api import state, routes_md
    from backend.api.main import app

    state.set_design(fixture(stereo))
    seen = []

    def prepare(body, **kwargs):
        seen.append(body)
        return SimpleNamespace(to_dict=lambda: {"status": "preparing", "test_only": True})

    monkeypatch.setattr(routes_md, "_spawn_prep_job", prepare)
    response = TestClient(app).post("/api/md/jobs", json={"draft": True, "relax_preset": "design_speed", "execution_target": target})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "preparing"
    assert len(seen) == 1
    assert seen[0].execution_target == target
    assert not seen[0].autostart and not seen[0].draft
    assert not seen[0].fast and not seen[0].relax_hmr
    assert seen[0].relax_timestep_fs == 2.0


def test_cpd_wizard_plan_exposes_supported_integrator():
    from fastapi.testclient import TestClient
    from backend.api import state
    from backend.api.main import app

    state.set_design(fixture())
    client = TestClient(app)
    response = client.post("/api/md/protocol-plan?include_box_preview=false", json={
        "relax_preset": "design_speed", "fast": True,
        "relax_timestep_fs": 4, "relax_hmr": True,
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    for key, value in {"fast": False, "relax_timestep_fs": 2.0, "relax_hmr": False,
                       "production_timestep_fs": 2.0, "production_hmr": False}.items():
        assert plan["request"][key]["value"] == value
        assert plan["request"][key]["provenance"] == "forced"
    # Explicit unsafe API choices still fail; this is not a removed safety gate.
    response = client.post("/api/md/jobs", json={"draft": True, "fast": True})
    assert response.status_code == 400
    assert "conflicting explicit request" in response.text
