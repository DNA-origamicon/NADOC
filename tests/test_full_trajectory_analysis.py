"""Full-frame preparation must never silently reuse a sampled preview."""
import json
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.mark.parametrize('max_frames, expected', [(None, 173), (7, 7)])
def test_flex_reads_every_frame_by_default(monkeypatch, max_frames, expected):
    from backend.core import md_trajectory as mt

    seen = []
    monkeypatch.setattr(mt, '_build_playback_ctx', lambda *a, **k: {
        'p_order': [('h', 0, 'FORWARD')], 'n_frames': 173,
    })

    def frame(ctx, index, **kwargs):
        seen.append(index)
        return np.array([[float(index), 0, 0]]), None, None, None, None

    monkeypatch.setattr(mt, '_extract_md_nadoc_frame', frame)
    options = {} if max_frames is None else {'max_frames': max_frames}
    result = mt.md_rmsf('top', [], 'ref', None, **options)
    assert result['n_frames'] == expected == len(seen)
    if max_frames is None:
        assert seen == list(range(173))
        assert result['positions'][0]['backbone_position'][0] == pytest.approx(86)
        assert result['mean_rmsf'] == pytest.approx(np.std(np.arange(173)))


@pytest.mark.parametrize('max_frames, expected', [(None, 173), (7, 7)])
def test_atomistic_mean_reads_every_frame_by_default(monkeypatch, max_frames, expected):
    from backend.core import md_trajectory as mt

    seen = []
    monkeypatch.setattr(mt, '_build_playback_ctx', lambda *a, **k: {
        'n_frames': 173, 'atom_meta': [{'serial': 0}],
    })

    def frame(ctx, index, **kwargs):
        seen.append(index)
        return np.array([[float(index), 0, 0]])

    monkeypatch.setattr(mt, '_extract_md_atoms_frame', frame)
    options = {} if max_frames is None else {'max_frames': max_frames}
    result = mt.md_rmsf_atomistic('top', [], 'ref', None, **options)
    assert result['n_frames'] == expected == len(seen)
    if max_frames is None:
        assert seen == list(range(173))
        assert result['atomistic'] == [86., 0., 0.]


def test_paused_md_backfill_upgrades_old_sampled_manifest(tmp_path, monkeypatch):
    from backend.core import trajectory_precompute as worker, md_trajectory as mt
    from backend.core.md_job import MdJob
    from backend.core.trajectory_cache import VERSION
    from backend.api import routes_md, routes_md_metrics as metrics

    (tmp_path / 'job.json').write_text('{"status":"paused"}')
    cache = tmp_path / 'analysis_cache'
    cache.mkdir()
    (cache / 'old.json').write_text('{}')
    (cache / 'prepared.json').write_text(json.dumps({
        'version': VERSION, 'sources': worker._source_stamp(tmp_path), 'artifacts': ['old.json'],
    }))
    assert not worker._prepared(tmp_path)
    job = SimpleNamespace(status=SimpleNamespace(value='paused'), job_id='test', job_dir=lambda ws: tmp_path)
    monkeypatch.setattr(MdJob, 'load', lambda *a: job)
    monkeypatch.setattr(metrics, '_job_inputs', lambda *a: ('top', 'ref', [], 'design'))
    monkeypatch.setattr(routes_md, '_md_snapshot_design', lambda *a: 'design')
    calls = []
    for name in ('md_rmsf', 'md_rmsf_atomistic', 'md_rmsf_surface'):
        monkeypatch.setattr(mt, name, lambda *a, _name=name, **k: calls.append(_name))

    def compute(run_id, job_id, request, ws):
        assert request.max_frames == 0
        calls.append('metrics')
        (cache / 'full.json').write_text('{}')
        metrics._RUNS[run_id] = {'state': 'done', 'result': {'ready': True}}

    monkeypatch.setattr(metrics, '_compute', compute)
    worker.prepare(tmp_path, 'md', 'test')
    assert worker._prepared(tmp_path)
    worker.prepare(tmp_path, 'md', 'test')
    assert calls == ['md_rmsf', 'md_rmsf_atomistic', 'md_rmsf_surface', 'metrics']


@pytest.mark.parametrize('periodic', [False, True])
@pytest.mark.parametrize('reader', ['prefix', 'universe'])
def test_batched_mean_base_centers_match_scalar_calculation(monkeypatch, periodic, reader):
    from backend.core import md_trajectory as mt, md_frame_alignment as alignment

    xyz = np.random.default_rng(123).normal(size=(24, 3)).astype(np.float32) * 10
    rings = [np.arange(3, 9), np.arange(9, 18), np.arange(18, 24)]
    dims = np.array([10, 10, 10, 90, 90, 90], dtype=np.float32) if periodic else None
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    aligned = np.array([[0., 1., 2.], [3., 4., 5.], [6., 7., 8.]])
    monkeypatch.setattr(alignment, 'align_md_frame', lambda *a: SimpleNamespace(
        positions=aligned, rotation=rotation, mobile_centroid=np.zeros(3),
    ))
    ctx = {
        'universe': None, 'playback_only': True, 'p_order': [('h', i, 'FORWARD') for i in range(3)],
        'centroid_T': np.zeros(3), 'eq_positions': None, 'rigid_mask': None,
        'eq_centroid': None, 'dna_p_idx': np.arange(3), 'base_ring_idx': rings,
        'dcd_prefix': SimpleNamespace(frame=lambda i: (xyz, dims)),
    }
    if reader == 'universe':
        class Atoms:
            def __getitem__(self, indices):
                return SimpleNamespace(positions=xyz[indices])
        ctx.update(playback_only=False, universe=SimpleNamespace(
            atoms=Atoms(), trajectory=[None], dimensions=dims,
        ))
    expected = []
    for row, indices in enumerate(rings):
        delta = (xyz[indices] / 10).mean(axis=0) - xyz[row] / 10
        if periodic:
            delta -= np.round(delta)  # 1 nm box
        expected.append(aligned[row] + delta @ rotation.T)
    for _ in range(2):  # cached ring groups must be reusable
        _, _, centers = mt._extract_md_nadoc_frame(ctx, 0, with_base_centers=True)
        np.testing.assert_allclose(centers, expected, atol=1e-7)
