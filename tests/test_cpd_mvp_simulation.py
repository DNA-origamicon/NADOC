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
    assert seen[0].fast
    assert seen[0].production_timestep_fs == 4.0


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
    for key, value in {"fast": True, "relax_timestep_fs": 4.0, "relax_hmr": True,
                       "production_timestep_fs": 4.0}.items():
        assert plan["request"][key]["value"] == value
        assert plan["request"][key]["provenance"] != "forced"


def test_unqualified_cpd_retains_integrator_block(monkeypatch):
    from backend.core import cpd_integrator
    from backend.api.routes_md import _apply_photoproduct_integrator_policy
    from backend.api.md_request_models import CreateJobRequest

    monkeypatch.setattr(cpd_integrator, 'design_hmr_qualified', lambda d: False)
    with pytest.raises(CpdCapabilityError, match='conflicting explicit request'):
        _apply_photoproduct_integrator_policy(fixture(), CreateJobRequest(fast=True))
    resolved = _apply_photoproduct_integrator_policy(fixture(), CreateJobRequest())
    assert resolved.fast is False and resolved.production_timestep_fs == 2.0


@pytest.mark.parametrize('qualified', [False, True])
def test_exported_cpd_fast_assets_follow_numerical_qualification(monkeypatch, qualified):
    import io
    import json
    import zipfile
    from backend.core import cpd_integrator, namd_solvate
    from tests.test_md_prep_wiring import _fake_solvate

    monkeypatch.setattr(namd_solvate, '_gmx_solvate', _fake_solvate)
    if not qualified:
        monkeypatch.setattr(cpd_integrator, 'assets_hmr_qualified', lambda a: False)
    blob = namd_solvate.build_namd_solvated_package(
        fixture(), require_full_topology=True, ion_conc_mM=0, mg_conc_mM=0,
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        manifest_name = next(n for n in archive.namelist() if n.endswith('/photoproduct_forcefield_manifest.json'))
        prefix = manifest_name.rsplit('/', 1)[0]+'/'
        manifest = json.loads(archive.read(manifest_name))
        assert manifest['hmr_4fs_enabled'] is qualified
        assert manifest['timestep_fs'] == (4 if qualified else 2)
        assert (prefix+'namd_fast.conf' in archive.namelist()) is qualified
        if qualified:
            conf = archive.read(prefix+'namd_fast.conf').decode()
            assert 'fullElectFrequency 1' in conf
            assert 'mvp_cpds/00_par_all36_cgenff.prm' in conf
            assert 'mvp_cpds/tt-cpd-cis-syn/overlay.prm' in conf
            assert any(n.endswith('_hmr.psf') for n in archive.namelist())
