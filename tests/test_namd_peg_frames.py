"""Restart lineage and bounded sampling for the physical PEG display layer."""
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from backend.core import namd_peg_frames as frames


def test_restart_discards_abandoned_future_even_before_new_dcd(tmp_path, monkeypatch):
    base = tmp_path/'base.dcd'; base.touch()
    cont = tmp_path/'cont.dcd'
    monkeypatch.setattr(frames, 'continuation_epochs', lambda *a: [(0, None, base, 0), (1, None, cont, 20)])
    monkeypatch.setattr(frames, 'read_layout', lambda p: SimpleNamespace(n_atoms=3, nsavc=10, istart=10, n_frames=4))
    assert [step for step, _ in frames.frame_index(tmp_path, 'rung', 3)] == [10, 20]
    cont.touch()
    assert [step for step, _ in frames.frame_index(tmp_path, 'rung', 3)] == [10, 20, 30, 40]
    assert frames.frame_index(tmp_path, 'rung', 3)[2][1][0] == cont
    with pytest.raises(ValueError, match='layout'):
        frames.frame_index(tmp_path, 'rung', 4)


def test_one_frame_means_latest_and_sampling_includes_endpoints(monkeypatch):
    monkeypatch.setattr(frames, 'read_frame', lambda p, layout, i: (np.array([[i, 0., 0.]]), None))
    index = [(i*10, (Path('segment.dcd'), None, i)) for i in range(10)]
    assert frames.sampled_frames(index, 1) == [{'step': 90, 'coordinates_nm': [[.9, 0., 0.]]}]
    assert [f['step'] for f in frames.sampled_frames(index, 3)] == [0, 40, 90]
    assert frames.sampled_frames([], 100) == []
    with pytest.raises(ValueError, match='limit'):
        frames.sampled_frames(index, 201)
    monkeypatch.setattr(frames, 'read_frame', lambda *a: (np.array([[float('nan'), 0, 0]]), None))
    with pytest.raises(ValueError, match='Nonfinite'):
        frames.sampled_frames(index, 1)


def test_live_review_includes_running_stage_and_rejects_unknown_segment(tmp_path, monkeypatch):
    import json
    from backend.core import namd_peg_review as review
    from backend.core.md_job import MdSegmentStatus, MdStatus, new_job
    job = new_job('PEG', 'PEG', 'system', 'package', run_kind='peg_fast_relax')
    job.status = MdStatus.running
    job.segments = [MdSegmentStatus('warm', 'warm', 100, 100, status='done'),
                    MdSegmentStatus('relax', 'relax', 100, 100, status='running')]
    job.save(tmp_path)
    package = job.package_dir(tmp_path); package.mkdir(parents=True, exist_ok=True)
    (package/'peg_review.json').write_text(json.dumps(dict(atoms=3)))
    monkeypatch.setattr(review, 'frame_index', lambda *a: [(10, None), (20, None)])
    monkeypatch.setattr(review, 'sampled_frames', lambda *a: [dict(step=20)])
    payload = review.job_review(tmp_path, job.job_id, max_frames=1)
    assert payload['stage'] == 'relax'
    assert payload['available_stages'] == ['warm', 'relax']
    assert payload['raw_frames'] == 2
    assert payload['job']['status'] == 'running'
    assert review.job_review(tmp_path, job.job_id, segment='warm')['stage'] == 'warm'
    with pytest.raises(ValueError, match='unavailable'):
        review.job_review(tmp_path, job.job_id, segment='../other')
