"""Reviewed half-space placements: exact geometry, invariance and conservative scope."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.extension_plane_motifs import apply_extension_plane_motifs, contexts, library

CASES = json.loads(gzip.decompress((Path(__file__).parent / 'data/extension_plane_cases.json.gz').read_bytes()))


def fragment(case, monkeypatch, rotate=None, shift=None):
    c = deepcopy(case)
    rotate = np.eye(3) if rotate is None else rotate
    shift = np.zeros(3) if shift is None else shift
    atoms = [NS(**a) for a in c['atoms']]
    for a in atoms:
        a.x, a.y, a.z = rotate @ [a.x, a.y, a.z] + shift
    ext = NS(**c['extension'])
    dom = NS(**(c['domain'] | {'direction': NS(value=c['domain']['direction'])}))
    arrays = {k: np.array(v) for k, v in c['arrays'].items()}
    arrays['axis_points'] = arrays['axis_points'] @ rotate.T + shift
    for k in ['axis_tangents', 'radial_hats']:
        arrays[k] = arrays[k] @ rotate.T
    d = NS(extensions=[ext], strands=[NS(id=ext.strand_id, domains=[dom])], helices=[NS(id=dom.helix_id, loop_skips=[])])
    monkeypatch.setattr('backend.core.deformation.deformed_nucleotide_arrays', lambda h, design: arrays)
    return d, atoms, c['bonds'], arrays


def positions(atoms):
    return np.array([[a.x, a.y, a.z] for a in atoms])


@pytest.mark.parametrize('case', CASES)
def test_reproduces_reviewed_atoms_and_keeps_context_fixed(case, monkeypatch):
    d, aa, bb, _ = fragment(case, monkeypatch)
    before = positions(aa)
    ctx = contexts(d, aa, bb)[0][0]
    reports = apply_extension_plane_motifs(d, aa, bb)
    assert len(reports) == 1
    after = positions(aa)
    assert np.linalg.norm(after[ctx['child']] - after[ctx['anchor']]) == pytest.approx(.16, abs=1e-12)
    assert np.max((after[list(ctx['roles'].values())] - ctx['plane']) @ ctx['normal']) <= 1e-8
    all_points = ctx['origin'] + np.array(library()['contexts'][ctx['key']]['all_atom_points']) @ ctx['frame'].T
    assert np.max((all_points - ctx['plane']) @ ctx['normal']) <= 1e-8
    ids = case['moved']
    np.testing.assert_allclose(positions(aa)[ids], np.array(case['expected'])[ids], atol=1e-11, rtol=0)
    fixed = sorted(set(range(len(aa))) - set(ids))
    np.testing.assert_array_equal(positions(aa)[fixed], before[fixed])


@pytest.mark.parametrize('case', CASES)
def test_rigid_motion_and_identifier_changes_preserve_placement(case, monkeypatch):
    rot = Rotation.from_euler('xyz', [31, -27, 116], degrees=True).as_matrix()
    shift = np.array([4.2, -1.7, 8.3])
    d, aa, bb, _ = fragment(case, monkeypatch, rot, shift)
    old = d.extensions[0].id
    for a in aa:
        if a.extension_id == old:
            a.extension_id = 'renamed-tail'
        elif a.extension_id:
            a.extension_id = 'neighbor-' + a.extension_id
        if a.crossover_id:
            a.crossover_id = 'renamed-' + a.crossover_id
    d.extensions[0].id = 'renamed-tail'
    d.strands[0].id = d.extensions[0].strand_id = 'renamed-strand'
    d.helices[0].id = d.strands[0].domains[0].helix_id = 'renamed-helix'
    assert len(apply_extension_plane_motifs(d, aa, bb)) == 1
    ids = case['moved']
    np.testing.assert_allclose(positions(aa)[ids], np.array(case['expected'])[ids] @ rot.T + shift, atol=1e-10, rtol=0)


@pytest.mark.parametrize('change', ['long_tail', 'other_base', 'local_geometry', 'local_connectivity', 'loop'])
def test_unreviewed_context_keeps_native_coordinates(change, monkeypatch):
    d, aa, bb, _ = fragment(CASES[0], monkeypatch)
    if change == 'long_tail':
        d.extensions[0].sequence = 'TT'
    elif change == 'other_base':
        d.extensions[0].sequence = 'A'
    elif change == 'local_geometry':
        aa[CASES[0]['moved'][0]].x += .02
    elif change == 'local_connectivity':
        i = CASES[0]['moved'][0]
        bb = [pair for pair in bb if i not in pair]
    else:
        d.helices[0].loop_skips = [NS(bp_index=d.strands[0].domains[0].end_bp)]
    before = positions(aa)
    assert apply_extension_plane_motifs(d, aa, bb) == []
    np.testing.assert_array_equal(positions(aa), before)


def test_native_builder_default_and_override_guards(monkeypatch):
    from backend.core.atomistic import build_atomistic_model
    from backend.core.models import Design
    calls = []
    monkeypatch.setattr('backend.core.extension_plane_motifs.apply_extension_plane_motifs', lambda *args: calls.append(True))
    build_atomistic_model(Design())
    assert calls == [True]
    for kwargs in [dict(_extension_plane_motifs=False), dict(_two_base_default=False), dict(apply_design_geometry=False),
                   dict(nuc_pos_override={}), dict(nuc_frame_override={}), dict(axis_override={}),
                   dict(frame_override={}), dict(xb_pos_override={}), dict(ext_pos_override={})]:
        build_atomistic_model(Design(), **kwargs)
    assert calls == [True]
