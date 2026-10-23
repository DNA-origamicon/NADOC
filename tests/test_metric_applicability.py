"""Undefined bundle geometry must not abort backfill or an entire refit chain."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.oxdna_health import bundle_metrics_unavailable
from backend.core.trajectory_cache import persistent_analysis


@pytest.mark.parametrize('engine', ['md', 'oxdna'])
@pytest.mark.parametrize('reference', [[], [{'helix_id': 'single'}]])
def test_undefined_bundle_returns_before_opening_trajectory(monkeypatch, engine, reference):
    from backend.core import md_trajectory, oxdna_health
    from backend.physics import oxdna_interface

    def no_read(*args, **kwargs):
        raise AssertionError('inapplicable geometry must not read trajectory/topology')

    monkeypatch.setattr(oxdna_interface, 'read_configuration_full', no_read)
    monkeypatch.setattr(md_trajectory, '_build_fast_md_metrics_ctx', no_read)
    if engine == 'md':
        result = md_trajectory.md_metric_series('missing.psf', [], 'missing.pdb', None, reference)
    else:
        result = oxdna_health.production_metric_series(None, [], 'missing.dat', reference)
    assert result['ready'] is False
    assert result['not_applicable'] is True
    assert 'at least two helices' in result['reason']


def test_inapplicability_is_cached_but_source_changes_invalidate_it(tmp_path):
    (tmp_path / 'job.json').write_text('{"status":"completed"}')
    source = tmp_path / 'design.json'
    source.write_text('one helix')
    calls = []

    @persistent_analysis
    def measure(path):
        calls.append(1)
        return bundle_metrics_unavailable([{'helix_id': 'single'}])

    assert measure(source)['not_applicable']
    assert measure.read_cached(source)['not_applicable']
    measure(source)
    assert len(calls) == 1
    source.write_text('revised multi-helix design')
    assert measure.read_cached(source) is None
    measure(source)
    assert len(calls) == 2


@pytest.mark.parametrize('engine', ['md', 'oxdna'])
@pytest.mark.parametrize('case', ['mixed', 'all_unavailable', 'error'])
def test_metric_chain_skips_only_expected_inapplicability(monkeypatch, engine, case):
    from backend.api import routes_md_metrics as md, routes_oxdna_metrics as ox
    from backend.core import md_trajectory, oxdna_health
    module = md if engine == 'md' else ox
    jobs = [SimpleNamespace(job_id='single'), SimpleNamespace(job_id='valid')]
    monkeypatch.setattr(module, '_resolve_jobs', lambda *a: jobs)
    monkeypatch.setattr(module, '_job_inputs', lambda j, ws:
                        ('top', 'ref', [], j.job_id) if engine == 'md' else (j.job_id, 'ref', []))
    monkeypatch.setattr(md_trajectory, 'count_md_frames', lambda *a: 1)
    monkeypatch.setattr(oxdna_health, 'count_trajectory_frames', lambda *a: 1)
    monkeypatch.setattr(md, '_job_scalar_series', lambda *a: {
        'energy': {'per_frame': [], 'x_values': []},
        'pressure': {'per_frame': [], 'x_values': []}, 'duration_ns': 0,
    })

    def measure(*args, **kwargs):
        if case == 'error':
            raise ValueError('corrupt trajectory')
        identity = args[3] if engine == 'md' else args[0]
        if identity == 'single' or case == 'all_unavailable':
            return bundle_metrics_unavailable([{'helix_id': 'single'}])
        return {'ready': True, 'n_frames': 1, 'frame_indices': [0], **{
            metric: {'temporal': {'per_frame': [0.1], 'n_designed': 4}, 'spatial': [(0, .1)]}
            for metric in ('twist', 'curvature', 'base_pairing', 'rmsd')
        }}

    monkeypatch.setattr(module, '_measure', measure)
    request = md.MdMetricsStartRequest(scope='chain') if engine == 'md' else ox.MetricsStartRequest(scope='chain')
    run_id = f'applicability-{engine}-{case}'
    try:
        module._compute(run_id, 'valid', request, Path('/unused'))
        run = module._RUNS[run_id]
        if case == 'error':
            assert run['state'] == 'error'
            assert run['error'] == 'corrupt trajectory'
        else:
            assert run['state'] == 'done'
            result = run['result']
            assert result['skipped_jobs'][0]['job_id'] == 'single'
            if case == 'mixed':
                assert result['ready'] is True
                assert result['jobs'] == ['valid']
                assert result['twist']['temporal']['per_frame'] == [.1]
            else:
                assert result['ready'] is False
                assert result['not_applicable'] is True
                assert 'at least two helices' in result['reason']
    finally:
        module._RUNS.pop(run_id, None)


@pytest.mark.parametrize('engine', ['md', 'oxdna'])
def test_unsupported_placement_is_saved_without_reading_trajectory(monkeypatch, tmp_path, engine):
    from backend.api import routes_md_metrics as md, routes_oxdna_metrics as ox, skip_twist_tuning
    from backend.core import md_trajectory, oxdna_health
    from backend.physics.native_oxdna import native_full_to_oxdna_geometry

    (tmp_path / 'job.json').write_text('{"status":"completed"}')
    ref = tmp_path / 'reference.dat'
    ref.write_text('reference')
    calls = []

    def reference(design):
        calls.append(1)
        return native_full_to_oxdna_geometry(design, [{
            'placement_source': 'manual-cpd-context-v1',
            'helix_id': 'h0', 'bp_index': 0, 'direction': 'FORWARD',
        }])

    def no_read(*args, **kwargs):
        raise AssertionError('unsupported reference must not read trajectory')

    monkeypatch.setattr(skip_twist_tuning, 'core_reference_geometry', reference)
    monkeypatch.setattr(md_trajectory, 'md_metric_series', no_read)
    monkeypatch.setattr(oxdna_health, 'production_metric_series', no_read)
    measure = md._measure if engine == 'md' else ox._measure
    args = ('top', [], ref, None) if engine == 'md' else (None, [], ref)
    result = measure(*args)
    assert result['not_applicable'] is True
    assert result['placement_source'] == 'manual-cpd-context-v1'
    assert 'manual-cpd-context-v1' in result['reason']
    assert measure(*args) == result
    assert len(calls) == 1
    ref.write_text('changed reference')
    assert measure.read_cached(*args) is None
    measure(*args)
    assert len(calls) == 2


def test_invalid_native_geometry_is_not_treated_as_unsupported(monkeypatch):
    from backend.api import skip_twist_tuning
    from backend.core.native_full_placement import NativePlacementError
    from backend.core.oxdna_health import metric_reference_geometry

    def invalid(design):
        raise NativePlacementError('Native Full coordinates disagree with their transported site.')

    monkeypatch.setattr(skip_twist_tuning, 'core_reference_geometry', invalid)
    with pytest.raises(NativePlacementError, match='disagree'):
        metric_reference_geometry(None)
