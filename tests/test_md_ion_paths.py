import numpy as np
import pytest
from backend.core.md_ion_paths import crossing_events, path_window, ion_paths


def test_aperture_crossings_reject_wall_and_periodic_face():
    # Three ions: through aperture, through solid membrane, across the box edge.
    xyz = np.array([[[0, -1, 0], [3, -1, 0], [0, 4.9, 0]],
                    [[0, 1, 0], [3, 1, 0], [0, -4.9, 0]],
                    [[0, -1, 0], [3, 1, 0], [0, -4.8, 0]]])
    cells = np.full((3, 3), 10.)
    assert crossing_events(xyz, cells, np.zeros(3), np.array([0, 1, 0]), 2) == [(1, 0, 1), (2, 0, -1)]
    assert crossing_events(xyz, cells, np.zeros(3), np.array([0, 1, 0]), 2, [1]) == [(2, 0, -1)]


def test_window_unwraps_continuously_and_clips():
    xyz = np.array([[[4.8, -1, 0]], [[-4.9, 0.1, 0]], [[-4.6, 1, 0]]])
    cells = np.full((3, 3), 10.)
    lo, points = path_window(xyz, cells, 1, 0, 10, 10, np.array([5, 0, 0]))
    assert lo == 0
    np.testing.assert_allclose(points[:, 0], [-0.2, 0.1, 0.4])
    lo, points = path_window(xyz, cells, 1, 0, 10, 10, np.array([5, 0, 0]), 1, 2)
    assert lo == 1 and len(points) == 1


def test_no_nanopore_rejected(tmp_path):
    (tmp_path / 'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='nanopore'):
        ion_paths(tmp_path, [])


def test_dcd_ion_selection_and_cached_window(tmp_path, monkeypatch):
    import json
    import MDAnalysis as mda
    from backend.core import md_ion_paths as module
    (tmp_path / 'manifest.json').write_text(json.dumps({'name_stem': 'test', 'graphene_nanopore': {
        'pore_center_nm': [0, 0, 0], 'dir': [0, 1, 0], 'pore_diameter_nm': 4}}))
    (tmp_path / 'test.psf').write_text('PSF\n\n5 !NATOM\n1 DNA 1 DA P P 0 31\n2 ION 1 SOD SOD SOD 1 23\n3 ION 2 MGH OH2 OT 0 16\n4 ION 2 MGH MG MG 2 24\n5 GRA 1 GRP C NGRC 0 12\n')
    universe = mda.Universe.empty(5, trajectory=True)
    universe.dimensions = [100, 100, 100, 90, 90, 90]
    path = tmp_path / 'test.dcd'
    with mda.Writer(str(path), n_atoms=5) as writer:
        for y in [-10, 10, 20]:
            universe.atoms.positions = [[0, 0, 0], [0, y, 0], [0, y, 0], [30, y, 0], [20, 0, y]]
            writer.write(universe.atoms)
    result = ion_paths(tmp_path, [path], 1, 1)
    assert result['graphene'] == [2, 0, -1]  # first saved frame, nm, same pore origin
    assert result['ion_count'] == 2
    assert result['crossings'] == 1
    assert result['paths'][0]['ion_serial'] == 2
    assert result['paths'][0]['positions'] == [0, -1, 0, 0, 1, 0, 0, 2, 0]
    monkeypatch.setattr(module, '_read_snapshot', lambda *a: pytest.fail('cache reread'))
    assert ion_paths(tmp_path, [path], 2, 2)['crossings'] == 1


def test_rmsf_mean_inverts_rotation_translation_and_periodic_pore_image():
    from backend.core.md_ion_paths import average_in_pore_frame
    rotation = np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]])
    reference = dict(box_nm=[10, 10, 10], c_box=[1, 2, 3], T_dyn=[5, -3, 7],
                     mob_c=[2, 3, 4], R_align=rotation, eq_centroid=[9, -2, 1])
    raw = np.array([[1.4, 2.1, 3.7], [1.8, 2.3, 3.9]])
    aligned = (raw + reference['T_dyn'] - np.asarray(reference['mob_c'])) @ rotation.T + reference['eq_centroid']
    # The nominal pore is one cell away from the DNA's chosen periodic image.
    actual = average_in_pore_frame(aligned, reference, np.array([11., 2, 3]))
    np.testing.assert_allclose(actual, raw - [1, 2, 3], atol=1e-12)


