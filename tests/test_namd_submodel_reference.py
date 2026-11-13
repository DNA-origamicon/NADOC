"""Reference-config and ion recipe contracts; parser fixtures only, no engines."""

import json
from types import SimpleNamespace

import pytest

from backend.api.md_request_models import CreateJobRequest
from backend.core.namd_submodel_reference import (
    PHYSICS,
    bind,
    capture,
    resolve_request,
    lookup,
    apply_package_profile,
    directives_text,
)
from backend.core.namd_solvate import ion_counts

BOX = dict(
    min_corner=[0, 0, 0], max_corner=[1, 1, 1], rotation=[0, 0, 0, 1], shell_nm=2
)
PHYSICS_VALUES = dict(
    zip(
        PHYSICS,
        [
            "4",
            "all",
            "1e-8",
            "on",
            "300",
            "1",
            "off",
            "10",
            "on",
            "8",
            "12",
            "scaled1-4",
            "1",
            "yes",
            "1.5",
            "1",
            "1",
            "10",
            "off",
            "on",
        ],
    )
)


@pytest.fixture
def reference(tmp_path):
    root = tmp_path / "reference"
    root.mkdir()
    pkg = root / "package"
    pkg.mkdir()
    # Parser sentinels, not a scientific topology or authored design.
    (root / "design.json").write_text(json.dumps(dict(strands=[], crossovers=[])))
    (root / "job.json").write_text(
        json.dumps(
            dict(
                job_id="whole",
                run_kind="production",
                package_subdir="package",
                design_source_path="toy.nadoc",
                segments=[dict(name="prod")],
            )
        )
    )
    (pkg / "toy_hmr.psf").write_text("PSF\n\n1 !NATOM\n1 ION 1 MGH MG MG 2 24 0\n")
    (pkg / "param.prm").write_text("parameter sentinel")
    (pkg / "prod.conf").write_text(
        "\n".join(f"{k} {v}" for k, v in PHYSICS_VALUES.items())
        + "\nstructure toy_hmr.psf\nparameters param.prm\nextraBondsFile mgh_extrabonds.txt\nconstraints off\nlangevinPiston on\nrun 1000\n"
    )
    ion = dict(
        n_na=0,
        n_cl=0,
        n_mg=1,
        n_mg_bulk=84,
        mg_hexahydrate=True,
        dna_charge_from_psf_e=-2.0,
    )
    (pkg / "charge_audit.json").write_text(json.dumps(dict(ionization=ion)))
    bind(tmp_path, root)
    return tmp_path, root


def test_explicit_zero_salt_magnesium_counterions_and_legacy_sodium():
    args = dict(nacl_mM=0, mgcl2_mM=0, box_nm=(10, 10, 10), mg_hexahydrate=True)
    ions = ion_counts(30000, -386.47, counterion="mg", **args)
    assert (ions.n_mg, ions.n_na, ions.n_cl, ions.n_mg_bulk) == (193, 0, 0, 0)
    odd = ion_counts(30000, -387, counterion="mg", **args)
    assert (odd.n_mg, odd.n_cl) == (194, 1)
    legacy = ion_counts(30000, -386.47, **args)
    assert (legacy.n_mg, legacy.n_na, legacy.n_cl) == (0, 386, 0)
    with pytest.raises(ValueError, match="hexahydrate"):
        ion_counts(10, -2, counterion="mg", **{**args, "mg_hexahydrate": False})


def test_capture_uses_actual_census_not_nominal_legacy_bulk(reference):
    workspace, root = reference
    profile = lookup(workspace, design_path="toy.nadoc")
    assert profile["mgcl2_mM"] == 0 and profile["actual_ion_counts"] == dict(
        mg=1, na=0, cl=0
    )
    path = root / "package/charge_audit.json"
    audit = json.loads(path.read_text())
    audit["ionization"]["n_mg"] = 2
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="census differs"):
        capture(root)


