"""Tail preview, exact weighting, bounded state and cancellation/resume."""
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core import md_flex_stream as stream
from backend.core import md_trajectory as mt


def _fake(monkeypatch, n=70):
    calls, contexts = [], []
    def context(*args, **kwargs):
        reader = SimpleNamespace(frame=lambda i: (np.array([i]), None), close=lambda: calls.append('closed'))
        ctx = dict(n_frames=n, p_order=[('h', 0, 'FORWARD')], term_specs=[],
                   atom_meta=[dict(serial=2, helix_id='h', bp_index=0, direction='FORWARD')],
                   heavy_bonds=np.empty((0, 2), int), dcd_prefix=reader,
                   backbone_residues=[('A', 1)], R_prev=None, prev_frame_idx=-999)
        contexts.append(ctx)
        return ctx
    def extract(ctx, i, **kwargs):
        calls.append(i)
        return (np.array([[float(i), 2., 3.]]), np.array([[0., 0., 1.]]),
                np.array([[i + 1., 2., 3.]]), None, None)
    monkeypatch.setattr(mt, '_build_playback_ctx', context)
    monkeypatch.setattr(mt, '_extract_md_nadoc_frame', extract)
    monkeypatch.setattr(mt, '_extract_md_atoms_frame', lambda ctx, i, **kw: np.array([[i, 2., 3.]]))
    return calls, contexts


def test_tail_preview_then_exact_final_and_shared_atom_means(monkeypatch):
    calls, _ = _fake(monkeypatch)
    partials = []
    def report(*args): pass
    report.publish = lambda *args: partials.append(args)
    result = stream.calculate_flex('none.psf', [], 'none.pdb', None, progress=report)
    preview, phase, done, total, atoms = partials[0]
    assert phase == 'tail_preview' and (done, total) == (32, 70)
    assert calls[:32] == list(range(38, 70))
    assert calls[32:-1] == list(range(70))
    assert calls[-1] == 'closed'
    assert preview['positions'][0]['backbone_position'][0] == 53.5
    assert atoms['atomistic'][6] == 53.5
    final = result['rmsf']
    assert final['n_frames'] == 70
    assert final['positions'][0]['backbone_position'] == [34.5, 2., 3.]
    assert final['positions'][0]['rmsf'] == pytest.approx(np.std(np.arange(70)))
    assert result['average']['atomistic'][6] == 34.5


def test_checkpoint_resume_reuses_completed_chunks_and_closes_on_cancel(tmp_path, monkeypatch):
    calls, _ = _fake(monkeypatch)
    path = tmp_path / 'checkpoint.npz'
    monkeypatch.setattr(stream, '_checkpoint_path', lambda _: path)
    def report(phase, done, total):
        if phase == 'backfill' and done == 32:
            raise RuntimeError('cancel')
    with pytest.raises(RuntimeError, match='cancel'):
        stream.calculate_flex('none.psf', [], 'none.pdb', None, progress=report)
    assert calls[-1] == 'closed'
    calls.clear()
    orphan = tmp_path / '.flex-write-interrupted'
    orphan.write_bytes(b'partial checkpoint from a killed worker')
    result = stream.calculate_flex('none.psf', [], 'none.pdb', None)
    assert not orphan.exists()
    assert calls == list(range(32, 70)) + ['closed']
    assert result['rmsf']['n_frames'] == 70
    assert result['rmsf']['positions'][0]['rmsf'] == pytest.approx(np.std(np.arange(70)))
    with np.load(path, allow_pickle=False) as saved:
        assert saved['atom_sum'].shape == (1, 3)
        assert saved['sum_pos'].shape == (1, 3)


def test_checkpoint_identity_changes_when_inputs_change(tmp_path):
    (tmp_path / 'job.json').write_text('{}')
    dcd = tmp_path / 'frames.dcd'
    dcd.write_bytes(b'old')
    first = stream._checkpoint_path((dcd,))
    dcd.write_bytes(b'new frames')
    assert first != stream._checkpoint_path((dcd,))


def test_lightweight_reader_failure_never_rebuilds_molecules(monkeypatch):
    from backend.core import md_playback_context
    def fail(*args): raise ValueError('unsupported package')
    monkeypatch.setattr(md_playback_context, 'playback_context', fail)
    monkeypatch.setattr(mt, '_build_md_nadoc_ctx', lambda *a, **kw: pytest.fail('full reader bypass'))
    with pytest.raises(ValueError, match='unsupported package'):
        mt._build_playback_ctx('a', [], 'b', None)


def test_duplicate_viewers_share_worker_and_one_disconnect_does_not_cancel():
    from backend.core.md_flex_requests import subscribe
    async def exercise():
        finish, started = asyncio.Event(), asyncio.Event()
        calls = []
        async def calculate():
            calls.append(1)
            started.set()
            await finish.wait()
            return 42
        a = asyncio.create_task(subscribe('test', None, calculate))
        await started.wait()
        b = asyncio.create_task(subscribe('test', None, calculate))
        await asyncio.sleep(0)
        a.cancel()
        await asyncio.gather(a, return_exceptions=True)
        assert not b.done()
        finish.set()
        assert await b == 42
        assert calls == [1]
    asyncio.run(exercise())


def test_worker_yields_after_bounded_slice_and_resumes_to_final(tmp_path, monkeypatch):
    calls, _ = _fake(monkeypatch)
    monkeypatch.setattr(stream, '_checkpoint_path', lambda _: tmp_path / 'checkpoint.npz')
    def report(*args): pass
    report.slice_seconds = 1e-12
    first = stream.calculate_flex('none.psf', [], 'none.pdb', None, progress=report)
    assert first['continue_calculation'] and not first['ready']
    assert calls == list(range(32)) + ['closed']
    calls.clear()
    result = stream.calculate_flex('none.psf', [], 'none.pdb', None)
    assert calls == list(range(32, 70)) + ['closed']
    assert result['rmsf']['n_frames'] == 70


def test_selected_range_drives_both_means_and_preview(monkeypatch):
    calls, _ = _fake(monkeypatch, n=1000)
    partials = []
    def report(*args): pass
    report.publish = lambda *args: partials.append(args)
    selected = dict(start=801, end=1000, interval=3)
    result = stream.calculate_flex('none.psf', [], 'none.pdb', None,
                                   frame_range=selected, progress=report)
    expected = list(range(800, 1000, 3))
    assert calls[:32] == expected[-32:]
    assert calls[32:-1] == expected
    assert result['rmsf']['n_frames'] == len(expected)
    assert result['rmsf']['positions'][0]['backbone_position'][0] == pytest.approx(np.mean(expected))
    assert result['average']['atomistic'][6] == pytest.approx(np.mean(expected))


def test_range_replacement_waits_for_old_worker_cleanup():
    from backend.core.md_flex_requests import subscribe
    async def exercise():
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events = []
        async def old():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                events.append('old cleanup')
        async def new():
            events.append('new worker')
            return 42
        a = asyncio.create_task(subscribe(('job', 'rmsf', 'old'), None, old))
        await started.wait()
        b = asyncio.create_task(subscribe(('job', 'rmsf', 'new'), None, new))
        await cleaning.wait()
        assert events == []
        release.set()
        assert await b == 42
        await asyncio.gather(a, return_exceptions=True)
        assert events == ['old cleanup', 'new worker']
    asyncio.run(exercise())
