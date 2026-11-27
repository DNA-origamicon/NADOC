"""Settings detail reports persisted physics instead of contemporary defaults."""
import asyncio
from dataclasses import asdict, replace
import json

from backend.core.oxdna_job import OxdnaJob, new_oxdna_job
from backend.core.oxdna_protocol import build_production_stage


def test_job_detail_includes_recorded_stage_specs(tmp_path, monkeypatch):
    from backend.api import routes_oxdna as routes
    spec = replace(build_production_stage(), dt=.0015, thermostat='bussi',
                   salt_concentration=.3, sequence_dependent=False)
    job = new_oxdna_job('recorded settings', [spec.to_status()])
    job.save(tmp_path)
    (job.job_dir(tmp_path) / 'stages_spec.json').write_text(json.dumps([asdict(spec)]))
    monkeypatch.setattr(routes, '_load_job', lambda _: job)
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, '_job_fingerprint', lambda _: None)
    monkeypatch.setattr(routes, '_current_design_fingerprint', lambda: None)
    result = asyncio.run(routes.get_oxdna_job(job.job_id))
    assert result['stage_specs'] == [asdict(spec)]
    (job.job_dir(tmp_path) / 'stages_spec.json').unlink()
    assert asyncio.run(routes.get_oxdna_job(job.job_id))['stage_specs'] == []


def test_stopped_continuation_requires_saved_frame_and_exited_writer(tmp_path, monkeypatch):
    from backend.api import routes_oxdna as routes
    from backend.core.oxdna_job import OxdnaStatus
    spec = build_production_stage()
    job = new_oxdna_job('stopped continuation', [spec.to_status()])
    job.status = OxdnaStatus.stopped
    job.save(tmp_path)
    monkeypatch.setattr(routes, 'is_running', lambda _: False)
    assert not routes._can_seed_production(job, tmp_path)
    conf = job.stage_dir(tmp_path, spec.name) / 'last_conf.dat'
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.touch()
    assert not routes._can_seed_production(job, tmp_path)
    conf.write_text('saved checkpoint')
    assert routes._can_seed_production(job, tmp_path)
    monkeypatch.setattr(routes, 'is_running', lambda _: True)
    assert not routes._can_seed_production(job, tmp_path)
    monkeypatch.setattr(routes, 'is_running', lambda _: False)
    job.status = OxdnaStatus.failed
    assert not routes._can_seed_production(job, tmp_path)


def test_torque_arrow_size_persists_without_rebuilding_the_job(tmp_path, monkeypatch):
    from backend.api import routes_oxdna as routes

    config = {"kind": "run", "torsion": {"axis": {"kind": "pose", "position_nm": [1, 2, 3]}}}
    job = new_oxdna_job("wheel", [build_production_stage().to_status()],
                       parent_job_id="parent", run_config=config)
    job.save(tmp_path)
    force_file = job.job_dir(tmp_path) / "torsion_forces.txt"
    force_file.write_bytes(b"existing forces")
    monkeypatch.setattr(routes, "_load_job", lambda _: job)
    monkeypatch.setattr(routes, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes, "is_running", lambda _: False)
    updated = asyncio.run(routes.update_oxdna_job_settings(job.job_id, {"torque_arrow_size": 175}))
    expected = {**config, "torque_arrow_size": 175}
    assert updated["run_config"] == expected
    assert OxdnaJob.load(job.job_id, tmp_path).run_config == expected
    assert force_file.read_bytes() == b"existing forces"