def test_bound_requests_force_all_stage_physics_and_leave_other_designs(reference):
    workspace, _ = reference
    request = CreateJobRequest(
        submodel=BOX,
        design_source_path="toy.nadoc",
        mg_conc_mM=12.5,
        stage_overrides={
            "*": {"langevindamping": "5"},
            "2": {"TIMESTEP": "2", "run": "2500"},
        },
    )
    resolved = resolve_request(request, workspace)
    assert resolved.salt_mode == "custom" and resolved.mg_conc_mM == 0
    assert resolved.relax_hmr and resolved.relax_timestep_fs == 4
    assert resolved.stage_overrides["*"]["langevinDamping"] == "1"
    assert resolved.stage_overrides["2"] == {"run": "2500"}
    assert resolved.submodel_reference_job_id == "whole"
    assert (
        resolve_request(
            CreateJobRequest(submodel=BOX, design_source_path="other.nadoc"), workspace
        ).mg_conc_mM
        == 12.5
    )
    assert (
        resolve_request(
            CreateJobRequest(design_source_path="toy.nadoc"), workspace
        ).submodel_reference_job_id
        is None
    )


def test_changed_reference_refused_and_native_profiles_are_frozen(reference):
    workspace, root = reference
    profile = lookup(workspace, "whole")
    package = root / "package"
    conf = "structure toy.psf\ntimestep 2\nlangevinDamping 5\nrun 2500\n"
    result = directives_text(apply_package_profile(package, conf, profile))
    assert result["structure"] == ["toy_hmr.psf"]
    assert result["run"] == ["2500"] and result["langevindamping"] == ["1"]
    (package / "prod.conf").write_text("changed")
    with pytest.raises(ValueError, match="Reference config changed"):
        lookup(workspace, "whole")
    # Historical embedded profile applies independently of the mutable registry.
    assert directives_text(apply_package_profile(package, conf, profile))[
        "timestep"
    ] == ["4"]
    (package / "param.prm").write_text("changed")
    with pytest.raises(ValueError, match="force-field mismatch"):
        apply_package_profile(package, conf, profile)


def test_preview_matches_bound_damping_and_fixed_volume(reference, monkeypatch):
    from backend.api import routes_md, routes_md_plan

    workspace, _ = reference
    monkeypatch.setattr(routes_md, "_workspace", lambda: workspace)
    monkeypatch.setattr(
        routes_md_plan,
        "_design_flags",
        lambda **kw: dict(
            known=False,
            extra_bases=False,
            extra_base_declash=False,
            extensions=False,
            aspect_ratio=None,
        ),
    )
    request = routes_md_plan.ProtocolPlanRequest(
        submodel=BOX, design_source_path="toy.nadoc", n_atoms_hint=10000
    )
    resolved = routes_md.resolve_relax_preset(request)
    plan = routes_md_plan._relaxation_plan(request, resolved)
    dynamics = [s for s in plan["stages"] if s["params"].get("run")]
    assert dynamics
    for stage in dynamics:
        assert float(stage["params"]["langevindamping"]) == 1
        assert float(stage["params"]["timestep"]) == 4
        assert stage["params"]["langevinpiston"] == "off"
        assert stage["params"].get("gpuresident", "off") == "off"
    provenance = routes_md_plan._provenance(request, resolved)
    assert provenance["mg_conc_mM"]["provenance"] == "forced"


def test_production_plan_inherits_profile_and_refuses_old_ion_package(
    reference, monkeypatch
):
    from backend.api import routes_md
    from fastapi import HTTPException

    workspace, root = reference
    profile = lookup(workspace, "whole")
    package = root / "package"
    manifest = package / "manifest.json"
    manifest.write_text(
        json.dumps(dict(submodel={"version": 2}, submodel_reference=profile))
    )
    job = SimpleNamespace(
        package_dir=lambda ws: package, design_source_path="toy.nadoc"
    )
    monkeypatch.setattr(routes_md, "_workspace", lambda: workspace)
    plan = routes_md._production_fast_plan(
        job, routes_md.ProductionRequest(production_timestep_fs=2, length_ns=1)
    )
    assert plan["timestep_fs"] == 4 and plan["hmr"] and plan["total_steps"] == 250000
    manifest.write_text(json.dumps(dict(submodel={"version": 2})))
    with pytest.raises(HTTPException) as exc:
        routes_md._production_fast_plan(job, routes_md.ProductionRequest(length_ns=1))
    assert exc.value.status_code == 409