def test_rmsf_context_keeps_existing_mean_and_connects_only_actual_strands(monkeypatch):
    from types import SimpleNamespace
    from backend.core import md_trajectory as mt
    atoms = np.asarray([SimpleNamespace(segid=seg, resid=res) for seg, res in [('A', 2), ('A', 3), ('B', 1), ('A', 1)]])
    ctx = dict(p_order=[('h', 1, 'FORWARD'), ('h', 2, 'FORWARD'), ('h', 1, 'REVERSE')],
               n_frames=2, dna_p_idx=[0, 1, 2], universe=SimpleNamespace(atoms=atoms),
               term_specs=[(('h', 0, 'FORWARD'), 3, 3, 0)])
    monkeypatch.setattr(mt, '_build_md_nadoc_ctx', lambda *a, **k: ctx)
    def extract(_ctx, frame, **kwargs):
        if kwargs.get('frame_out') is not None:
            kwargs['frame_out'].update(box_nm=np.array([10, 10, 10]))
        pos = np.array([[0., 0, 0], [1, 0, 0], [2, 0, 0]]) + frame
        normal = np.tile([0., 0, 1], (3, 1))
        return pos, normal, pos + normal, np.array([[-1., 0, 0]]) + frame, np.array([[0., 0, 1]])
    monkeypatch.setattr(mt, '_extract_md_nadoc_frame', extract)
    original = mt.md_rmsf('x.psf', [], 'x.pdb', None)
    actual = mt.md_rmsf('x.psf', [], 'x.pdb', None, include_reference_frame=True)
    assert actual['positions'] == original['positions']
    assert actual['backbone_edges'] == [[3, 0], [0, 1]]
    assert actual['reference_frame'] == {'box_nm': [10, 10, 10]}


@pytest.mark.parametrize('before,after', [(10, 200), (200, 200), (10000, 10000)])
def test_shared_large_windows_preserve_coordinates_and_periodic_images(before, after):
    from backend.core.md_ion_paths import shared_path_tracks, pack_ion_paths
    import json
    import struct
    t = np.arange(600)
    xyz = np.zeros((600, 1, 3), dtype=np.float32)
    xyz[:, 0, 0] = (t * 0.13 + 5) % 10 - 5
    xyz[:, 0, 1] = np.sin(t / 3)
    cells = np.full((600, 3), 10., dtype=np.float32)
    events = [(f, 0, 1) for f in range(20, 581, 20)]
    paths, tracks, expanded = shared_path_tracks(xyz, cells, [42], [0], np.zeros(3), events, [0, 600], before, after)
    assert sum(len(track) // 3 for track in tracks) < expanded
    for path, (frame, row, _direction) in zip(paths, events):
        lo, expected = path_window(xyz, cells, frame, row, before, after, np.zeros(3))
        start, count = path['point_start'], path['point_count']
        actual = tracks[path['track']].reshape(-1, 3)[start:start + count] + path['offset']
        assert path['start_frame'] == lo
        np.testing.assert_allclose(actual, expected, atol=1e-5)
    blob = pack_ion_paths({'paths': paths, 'tracks': tracks})
    magic, version, size = struct.unpack('<III', blob[:12])
    assert (magic, version) == (0x4e495054, 1)
    header = json.loads(blob[12:12 + size])
    coords = np.frombuffer(blob, '<f4', offset=12 + (size + 3) // 4 * 4)
    for descriptor, track in zip(header['tracks'], tracks):
        start = descriptor['offset']
        np.testing.assert_array_equal(coords[start:start + descriptor['count'] * 3], track)


def test_large_windows_never_merge_separate_dcd_segments():
    from backend.core.md_ion_paths import shared_path_tracks
    xyz = np.zeros((10, 1, 3), dtype=np.float32)
    paths, tracks, _ = shared_path_tracks(xyz, np.full((10, 3), 10), [1], [0], np.zeros(3),
                                         [(2, 0, 1), (7, 0, -1)], [0, 5, 10], 10000, 10000)
    assert len(tracks) == 2
    assert [p['point_count'] for p in paths] == [5, 5]
    assert [p['start_frame'] for p in paths] == [0, 5]
