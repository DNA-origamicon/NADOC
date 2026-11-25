"""Persistence/precision and interrupted batch contracts for derived EM volumes."""
import json

import numpy as np
import pytest

from backend.physics.em_volume_archive import VolumeArchive, read_frame, write_snapshots


def result():
    # Odd sample count exercises packed-mask padding; unequal axes detect swaps.
    values = np.random.default_rng(42).lognormal(0, 5, 105)
    values[0] = np.nextafter(1., 2.)
    return {'shape': [3, 5, 7], 'intensity': values,
            'outside': np.arange(105) % 3 != 0,
            'inputs': {'particles': [{'id': 'optical-only'}]},
            'basis': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            'quantity': '|E_total|²/|E_incident|²', 'probe_relative_error': .001}


def test_random_access_bit_exact_and_metadata(tmp_path):
    path = tmp_path / 'volumes'
    archive = VolumeArchive(path)
    expected = result()
    archive.append(expected, frame_index=20, time_ps=1.25)
    archive.append(expected, frame_index=40, time_ps=2.5)
    archive.finish()
    loaded = read_frame(path, 1)
    assert loaded['frame_index'] == 40 and loaded['time_ps'] == 2.5
    assert loaded['inputs'] == expected['inputs']
    assert loaded['quantity'] == expected['quantity']
    assert loaded['intensity'].tobytes() == expected['intensity'].tobytes()
    np.testing.assert_array_equal(loaded['outside'].ravel(), expected['outside'])
    assert loaded['intensity'].shape == (3, 5, 7)
    assert json.loads((path / 'manifest.json').read_text())['status'] == 'complete'
    with pytest.raises(ValueError, match='closed'):
        archive.append(expected, frame_index=60)
    with pytest.raises(FileExistsError):
        VolumeArchive(path)
    with pytest.raises(IndexError):
        read_frame(path, -1)


def test_failure_retains_only_completed_frames(tmp_path):
    path = tmp_path / 'volumes'
    calls = []
    def solver(payload, *, arrays):
        assert arrays
        calls.append(payload)
        if payload == 'bad':
            raise ValueError('did not converge')
        return result()
    entries = [dict(frame_index=i, input=value) for i, value in enumerate(['ok', 'bad', 'unreached'])]
    with pytest.raises(ValueError, match='converge'):
        write_snapshots(map(json.dumps, entries), path, solver=solver)
    manifest = json.loads((path / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and len(manifest['frames']) == 1
    assert calls == ['ok', 'bad']
    assert read_frame(path, 0)['frame_index'] == 0
    assert not list(path.glob('*.tmp'))


def test_integrity_and_duplicate_identity(tmp_path):
    archive = VolumeArchive(tmp_path / 'volumes')
    archive.append(result(), frame_index=0)
    with pytest.raises(ValueError, match='Duplicate'):
        archive.append(result(), frame_index=0)
    frame = archive.path / 'frame-000000.npz'
    frame.write_bytes(frame.read_bytes() + b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        read_frame(archive.path, 0)


@pytest.mark.parametrize('field,value', [('intensity', [float('nan')] * 105),
    ('intensity', [-1.] * 105), ('outside', [1] * 105), ('shape', [3, 5, 8])])
def test_invalid_volume_never_committed(tmp_path, field, value):
    archive = VolumeArchive(tmp_path / 'volumes')
    invalid = result(); invalid[field] = value
    with pytest.raises(ValueError):
        archive.append(invalid, frame_index=0)
    assert json.loads((archive.path / 'manifest.json').read_text())['frames'] == []
    assert not list(archive.path.glob('*.npz'))