def test_package_builder_passes_explicit_counterion_and_records_reference(
    reference, monkeypatch
):
    import io
    import zipfile
    from backend.core import (
        namd_submodel,
        namd_topology,
        namd_solvate,
        namd_submodel_charge,
    )

    workspace, _ = reference
    profile = lookup(workspace, "whole")
    sentinel = SimpleNamespace(psf_text="parser sentinel", pdb_text="parser sentinel")
    monkeypatch.setattr(
        namd_topology, "build_charmm_psfgen_topology", lambda *a, **kw: sentinel
    )
    monkeypatch.setattr(namd_submodel, "crop_topology", lambda *a: (sentinel, {}))
    monkeypatch.setattr(namd_submodel_charge, "record_charge_policy", lambda *a: {})
    seen = {}

    def build(design, **kwargs):
        seen.update(kwargs)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("toy/namd.conf", "config sentinel")
        return buffer.getvalue()

    monkeypatch.setattr(namd_solvate, "build_namd_solvated_package", build)
    design = SimpleNamespace(
        to_json=lambda: json.dumps(dict(strands=[], crossovers=[]))
    )
    result = namd_submodel.package_builder(BOX, reference_profile=profile)(
        design, mg_conc_mM=12.5, mg_hexahydrate=True
    )
    assert (
        seen["counterion"] == "mg"
        and seen["mg_conc_mM"] == 0
        and seen["ion_conc_mM"] == 0
    )
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        assert json.loads(z.read("toy/submodel.json"))["reference_profile"] == profile


def test_historical_view_uses_embedded_profile_not_new_binding(reference, monkeypatch):
    from backend.api.routes_md_plan import ProtocolPlanRequest
    from backend.core.md_job import MdJob

    workspace, root = reference
    package = root / "package"
    profile = lookup(workspace, "whole")
    monkeypatch.setattr(
        MdJob, "load", lambda *a: SimpleNamespace(package_dir=lambda ws: package)
    )
    request = ProtocolPlanRequest(
        saved_job_id="old", design_source_path="toy.nadoc", mg_conc_mM=12.5
    )
    receipt = package / "submodel.json"
    receipt.write_text(json.dumps(dict(box=BOX)))
    result = resolve_request(request, workspace)
    assert result.submodel is not None
    assert result.mg_conc_mM == 12.5 and result.submodel_reference_job_id is None
    receipt.write_text(json.dumps(dict(box=BOX, reference_profile=profile)))
    (package / "prod.conf").write_text("changed source after historical run")
    result = resolve_request(request, workspace)
    assert result.mg_conc_mM == 0 and result.submodel_reference_job_id == "whole"


def test_production_reference_overrides_are_visible_as_forced(reference):
    from backend.api.routes_md_plan import ProtocolPlanRequest, _production_provenance
    from backend.core.md_integrator import resolve_integrator

    workspace, _ = reference
    profile = lookup(workspace, "whole")
    result = _production_provenance(
        ProtocolPlanRequest(
            kind="production", production_timestep_fs=2, langevin_damping=5
        ),
        dict(length_ns=1, timestep_fs=4),
        dict(damping=1, enm_restraints=False, enm_reason="reference"),
        resolve_integrator(4, rigid_bonds="all", hmr=True),
        manifest={"submodel_reference": profile},
    )
    assert result["langevin_damping"]["value"] == 1
    assert result["production_timestep_fs"]["value"] == 4
    for key in (
        "production_timestep_fs",
        "production_rigid_bonds",
        "production_hmr",
        "langevin_damping",
        "enm_restraints",
        "gpu_resident",
    ):
        assert result[key]["provenance"] == "forced"
