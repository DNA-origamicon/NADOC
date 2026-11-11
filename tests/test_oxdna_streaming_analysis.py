"""Streaming analysis retains particle moments rather than trajectory history."""
import weakref

import numpy as np
import pytest

from backend.core.oxdna_health import production_rmsf
from backend.physics import oxdna_interface as interface


@pytest.mark.parametrize('average', [False, True])
def test_online_rmsf_matches_batch_with_missing_particles(monkeypatch, average):
    keys = [(0, 0, 'FORWARD', 0), (0, 0, 'FORWARD', 1)]
    samples = {k: [] for k in keys}
    live = []

    def frames(*args, **kwargs):
        for i in range(80):
            # Only the current/previous frame may remain alive in the consumer.
            assert sum(ref() is not None for ref in live) <= 4
            frame = {}
            for j, key in enumerate(keys):
                if j and i % 3 == 0:
                    continue
                cm = np.array([1e5 + np.sin(i), j + i / 10, np.cos(i)])
                a1 = np.array([1., 0., 0.])
                a3 = np.array([0., 0., 1.])
                samples[key].append(cm.copy())
                live.append(weakref.ref(cm))
                frame[key] = {'backbone_position': cm, 'a1': a1, 'a3': a3}
            yield frame

    monkeypatch.setattr(interface, 'iter_trajectory_frames_full', frames)
    monkeypatch.setattr(interface, 'read_configuration_full', lambda *a, **k: {})
    monkeypatch.setattr(interface, '_parse_box_nm', lambda *a: None)
    monkeypatch.setattr(interface, '_build_unwrap_plan', lambda *a: {})
    result = production_rmsf(None, ['one', 'two'], 'ref', copies=True,
                             include_average_frame=average)
    assert result['n_frames'] == 160
    for key, pos in zip(keys, result['positions']):
        cm = np.array(samples[key])
        a1 = np.tile([1., 0., 0.], (len(cm), 1))
        a3 = np.tile([0., 0., 1.], (len(cm), 1))
        bb = interface.oxdna_backbone_sites(cm, a1, a3)
        np.testing.assert_allclose(pos['backbone_position'], bb.mean(axis=0))
        expected = np.sqrt(np.mean(np.sum((bb - bb.mean(axis=0)) ** 2, axis=1)))
        assert pos['rmsf'] == pytest.approx(expected, abs=1e-9)
        assert pos['copy'] == key[3]
        if average:
            np.testing.assert_allclose(result['average_frame'][key]['backbone_position'], cm.mean(axis=0))
            np.testing.assert_allclose(result['average_frame'][key]['a1'], [1, 0, 0])
            np.testing.assert_allclose(result['average_frame'][key]['a3'], [0, 0, 1])


def test_frame_iterator_is_lazy_and_does_not_read_whole_file(tmp_path, monkeypatch):
    from pathlib import Path
    from backend.physics import oxdna_submodel

    path = tmp_path / 'trajectory.dat'
    path.write_text('ignored\nt = 0\nb = 1 1 1\nE = 0\nfirst\nt = 1\nsecond\nt = 2\n')
    monkeypatch.setattr(interface, '_strand_nucleotide_order', lambda d: [])
    parsed = []

    def parse(lines, *args, **kwargs):
        parsed.append(list(lines))
        return {'rows': list(lines)} if lines else {}

    monkeypatch.setattr(interface, '_parse_trajectory_frame_lines', parse)
    monkeypatch.setattr(oxdna_submodel, 'display_frame', lambda frame, path: frame)
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: pytest.fail('whole-file read'))
    frames = interface.iter_trajectory_frames_full(path, None)
    assert parsed == []
    assert next(frames) == {'rows': ['first\n']}
    assert len(parsed) == 1
    assert list(frames) == [{'rows': ['second\n']}]
