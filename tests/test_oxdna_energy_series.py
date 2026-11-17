"""Energy metrics are independent of geometry and keep ramp/resume boundaries."""
from types import SimpleNamespace

from backend.core.oxdna_energy_series import energy_series


def job(tmp_path, names=('warm', 'hot', 'pending')):
    return SimpleNamespace(job_id='j1', stages=[SimpleNamespace(name=n, kind='production') for n in names],
                           stage_dir=lambda ws, name: ws / name)


def write_stage(tmp_path, name, temperature, energy):
    directory = tmp_path / name
    directory.mkdir()
    (directory / 'input.txt').write_text(f'T = {temperature}C\n')
    (directory / 'energy.dat').write_text(energy)
    return directory


def test_ramp_resume_and_pending_stage(tmp_path):
    warm = write_stage(tmp_path, 'warm', 25, '0 -2 .1 -1.9\n10 -3 .1 -2.9\n')
    (warm / 'energy.r1.dat').write_text('0 -1 .1 -.9\n10 -2 .1 -1.9\n')
    write_stage(tmp_path, 'hot', 30, '0 -3 .1 -2.9\n5 -4 .1 -3.9\n')
    result = energy_series([job(tmp_path)], tmp_path)
    data = result['oxdna_energy']['temporal']
    assert result['ready']
    assert data['x_values'] == [0, 10, 10, 20, 20, 25]
    assert data['per_frame'] == [-1, -2, -2, -3, -3, -4]
    assert data['temperature_c'] == [25]*4 + [30]*2
    assert [b['start_x'] for b in data['boundaries']] == [0, 20]
    assert data['stage_names'] == ['warm']*4 + ['hot']*2
    assert not list(tmp_path.rglob('thermal_energy_curve.json'))  # read-only, no gate writes


def test_energy_only_route_needs_no_geometry_or_trajectory(tmp_path, monkeypatch):
    from backend.api import routes_oxdna_metrics as routes
    write_stage(tmp_path, 'warm', 25, '0 -1\n10 -2\n')
    monkeypatch.setattr(routes, '_resolve_jobs', lambda *args: [job(tmp_path)])
    monkeypatch.setattr(routes, '_job_inputs', lambda *args: (_ for _ in ()).throw(AssertionError('geometry read')))
    routes._compute('energy-test', 'j1', routes.MetricsStartRequest(metric='oxdna_energy'), tmp_path)
    result = routes._RUNS.pop('energy-test')
    assert result['state'] == 'done'
    assert result['result']['ready']


def test_no_data_and_chain_offsets(tmp_path):
    first = job(tmp_path, ('warm',))
    assert not energy_series([first], tmp_path)['ready']
    write_stage(tmp_path, 'warm', 25, '0 -1\n10 -2\n')
    second = job(tmp_path, ('hot',))
    second.job_id = 'j2'
    write_stage(tmp_path, 'hot', 20, '0 -3\n5 -4\n')
    result = energy_series([first, second], tmp_path, 'chain')
    assert result['jobs'] == ['j1', 'j2']
    assert result['oxdna_energy']['temporal']['x_values'] == [0, 10, 10, 15]
    assert result['oxdna_energy']['temporal']['temperature_c'] == [25, 25, 20, 20]


def test_active_output_does_not_export_half_written_row(tmp_path):
    directory = write_stage(tmp_path, 'warm', 25, '0 -1\n10 -2')
    result = energy_series([job(tmp_path)], tmp_path)
    assert result['oxdna_energy']['temporal']['per_frame'] == [-1]
    with (directory / 'energy.dat').open('a') as output:
        output.write('.5\n')
    result = energy_series([job(tmp_path)], tmp_path)
    assert result['oxdna_energy']['temporal']['per_frame'] == [-1, -2.5]
