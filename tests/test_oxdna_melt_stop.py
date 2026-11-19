from types import SimpleNamespace

import pytest

from backend.core.oxdna_melt_stop import pairing_output, pairing_summary, prune_after_melt


def test_native_pairing_counts_bases_not_bonds_and_preserves_restart_offsets(tmp_path):
    topology = tmp_path / 'topology.top'
    topology.write_text('5 3\n1 A -1 1\n1 C 0 -1\n2 T -1 3\n2 G 2 -1\n-1 A -1 -1\n')
    (tmp_path / 'thermal_pairing_0.dat').write_text('# step 0\n0 2\n1 3\n\n# step 10\n0 2\n0 3\n\n# step 30\n\n')
    (tmp_path / 'thermal_pairing_20.dat').write_text('# step 0\n0 2\n\n# step 10\n\n# step 20\n')
    r = pairing_summary(tmp_path, topology, .5)
    assert r['dna_bases'] == 4 and r['samples'] == 4
    assert r['first_crossing'] == {'step': 20, 'unpaired_fraction': .5}
    assert pairing_summary(tmp_path, topology, 1)['first_crossing']['step'] == 30
    assert r['max_unpaired_fraction'] == 1


def test_missing_or_malformed_observation_cannot_trigger(tmp_path):
    top = tmp_path / 'topology.top'; top.write_text('2 2\n1 A -1 -1\n2 T -1 -1\n')
    assert pairing_summary(tmp_path, top, 1)['first_crossing'] is None
    (tmp_path / 'thermal_pairing_0.dat').write_text('# step 0\nbroken\n\n# step 10\n')
    assert pairing_summary(tmp_path, top, 1)['samples'] == 0


def test_melt_pruning_is_successful_idempotent_and_preserves_current_dwell():
    job = SimpleNamespace(run_config={}, stages=[SimpleNamespace(name=f'{i}_thermal', status=s)
        for i,s in enumerate(['done', 'running', 'pending', 'pending'])])
    report = {'metrics': {'pairing': {'first_crossing': {'step': 50, 'unpaired_fraction': 1}, 'threshold': 1}}}
    prune_after_melt(job, 1, report); prune_after_melt(job, 1, report)
    assert [s.status for s in job.stages] == ['done', 'running', 'skipped', 'skipped']
    assert job.run_config['melt_stop']['step'] == 50


def test_observable_is_opt_in_for_legacy_jobs_and_uses_native_interaction():
    spec = SimpleNamespace(thermal_ramp={}, print_conf_interval_override=10000)
    assert pairing_output(spec) == ''
    spec.thermal_ramp = {'stop_on_unpaired': True}
    assert 'thermal_pairing_50000.dat' in pairing_output(spec, 50000)
    assert 'type = hb_list' in pairing_output(spec)


@pytest.mark.parametrize('enabled', [True, False])
def test_runner_finishes_dwell_prunes_persists_and_reloads(tmp_path, monkeypatch, enabled):
    import asyncio
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_job import new_oxdna_job, OxdnaJob, OxdnaStatus
    from backend.core.oxdna_protocol import build_production_stage
    from backend.core.oxdna_thermal_ramp import ThermalRamp, ramp_stages, advance, reset_copy
    from backend.core.oxdna_health import OxdnaHealthResult
    specs = ramp_stages(build_production_stage(steps=1000), ThermalRamp(block_steps=1000, end_c=35, stop_on_unpaired=enabled))
    job = new_oxdna_job('melt control fixture', [s.to_status() for s in specs], n_nucleotides=2)
    job.run_config = {'thermal_ramp': specs[0].thermal_ramp}
    root = job.job_dir(tmp_path); root.mkdir(parents=True)
    (root / 'topology.top').write_text('2 2\n1 A -1 -1\n2 T -1 -1\n')
    (root / 'conf.dat').write_text('test input sentinel')
    monkeypatch.setattr(runner, 'find_oxdna', lambda: '/fake/oxDNA')
    monkeypatch.setattr(runner, 'find_dnanalysis', lambda: None)
    monkeypatch.setattr(runner, 'oxdna_supports_physics_v3', lambda _: True)
    monkeypatch.setattr(runner, '_load_snapshot_design', lambda _: object())
    monkeypatch.setattr(runner, 'run_oxdna_health_check', lambda *a, **kw: OxdnaHealthResult(passed=True, fene_safe=True))
    monkeypatch.setattr(runner, 'conf_is_restartable', lambda *a: True)
    calls = []
    async def native(binary, inp, directory, log, jid, on_spawn=None):
        text = inp.read_text()
        assert 'steps = 1000' in text
        assert ('type = hb_list' in text) == enabled
        calls.append(directory.name)
        (directory / 'thermal_pairing_0.dat').write_text('# step 10\n\n# step 1000\n0 1\n\n')
        (directory / 'last_conf.dat').write_text('finished full dwell')
        (directory / 'energy.dat').write_text('5 -1 .3 -.7\n')
        return 0, 123
    monkeypatch.setattr(runner, '_run_oxdna_async', native)
    asyncio.run(runner.run_job(job, tmp_path, specs))
    assert calls == (['1_thermal'] if enabled else ['1_thermal', '2_thermal', '3_thermal'])
    loaded = OxdnaJob.load(job.job_id, tmp_path)
    assert loaded.status == OxdnaStatus.completed
    assert [s.status for s in loaded.stages] == (['done', 'skipped', 'skipped'] if enabled else ['done'] * 3)
    if enabled:
        assert loaded.run_config['melt_stop']['step'] == 10
    else:
        assert 'melt_stop' not in loaded.run_config
    assert loaded.run_config['thermal_progress']['1_thermal']['evaluated_steps'] == 1000
    assert advance(loaded, tmp_path, specs, 0, None) == 'done'
    copied = reset_copy(specs, loaded.run_config)
    assert 'melt_stop' not in loaded.run_config
    assert [s.to_status().status for s in copied] == ['pending'] * 3


def test_legacy_copy_does_not_enable_new_stopping_rule():
    from backend.core.oxdna_protocol import build_production_stage
    from backend.core.oxdna_thermal_ramp import reset_copy
    spec = build_production_stage(steps=1000)
    spec.thermal_ramp = {'start_c': 25, 'end_c': 30, 'step_c': 5, 'block_steps': 1000}
    copied = reset_copy([spec], {'thermal_ramp': spec.thermal_ramp})
    assert copied[0].thermal_ramp['stop_on_unpaired'] is False
