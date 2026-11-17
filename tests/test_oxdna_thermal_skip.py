"""Skip is an explicit partial-stage handoff, not an equilibrium acceptance."""
import json
from dataclasses import replace

import pytest

from backend.core.oxdna_job import OxdnaJob, OxdnaStageStatus, OxdnaStatus
from backend.core.oxdna_protocol import build_production_stage
from backend.core.oxdna_thermal_ramp import ramp_stages
from backend.core.oxdna_thermal_skip import apply_skip, validate_skip, execute


@pytest.fixture
def plateau(tmp_path):
    cfg = {'start_c': 25, 'end_c': 35, 'block_steps': 1000, 'max_steps': 2000, 'gate': False}
    specs = ramp_stages(replace(build_production_stage(), steps=1000), cfg)
    job = OxdnaJob(job_id='skip-test', design_name='test', status=OxdnaStatus.stopped,
                   created_at=1, n_nucleotides=1, run_config={'thermal_ramp': cfg},
                   stages=[OxdnaStageStatus(s.name, s.kind, s.steps) for s in specs])
    directory = job.job_dir(tmp_path)
    directory.mkdir(parents=True)
    from backend.core.oxdna_runner import _persist_specs
    _persist_specs(job, tmp_path, specs)
    stage = job.stage_dir(tmp_path, specs[0].name)
    stage.mkdir()
    conf = 't = 0\nb = 10 10 10\nE = 0 0 0\n' + ' '.join(['0'] * 15) + '\n'
    (stage / 'last_conf.dat').write_text(conf)
    (stage / 'energy.dat').write_text('0 -1\n1 -2\n')
    (stage / 'input.txt').write_text('T = 25C\n')
    job.save(tmp_path)
    return job, specs, stage


def request(stage='1_thermal', generation=None):
    return {'stage': stage, 'request_id': 'request-test', 'requested_at': 1, 'generation': generation}


def test_skip_preserves_data_checkpoint_and_does_not_claim_stability(plateau, tmp_path):
    job, specs, directory = plateau
    before = (directory / 'energy.dat').read_bytes(), (directory / 'last_conf.dat').read_bytes()
    apply_skip(job, tmp_path, request())
    saved = OxdnaJob.load(job.job_id, tmp_path)
    assert saved.current_stage_idx == 1
    assert saved.stages[0].status == 'skipped'
    assert saved.run_config['thermal_progress']['1_thermal']['decision'] == 'skipped'
    assert saved.run_config['thermal_progress']['1_thermal']['stability_status'] == 'manually_skipped'
    assert before == ((directory / 'energy.dat').read_bytes(), (directory / 'last_conf.dat').read_bytes())
    from backend.core.oxdna_runner import _starting_conf, reconcile_oxdna_status
    assert _starting_conf(saved, tmp_path, specs, 1, 1) == (directory / 'last_conf.dat').resolve()
    reconcile_oxdna_status(saved, tmp_path, specs)
    assert saved.current_stage_idx == 1 and saved.stages[0].status == 'skipped'


def test_missing_checkpoint_cannot_skip(plateau, tmp_path):
    job, _, directory = plateau
    (directory / 'last_conf.dat').unlink()
    with pytest.raises(ValueError, match='valid saved configuration'):
        apply_skip(job, tmp_path, request())
    assert job.current_stage_idx == 0


def test_stale_final_and_nonthermal_requests_rejected(plateau):
    job, _, _ = plateau
    with pytest.raises(ValueError, match='changed'):
        validate_skip(job, '2_thermal')
    job.current_stage_idx = 2
    with pytest.raises(ValueError, match='final'):
        validate_skip(job, '3_thermal')
    job.run_config = {}
    with pytest.raises(ValueError, match='not a thermal'):
        validate_skip(job, '3_thermal')


def test_controller_handoff_and_idempotent_stale_request(plateau, tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner
    job, _, _ = plateau
    started = []
    monkeypatch.setattr(runner, 'stop_job', lambda *args: True)
    monkeypatch.setattr(runner, 'start_job', lambda j, ws, specs: started.append((j.current_stage_idx, specs[1].temperature)))
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request()))
    execute(tmp_path, job.job_id, path)
    assert started == [(1, '303.15K')]
    assert json.loads(path.read_text())['state'] == 'applied'
    # Replaying the old request must never skip the new temperature.
    with pytest.raises(ValueError, match='changed'):
        execute(tmp_path, job.job_id, path)
    assert OxdnaJob.load(job.job_id, tmp_path).current_stage_idx == 1
    assert len(started) == 1


