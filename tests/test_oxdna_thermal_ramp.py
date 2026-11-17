"""Protocol/control tests only: no native simulation or authored molecular artifacts."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.core.oxdna_protocol import build_production_stage
from backend.core.oxdna_thermal_ramp import (
    ThermalRamp, advance, ramp_stages, reset_copy, sampling_cadence, stability,
)


def stage():
    return build_production_stage(steps=10000, backend="CPU", device="0", salt_concentration=0.5)


@pytest.mark.parametrize("start,end,step,expected", [(25, 36, 5, [25, 30, 35, 36]), (36, 25, 5, [36, 31, 26, 25]), (25, 25, 5, [25]), (25.4, 25.7, .1, [25.4, 25.5, 25.6, 25.7])])
def test_schedule(start, end, step, expected):
    cfg = ThermalRamp(start_c=start, end_c=end, step_c=step)
    assert cfg.temperatures() == pytest.approx(expected)
    specs = ramp_stages(replace(stage(), interaction="CpdDNA2", dt=0.0001, forces_file="frozen.txt", external_forces=True), cfg)
    assert [float(s.temperature[:-1]) for s in specs] == pytest.approx([t + 273.15 for t in expected])
    assert all(s.dt == 0.0001 and s.interaction == "CpdDNA2" and s.forces_file == "frozen.txt" for s in specs)
    assert all(s.min_bp_retained == 0 and s.max_backbone_force is None for s in specs)


@pytest.mark.parametrize("kwargs", [{"step_c": 0}, {"start_c": float("nan")}, {"step_c": .01}, {"max_steps": 1000}, {"min_effective_samples": 30}, {"max_steps": 2500000}])
def test_invalid_schedule(kwargs):
    with pytest.raises(ValidationError):
        ThermalRamp(**kwargs)


def test_stationarity_allows_melting_but_rejects_drift_and_autocorrelation():
    cfg = ThermalRamp()
    assert stability([0] * 60, .02, cfg)["passed"]  # fully melted stable plateau
    assert stability(np.tile([-.005, .005], 30), .02, cfg)["passed"]
    assert not stability(np.linspace(0, 1, 60), .02, cfg)["passed"]
    assert not stability(np.tile(np.linspace(0, .001, 20), 3), .02, cfg)["passed"]
    assert not stability([0] * 59, .02, cfg)["passed"]
    assert not stability([float("nan")] * 60, .02, cfg)["passed"]


def test_cadence_and_thermostat():
    cfg = ThermalRamp()
    cadence = sampling_cadence(cfg, 9876)
    assert cadence <= 9876 and cfg.block_steps % cadence == cfg.max_steps % cadence == 0
    assert cfg.block_steps / cadence >= cfg.window_samples * 3
    with pytest.raises(ValueError, match="thermostat"):
        ramp_stages(replace(stage(), thermostat="no"), cfg)


def fake_job(tmp_path, spec):
    return SimpleNamespace(run_config={}, stages=[spec.to_status()], status="running", error=None,
                           stage_dir=lambda *_: tmp_path, current_stage_idx=0)


def test_gate_extends_then_passes_and_copy_resets(tmp_path, monkeypatch):
    import backend.core.oxdna_thermal_ramp as ramp
    monkeypatch.setattr(ramp, "evaluate", lambda *a, **k: {"passed": True})
    specs = ramp_stages(stage(), ThermalRamp(end_c=25))
    job = fake_job(tmp_path, specs[0])
    assert advance(job, tmp_path, specs, 0, None) == "extend"
    assert specs[0].steps == 2000000 and not specs[0].refresh_vel
    assert advance(job, tmp_path, specs, 0, None) == "done"
    assert advance(job, tmp_path, specs, 0, None) == "done"  # replay does not count twice
    assert job.run_config["thermal_progress"]["1_thermal"]["consecutive_passes"] == 2
    copied = reset_copy(specs, job.run_config)
    assert copied[0].steps == 1000000 and copied[0].refresh_vel
    assert "thermal_progress" not in job.run_config


def test_gate_stops_at_cap_and_fixed_dwell_reports_without_blocking(tmp_path, monkeypatch):
    import backend.core.oxdna_thermal_ramp as ramp
    monkeypatch.setattr(ramp, "evaluate", lambda *a, **k: {"passed": False})
    specs = ramp_stages(stage(), ThermalRamp(end_c=25, max_steps=2000000))
    job = fake_job(tmp_path, specs[0])
    assert advance(job, tmp_path, specs, 0, None) == "extend"
    assert advance(job, tmp_path, specs, 0, None) == "failed"
    assert "not advanced" in job.error and job.current_stage_idx == 0
    specs = ramp_stages(stage(), ThermalRamp(gate=False))
    job = fake_job(tmp_path, specs[0])
    assert advance(job, tmp_path, specs, 0, None) == "done"
    report = job.run_config['thermal_progress']['1_thermal']
    assert report['metrics']['passed'] is False
    assert report['gate_enabled'] is False
    assert report['stability_status'] == 'not_demonstrated'
    assert job.status == 'running' and job.error is None


def test_reconciliation_cannot_bypass_an_unchecked_temperature(tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus
    specs = ramp_stages(stage(), ThermalRamp(end_c=25))
    job = fake_job(tmp_path, specs[0])
    job.job_id = 'thermal-test'
    job.archived = False
    job.job_dir = lambda *_: tmp_path
    job.save = lambda *_: None
    job.status = OxdnaStatus.stopped
    monkeypatch.setattr(runner.runtime, 'is_owned', lambda *_: False)
    monkeypatch.setattr(runner, '_stage_energy_lines', lambda *_: 100000)
    (tmp_path / 'last_conf.dat').touch()  # existence stub, never parsed
    runner.reconcile_oxdna_status(job, tmp_path, specs)
    assert job.status == OxdnaStatus.stopped
    assert job.stages[0].status != 'done'
    job.run_config = {'thermal_progress': {'1_thermal': {'decision': 'done'}}}
    runner.reconcile_oxdna_status(job, tmp_path, specs)
    assert job.status == OxdnaStatus.completed


def test_numerical_retry_discards_gate_evidence_and_archives_samples(tmp_path):
    from backend.core.oxdna_thermal_ramp import restart_plateau
    specs = ramp_stages(stage(), ThermalRamp(end_c=25))
    specs[0] = replace(specs[0], steps=3000000)
    job = fake_job(tmp_path, specs[0])
    job.production_retries = 1
    job.run_config = {'thermal_progress': {'1_thermal': {'consecutive_passes': 1}}}
    for name in ('energy.dat', 'energy.r1.dat', 'thermal_check.json', 'error_conf.dat'):
        (tmp_path / name).write_text('test sentinel')
    restart_plateau(job, tmp_path, specs, 0)
    assert specs[0].steps == 1000000 and specs[0].refresh_vel
    assert not job.run_config['thermal_progress']
    assert not list(tmp_path.glob('energy*.dat'))
    assert not (tmp_path / 'error_conf.dat').exists()
    assert (tmp_path / 'thermal_retry_1/energy.r1.dat').read_text() == 'test sentinel'


def test_edit_rejects_silent_plateau_overrides_and_unsupported_runner(tmp_path):
    from fastapi import HTTPException
    from backend.core.oxdna_thermal_ramp import require_full_system, validate_edit
    spec = ramp_stages(stage(), ThermalRamp(end_c=25))[0]
    job = fake_job(tmp_path, spec)
    validate_edit(job, {'thermal_ramp': None, 'stages': [{'name': spec.name, 'kind': spec.kind, 'steps': spec.steps}]})
    with pytest.raises(HTTPException, match='generated thermal'):
        validate_edit(job, {'stages': [{'name': spec.name, 'temperature': '310K'}]})
    with pytest.raises(HTTPException, match='deposition'):
        validate_edit(job, {'surface_deposition': True})
    with pytest.raises(HTTPException, match='full-system'):
        require_full_system(ThermalRamp(), {'box': True})
    require_full_system(None, {'box': True})


def test_hardware_edits_survive_rebuild_including_cpd_cuda():
    from fastapi import HTTPException
    from backend.core.oxdna_thermal_ramp import apply_edit_hardware
    source = SimpleNamespace(run_config={'thermal_ramp': ThermalRamp().model_dump()}, backend='CPU', device='0', salt_concentration=.5)
    prepared = SimpleNamespace(run_config={})
    specs = [replace(stage(), interaction='CpdDNA2')]
    apply_edit_hardware(prepared, source, {'backend': 'CUDA', 'device': '1', 'salt_concentration': .25}, specs)
    assert prepared.backend == specs[0].backend == 'CUDA'
    assert prepared.device == specs[0].device == '1'
    assert prepared.salt_concentration == specs[0].salt_concentration == .25
    with pytest.raises(HTTPException, match='positive finite'):
        apply_edit_hardware(prepared, source, {'salt_concentration': float('nan')}, specs)


def test_fixed_dwell_does_not_require_a_hidden_gate_budget():
    cfg = ThermalRamp(gate=False, block_steps=20000000)
    specs = ramp_stages(stage(), cfg)
    assert specs[0].steps == 20000000
    assert sampling_cadence(cfg, 10000) == 10000


def test_extensions_and_retries_use_reproducible_distinct_noise(tmp_path):
    from backend.core.oxdna_thermal_ramp import prepare_attempt
    spec = replace(ramp_stages(stage(), ThermalRamp(end_c=25))[0], seed=12345)
    job = fake_job(tmp_path, spec)
    job.random_seed = 12345
    job.production_retries = 0
    assert prepare_attempt(spec, job, tmp_path, 0).seed == 12345
    job.stages[0].completed_steps = 1000000
    extended = prepare_attempt(spec, job, tmp_path, 0)
    assert extended.seed != spec.seed
    assert prepare_attempt(spec, job, tmp_path, 0).seed == extended.seed
    job.production_retries = 1
    assert prepare_attempt(spec, job, tmp_path, 0).seed not in {extended.seed, spec.seed}
    assert len(list(tmp_path.glob('thermal_attempt_*.json'))) == 3


def test_extensions_accumulate_correlated_evidence_without_relaxing_gate(tmp_path):
    from backend.core.oxdna_thermal_ramp import evaluate
    cfg = ThermalRamp(check_pairing=False)
    # Small stationary fluctuations, strongly correlated within groups of 5.
    values = np.tile(np.repeat([-.001, .001], 5), 60)
    (tmp_path / 'energy.dat').write_text('\n'.join(f'{i+1} {v}' for i, v in enumerate(values)))
    short = evaluate(tmp_path, None, cfg, evaluated_steps=cfg.block_steps)
    long = evaluate(tmp_path, None, cfg, evaluated_steps=cfg.max_steps)
    assert not short['passed']
    assert long['passed']
    assert short['energy']['samples'] == 60
    assert long['energy']['samples'] == 600
    assert long['energy']['tolerance'] == cfg.energy_tolerance
    (tmp_path / 'energy.dat').write_text('\n'.join(f'{i+1} {v}' for i, v in enumerate(np.linspace(0, 1, 600))))
    assert not evaluate(tmp_path, None, cfg, evaluated_steps=cfg.max_steps)['passed']


def test_accumulated_evidence_does_not_hide_a_recent_shift():
    from backend.core.oxdna_thermal_ramp import accumulated_stability
    initial = ThermalRamp(check_pairing=False)
    expanded = initial.model_copy(update={'window_samples': 200})
    values = [0.] * 570 + [.04] * 30
    result = accumulated_stability(values, .02, initial, expanded)
    assert result['mean_spread'] < .02
    assert result['recent_mean_spread'] > .02
    assert not result['passed']


def test_explicit_budget_extension_preserves_evidence_and_uses_next_block(tmp_path):
    from backend.core.oxdna_thermal_resume import extend_budget
    cfg = ThermalRamp(end_c=25, max_steps=2000000)
    specs = ramp_stages(stage(), cfg)
    specs[0] = replace(specs[0], steps=cfg.max_steps)
    job = fake_job(tmp_path, specs[0])
    job.status = 'failed'
    job.run_config = {'thermal_ramp': cfg.model_dump(), 'thermal_progress': {'1_thermal': {
        'evaluated_steps': cfg.max_steps, 'decision': 'failed', 'consecutive_passes': 0}}}
    job.stages[0].status = 'failed'
    job.stages[0].started_at = 123
    (tmp_path / 'thermal_check_2000000.json').write_text('original evidence')
    updated = extend_budget(job, specs, 4000000)
    assert updated[0].steps == 3000000
    assert not updated[0].refresh_vel
    assert updated[0].thermal_ramp['max_steps'] == 4000000
    assert job.run_config['thermal_progress']['1_thermal']['decision'] == 'failed'
    assert job.run_config['thermal_budget_changes'][0]['old_max_steps'] == 2000000
    assert job.stages[0].started_at == 123
    assert (tmp_path / 'thermal_check_2000000.json').read_text() == 'original evidence'
    with pytest.raises(ValueError):
        extend_budget(job, updated, 2000000)


def test_resume_route_persists_extended_plan_and_keeps_existing_outputs(tmp_path, monkeypatch):
    import asyncio
    import json
    from dataclasses import asdict
    import backend.api.routes_oxdna as routes
    from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
    from backend.core.oxdna_thermal_resume import ThermalResumeRequest
    cfg = ThermalRamp(end_c=25, max_steps=2000000)
    specs = [replace(ramp_stages(stage(), cfg)[0], steps=2000000)]
    job = new_oxdna_job('thermal resume', [s.to_status() for s in specs], n_nucleotides=0,
                        run_config={'thermal_ramp': cfg.model_dump(), 'thermal_progress': {'1_thermal': {
                            'evaluated_steps': 2000000, 'decision': 'failed'}}})
    job.status = OxdnaStatus.failed
    job.stages[0].status = 'failed'
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / 'stages_spec.json').write_text(json.dumps([asdict(s) for s in specs]))
    evidence = jd / 'sample-evidence.txt'
    evidence.write_text('preserve this sampling history')
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, 'find_oxdna', lambda: 'test-no-launch')
    monkeypatch.setattr(routes, '_submodel_preflight', lambda j, s: s)
    launched = []
    monkeypatch.setattr(routes, 'start_job', lambda j, w, s: launched.append(s))
    asyncio.run(routes.start_oxdna_job(job.job_id, ThermalResumeRequest(thermal_max_steps=4000000)))
    restored = OxdnaJob.load(job.job_id, tmp_path)
    assert restored.status == OxdnaStatus.running
    assert restored.stages[0].steps == 3000000
    assert restored.run_config['thermal_budget_changes'][0]['previous_check']['decision'] == 'failed'
    assert routes.load_stage_specs(jd)[0].thermal_ramp['max_steps'] == 4000000
    assert launched[0][0].steps == 3000000
    assert evidence.read_text() == 'preserve this sampling history'
