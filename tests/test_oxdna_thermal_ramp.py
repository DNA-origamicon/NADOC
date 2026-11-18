"""Protocol/control tests only: no native simulation or authored molecular artifacts."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.core.oxdna_protocol import build_production_stage
from backend.core.oxdna_thermal_ramp import (
    ThermalRamp, advance, ramp_stages, reset_copy, sampling_cadence,
)


def stage():
    return build_production_stage(steps=10000, backend="CPU", device="0", salt_concentration=0.5)


@pytest.mark.parametrize("start,end,step,expected", [(25, 36, 5, [25, 30, 35, 36]), (36, 25, 5, [36, 31, 26, 25]), (25, 25, 5, [25]), (25.4, 25.7, .1, [25.4, 25.5, 25.6, 25.7])])
def test_schedule(start, end, step, expected):
    cfg = ThermalRamp(start_c=start, end_c=end, step_c=step)
    assert cfg.block_steps == 100_000_000 and not cfg.gate
    assert sampling_cadence(cfg) == 50_000
    assert cfg.temperatures() == pytest.approx(expected)
    specs = ramp_stages(replace(stage(), interaction="CpdDNA2", dt=0.0001, forces_file="frozen.txt", external_forces=True), cfg)
    assert [float(s.temperature[:-1]) for s in specs] == pytest.approx([t + 273.15 for t in expected])
    assert all(s.dt == 0.0001 and s.interaction == "CpdDNA2" and s.forces_file == "frozen.txt" for s in specs)
    assert all(s.min_bp_retained == 0 and s.max_backbone_force is None for s in specs)


@pytest.mark.parametrize("kwargs", [{"step_c": 0}, {"start_c": float("nan")}, {"step_c": .01}, {"block_steps": 999}, {"block_steps": 10000000001}, {"block_steps": 1000.5}])
def test_invalid_schedule(kwargs):
    with pytest.raises(ValidationError):
        ThermalRamp(**kwargs)




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






def test_reconciliation_cannot_bypass_an_unchecked_temperature(tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import OxdnaStatus
    specs = ramp_stages(stage(), ThermalRamp(block_steps=1_000_000, end_c=25))
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
    specs = ramp_stages(stage(), ThermalRamp(block_steps=1_000_000, end_c=25))
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
    spec = ramp_stages(stage(), ThermalRamp(block_steps=1_000_000, end_c=25))[0]
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
    spec = replace(ramp_stages(stage(), ThermalRamp(block_steps=1_000_000, end_c=25))[0], seed=12345)
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


def test_energy_uses_all_available_samples_without_a_tail_limit(tmp_path):
    from backend.core.oxdna_thermal_ramp import evaluate
    cfg = ThermalRamp(check_pairing=False)
    # Small stationary fluctuations, strongly correlated within groups of 5.
    values = np.tile(np.repeat([-.001, .001], 5), 60)
    (tmp_path / 'energy.dat').write_text('\n'.join(f'{i+1} {v}' for i, v in enumerate(values)))
    short = evaluate(tmp_path, None, cfg, evaluated_steps=cfg.block_steps)
    long = evaluate(tmp_path, None, cfg, evaluated_steps=cfg.max_steps)
    assert short['energy']['status'] == 'recorded'
    assert long['energy']['status'] == 'recorded'
    assert short['energy']['samples'] == 600
    assert long['energy']['samples'] == 600
    import json
    assert json.loads((tmp_path / 'thermal_energy_curve.json').read_text())['fit'] is None
    (tmp_path / 'energy.dat').write_text('\n'.join(f'{i+1} {v}' for i, v in enumerate(np.linspace(0, 1, 600))))
    assert evaluate(tmp_path, None, cfg, evaluated_steps=cfg.max_steps)['energy']['maximum'] == 1






def test_resume_route_rejects_retired_extension_without_mutating_history(tmp_path, monkeypatch):
    import asyncio
    import json
    from dataclasses import asdict
    import backend.api.routes_oxdna as routes
    from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
    from backend.core.oxdna_thermal_resume import ThermalResumeRequest
    cfg = ThermalRamp(block_steps=1_000_000, end_c=25, max_steps=2000000)
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
    from fastapi import HTTPException
    with pytest.raises(HTTPException, match='removed'):
        asyncio.run(routes.start_oxdna_job(job.job_id, ThermalResumeRequest(thermal_max_steps=4000000)))
    restored = OxdnaJob.load(job.job_id, tmp_path)
    assert restored.status == OxdnaStatus.failed
    assert restored.stages[0].steps == 2000000
    assert not launched
    assert evidence.read_text() == 'preserve this sampling history'




@pytest.mark.parametrize('legacy_gate', [False, True])
def test_fixed_duration_advances_regardless_of_observations(tmp_path, monkeypatch, legacy_gate):
    import backend.core.oxdna_thermal_ramp as ramp
    monkeypatch.setattr(ramp, 'evaluate', lambda *args, **kwargs: {'energy': {'status': 'recorded', 'maximum': 1000}})
    cfg = ThermalRamp(block_steps=1000000, gate=legacy_gate, max_steps=1000, min_effective_samples=900)
    specs = ramp_stages(stage(), cfg)
    job = fake_job(tmp_path, specs[0])
    job.run_config = {'thermal_progress': {'1_thermal': {'decision': 'failed', 'gate_version': 3}}}
    before_steps = [s.steps for s in specs]
    assert advance(job, tmp_path, specs, 0, None) == 'done'
    assert advance(job, tmp_path, specs, 0, None) == 'done'
    assert [s.steps for s in specs] == before_steps
    report = job.run_config['thermal_progress']['1_thermal']
    assert report['gate_enabled'] is False and report['stability_status'] == 'not_assessed'
    assert report['previous_decision']['decision'] == 'failed'
    assert set(cfg.model_dump()) == {'start_c', 'end_c', 'step_c', 'block_steps'}
    assert not cfg.gate
    assert all(s.steps == 1000000 for s in specs)
    reset_copy(specs, job.run_config)
    assert 'thermal_progress' not in job.run_config


def test_energy_diagnostic_errors_cannot_stop_or_extend_stage(tmp_path, monkeypatch):
    import backend.core.oxdna_thermal_ramp as ramp
    def unavailable(*args, **kwargs):
        raise ValueError('unreadable energy')
    monkeypatch.setattr(ramp, 'evaluate', unavailable)
    specs = ramp_stages(stage(), ThermalRamp(block_steps=1000000))
    job = fake_job(tmp_path, specs[0])
    assert advance(job, tmp_path, specs, 0, None) == 'done'
    assert job.status == 'running' and job.error is None
    assert specs[0].steps == 1000000
    assert job.run_config['thermal_progress']['1_thermal']['metrics']['energy']['status'] == 'unavailable'


def test_recording_energy_never_requires_exponential_fit(tmp_path, monkeypatch):
    import backend.core.oxdna_energy_fit as fitting
    from backend.core.oxdna_thermal_ramp import evaluate
    monkeypatch.setattr(fitting, 'fit_energy', lambda *args: pytest.fail('No automatic exponential fitting'))
    (tmp_path / 'energy.dat').write_text('0 -2\n1 -1\n2 10\n')
    metrics = evaluate(tmp_path, None, ThermalRamp())
    assert metrics['energy']['samples'] == 3
    assert metrics['energy']['minimum'] == -2
    assert metrics['energy']['maximum'] == 10
    assert 'passed' not in metrics


def test_literature_defaults_render_sequence_dependent_inputs_and_allow_overrides(tmp_path):
    from backend.api.routes_oxdna import RunRequest
    from backend.core.oxdna_thermal_ramp import literature_stage_defaults
    from backend.core.oxdna_protocol import apply_stage_overrides, render_stage_input, AVERAGE_SEQUENCE_PATH
    from backend.core.runpod_oxdna import stage_inputs
    cfg = ThermalRamp()
    RunRequest(steps=cfg.block_steps, thermal_ramp=cfg)
    base = stage()
    preset = literature_stage_defaults(base)
    assert base.salt_concentration == .5 and not base.sequence_dependent
    assert (preset.dt, preset.thermostat, preset.newtonian_steps, preset.diff_coeff) == (.005, 'brownian', 100, 2.5)
    assert preset.salt_concentration == .5 and preset.sequence_dependent
    custom = apply_stage_overrides([preset], {preset.name: {'salt_concentration': .3, 'dt': .002}})[0]
    plateaus = ramp_stages(custom, cfg)
    assert all(s.steps == 100_000_000 and s.salt_concentration == .3 and s.dt == .002 for s in plateaus)
    source = AVERAGE_SEQUENCE_PATH.with_name('oxDNA2_sequence_dependent_parameters.txt')
    text = render_stage_input(plateaus[0], 'topology.top', 'conf.dat')
    assert f'seq_dep_file = {source}' in text
    assert 'thermostat = brownian' in text and 'newtonian_steps = 100' in text
    remote = stage_inputs(tmp_path, plateaus[:1], '/remote/job')
    assert remote[source.name] == source.read_text()
    assert f'seq_dep_file = /remote/job/{source.name}' in remote['1_thermal/input.txt']
