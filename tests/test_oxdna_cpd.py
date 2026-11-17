"""CPD authoring, projection, and frozen managed-job interaction contracts."""

import json

import numpy as np
import pytest

from backend.physics import oxdna_cpd as cpd
from backend.core.oxdna_protocol import build_relaxation_stages, build_production_stage
from scripts.validate_oxdna_cpd import example


@pytest.fixture(params=list(cpd.MODELS))
def design(request):
    return example(isomer=request.param)


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    directory = tmp_path / "plugin"
    directory.mkdir()
    (directory / "CpdDNA2.so").write_bytes(b"test-only package payload; not executed")
    import hashlib
    from pathlib import Path
    (directory / 'CUDACpdDNA2.so').write_bytes(b'test-only CUDA payload; not executed')
    sources=Path(__file__).resolve().parents[1]/'tools/oxdna_cpd'
    digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (directory / "build.json").write_text(json.dumps({
        'cuda_plugin_sha256':digest(directory/'CUDACpdDNA2.so'),
        'cuda_source_sha256':digest(sources/'CUDACpdDNA2.cu'),
        'cuda_builder_sha256':digest(sources/'build_cuda.py')}))
    monkeypatch.setattr(cpd, "plugin_directory", lambda: directory)
    return directory


def test_assignment_saved_history_replays_from_empty_root(design):
    from scripts.agent_structure_guard import audit

    reopened = type(design).model_validate_json(design.model_dump_json())
    assert audit(reopened)["commands"] == 4
    stereo = reopened.photoproduct_junctions[0].stereochemistry
    assert stereo in cpd.MODELS
    assert reopened.feature_log[-1].params["conversion_version"] == (
        2 if stereo == "cis-syn" else 3
    )


def test_frozen_weld_survives_production_and_copy(design, plugin, tmp_path):
    stages = build_relaxation_stages(backend="CUDA")
    parent = tmp_path / "parent"
    parent.mkdir()
    from backend.physics.oxdna_interface import write_topology

    write_topology(design, parent / "topology.top")
    manifest = cpd.prepare(design, parent, stages)
    assert manifest["endpoints"][0]["particles"] == [6, 7]
    isomer = design.photoproduct_junctions[0].stereochemistry
    assert manifest["endpoints"][0]["stereochemistry"] == isomer
    assert (parent / "cpd_model.json").read_bytes() == cpd.MODELS[isomer].read_bytes()
    assert all(s.backend == ("CPU" if s.sim_type == "MC" else "CUDA") and s.interaction == "CpdDNA2" for s in stages)
    child = tmp_path / "child"
    child.mkdir()
    (child / "topology.top").write_bytes((parent / "topology.top").read_bytes())
    production = build_production_stage(backend="CUDA")
    cpd.inherit(parent, child, [production])
    assert production.backend == "CUDA" and production.dt == 0.0001
    assert not production.external_forces
    for name in cpd.FILES:
        assert (parent / name).read_bytes() == (child / name).read_bytes()
    assert str(child / "cpd.dat") in cpd.stage_input(child, production)
    (child / "cpd.dat").write_text("lost weld")
    with pytest.raises(ValueError, match="changed"):
        cpd.stage_input(child, production)


def test_projection_preserves_frozen_physical_frames(design):
    from backend.core.design_geometry import _geometry_for_design
    from backend.physics.oxdna_interface import resolved_nuc_map, oxdna_native_seed_map

    mapped = resolved_nuc_map(design, _geometry_for_design(design))
    welded = [n for n in mapped.values() if n.get("cpd_particle_frame")]
    assert len(welded) == 2
    for n in welded:
        assert np.dot(n["base_normal"], n["axis_tangent"]) == pytest.approx(
            0, abs=1e-12
        )
        assert "helical_site" not in n
    shifted = oxdna_native_seed_map(design, mapped)
    for key, n in mapped.items():
        if n.get("cpd_particle_frame"):
            np.testing.assert_array_equal(
                n["backbone_position"], shifted[key]["backbone_position"]
            )
    assert cpd.physical_geometry(design, welded) is welded


def test_missing_models_never_silently_run_as_ordinary_dna(
    design, plugin, tmp_path, monkeypatch
):
    monkeypatch.setattr(cpd, "MODELS", {})
    with pytest.raises(ValueError, match="No fitted"):
        cpd.prepare(design, tmp_path, build_relaxation_stages())


@pytest.mark.parametrize("isomer", list(cpd.MODELS))
def test_fit_has_six_positive_modes_and_documented_limits(isomer):
    model = json.loads(cpd.MODELS[isomer].read_text())
    assert model["stereochemistry"] == isomer
    parameters = model["parameters"]
    assert np.linalg.eigvalsh(parameters["hessian"]).min() > 0
    assert len(parameters["stiffness"]) == 16
    assert parameters["sample_count"] == 300
    assert not set(model["fit_replicas"]) & set(model["validation_replicas"])
    assert model["validation_is_blind"] is False
    assert "not validated melting" in model["qualification"]