def test_natural_completion_race_does_not_skip_next_temperature(plateau, tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner
    job, _, _ = plateau
    started = []
    def stop(*args):
        job.current_stage_idx = 1
        job.stages[0].status = 'done'
        job.save(tmp_path)
    monkeypatch.setattr(runner, 'stop_job', stop)
    monkeypatch.setattr(runner, 'start_job', lambda j, *args: started.append(j.current_stage_idx))
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request()))
    execute(tmp_path, job.job_id, path)
    assert started == [1]
    assert OxdnaJob.load(job.job_id, tmp_path).stages[0].status == 'done'
    assert json.loads(path.read_text())['state'] == 'already_advanced'


def test_skip_before_first_output_uses_incoming_configuration(plateau, tmp_path):
    job, _, directory = plateau
    checkpoint = directory / 'last_conf.dat'
    (job.job_dir(tmp_path) / 'conf.dat').write_bytes(checkpoint.read_bytes())
    checkpoint.unlink()
    apply_skip(job, tmp_path, request())
    report = job.run_config['thermal_progress']['1_thermal']
    assert report['evaluated_steps'] == 0
    assert 'incoming' in report['checkpoint']
    assert checkpoint.exists()


def test_later_stop_cancels_pending_skip(plateau, tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_thermal_skip import cancel_skip
    job, _, _ = plateau
    directory = job.job_dir(tmp_path)
    (directory / '.thermal-skip.lock').touch()
    monkeypatch.setattr(runner, 'stop_job', lambda *args: cancel_skip(directory))
    monkeypatch.setattr(runner, 'start_job', lambda *args: pytest.fail('Stop must win'))
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request()))
    execute(tmp_path, job.job_id, path)
    assert json.loads(path.read_text())['state'] == 'cancelled'
    assert OxdnaJob.load(job.job_id, tmp_path).current_stage_idx == 0


def test_duplicate_command_is_rejected_before_starting_another_controller(plateau, tmp_path):
    import fcntl
    from backend.core.oxdna_thermal_skip import begin_skip
    job, _, _ = plateau
    with (job.job_dir(tmp_path) / '.thermal-skip.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already in progress'):
            begin_skip(job.job_id, tmp_path, '1_thermal')
    assert not list(job.job_dir(tmp_path).glob('thermal_skip_*.json'))


def test_changed_execution_cannot_stop_or_advance_a_new_run(plateau, tmp_path, monkeypatch):
    from backend.core import oxdna_runner as runner, simulation_runtime
    job, _, _ = plateau
    monkeypatch.setattr(simulation_runtime, 'generation', lambda directory: 'new-generation')
    monkeypatch.setattr(runner, 'stop_job', lambda *args: pytest.fail('Must not stop a new run'))
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request(generation='old-generation')))
    with pytest.raises(ValueError, match='Execution changed'):
        execute(tmp_path, job.job_id, path)
    assert OxdnaJob.load(job.job_id, tmp_path).current_stage_idx == 0


def test_optional_diagnosis_failure_does_not_block_manual_skip(plateau, tmp_path, monkeypatch):
    from backend.core import oxdna_thermal_metrics
    job, _, _ = plateau
    def broken(*args, **kwargs):
        raise ValueError('unreadable historical energy')
    monkeypatch.setattr(oxdna_thermal_metrics, 'energy_observations', broken)
    apply_skip(job, tmp_path, request())
    report = job.run_config['thermal_progress']['1_thermal']
    assert report['decision'] == 'skipped'
    assert report['metrics']['energy']['status'] == 'unavailable'
    assert 'unavailable' in report['metrics']['energy']['reason']


def test_detached_controller_reports_checkpoint_failure_without_starting_engine(plateau, tmp_path):
    from backend.core.oxdna_thermal_skip import begin_skip, wait_skip
    job, _, directory = plateau
    (directory / 'last_conf.dat').unlink()
    accepted = begin_skip(job.job_id, tmp_path, '1_thermal')
    with pytest.raises(ValueError, match='valid saved configuration'):
        wait_skip(job.job_id, tmp_path, accepted['request_id'])
    saved = OxdnaJob.load(job.job_id, tmp_path)
    assert saved.current_stage_idx == 0
    assert saved.oxdna_pid is None
    assert 'Skip to next stage failed' in saved.error