def test_projection_is_rigid_motion_equivariant():
    from scipy.spatial.transform import Rotation
    from backend.physics.oxdna_cpd_fit import particle_frame, relative_pose

    atoms = np.array(
        [
            [0, 0, 0],
            [1, 1, 0],
            [2, 1, 0],
            [3, 0, 0],
            [2, -1, 0],
            [1, -1, 0],
            [-1, 0, 0],
        ],
        float,
    )
    b = atoms + np.array([0, 0, 4])
    r = Rotation.from_rotvec([0.3, -0.4, 0.1]).as_matrix()
    shift = np.array([8, 2, 1])
    p, q = relative_pose(particle_frame(atoms), particle_frame(b))
    pp, qq = relative_pose(
        particle_frame(atoms @ r.T + shift), particle_frame(b @ r.T + shift)
    )
    np.testing.assert_allclose(p, pp, atol=1e-12)
    np.testing.assert_allclose(q, qq, atol=1e-12)


def test_mixed_isomers_keep_distinct_per_lesion_parameters(plugin, tmp_path):
    from backend.api.feature_recording import record_feature
    from backend.api.part_proof_commands import execute
    from backend.api.state import _DesignSession
    from backend.core.part_cpd_conversion_isomers import prepare
    from backend.physics.oxdna_interface import write_topology
    from scripts.agent_structure_guard import audit

    session = _DesignSession(design=example(sequence="GCGCGCTTGCTTGCGC"))
    params = prepare(
        [f"38b9786d-4dcf-4a62-92a6-c90bc301961b:{i}:FORWARD" for i in (10, 11)],
        "d1c84d5e-cdb3-4ead-942b-b1bb96573efa",
        "trans-syn-II",
    )
    record_feature(
        session,
        "photoproduct-create",
        "Assign second TT pair",
        params,
        lambda d: execute("photoproduct-create", d, params),
    )
    assert audit(session.design)["commands"] == 5
    write_topology(session.design, tmp_path / "topology.top")
    manifest = cpd.prepare(session.design, tmp_path, build_relaxation_stages())
    assert [e["stereochemistry"] for e in manifest["endpoints"]] == [
        "cis-syn",
        "trans-syn-II",
    ]
    bundle = json.loads((tmp_path / "cpd_model.json").read_text())
    assert set(bundle["models"]) == {"cis-syn", "trans-syn-II"}
    lines = (tmp_path / "cpd.dat").read_text().splitlines()
    assert lines[1] == "6 7 16" and lines[18] == "10 11 16"
    for offset, stereo in [(2, "cis-syn"), (19, "trans-syn-II")]:
        springs = [float(line.split()[-1]) for line in lines[offset : offset + 16]]
        assert springs == bundle["models"][stereo]["parameters"]["stiffness"]


def test_model_identity_mismatch_is_rejected(design, plugin, tmp_path, monkeypatch):
    isomer = design.photoproduct_junctions[0].stereochemistry
    other = next(key for key in cpd.MODELS if key != isomer)
    monkeypatch.setattr(cpd, "MODELS", {isomer: cpd.MODELS[other]})
    with pytest.raises(ValueError, match="identity"):
        cpd.prepare(design, tmp_path, build_relaxation_stages())


def test_gpu_backend_change_preserves_checkpoint_and_gate(design, plugin, tmp_path):
    from dataclasses import asdict
    from backend.core.oxdna_job import new_oxdna_job, OxdnaJob, OxdnaStatus
    from backend.core.oxdna_cpd_backend import change_backend
    from backend.physics.oxdna_interface import write_topology
    from backend.core.oxdna_runner import load_stage_specs
    specs=[build_production_stage(backend='CPU')]
    job=new_oxdna_job('CPD switch',[s.to_status() for s in specs],backend='CPU',run_config={'thermal_progress':{'preserved':True}})
    job.status=OxdnaStatus.stopped;job.save(tmp_path)
    jd=job.job_dir(tmp_path);write_topology(design,jd/'topology.top')
    cpd.prepare(design,jd,specs)
    (jd/'stages_spec.json').write_text(json.dumps([asdict(s) for s in specs]))
    checkpoint=jd/'checkpoint-sentinel';checkpoint.write_bytes(b'unchanged')
    change_backend(job,tmp_path,'CUDA')
    loaded=OxdnaJob.load(job.job_id,tmp_path)
    assert loaded.backend=='CUDA' and loaded.status==OxdnaStatus.stopped
    assert loaded.run_config['thermal_progress']=={'preserved':True}
    assert loaded.run_config['backend_changes'][0]['from']=='CPU'
    assert load_stage_specs(jd)[0].backend=='CUDA'
    assert cpd.verify(jd)['cuda_plugin_sha256']
    assert checkpoint.read_bytes()==b'unchanged'
    change_backend(loaded,tmp_path,'CUDA')
    assert len(loaded.run_config['backend_changes'])==1
    loaded.status=OxdnaStatus.running
    with pytest.raises(ValueError,match='Stop'):
        change_backend(loaded,tmp_path,'CPU')


def test_missing_or_tampered_gpu_plugin_never_falls_back(design, plugin, tmp_path):
    from backend.physics.oxdna_interface import write_topology
    write_topology(design,tmp_path/'topology.top')
    specs=[build_production_stage(backend='CUDA')]
    cpd.prepare(design,tmp_path,specs)
    (tmp_path/'cpd_plugin/CUDACpdDNA2.so').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='CUDA plugin changed'):
        cpd.stage_input(tmp_path,specs[0])
    assert specs[0].backend=='CUDA'
