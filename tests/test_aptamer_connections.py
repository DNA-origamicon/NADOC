"""Imported motifs participate in ordinary strand editing and connection APIs."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.aptamer import import_aptamer, template_content, native_core_paired
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.deformation import deformed_helix_axes
from backend.core.lattice import resize_strand_ends, autodetect_all_overhangs
from backend.core.models import Design, Domain, Strand, Direction, Helix, Vec3


@pytest.fixture
def client():
    state.load_design(None)
    state.clear_history()
    with TestClient(app) as c:
        yield c
    state.load_design(None)
    state.clear_history()


def call(client, method, path, **kwargs):
    r = client.request(method, '/api/design/' + path, **kwargs)
    assert r.is_success, r.text
    return r.json()


def seed():
    d = import_aptamer(template_content('148D'))
    s = d.strands[0]
    d = resize_strand_ends(d, [dict(strand_id=s.id, helix_id=d.helices[0].id, end=end, delta_bp=delta)
                              for end, delta in [('5p', -4), ('3p', 4)]])
    h = Helix(id='ordinary', axis_start=Vec3(x=6,y=0,z=0), axis_end=Vec3(x=6,y=0,z=10), length_bp=30)
    d.helices.append(h)
    d.strands.extend([
        Strand(id='scaf', strand_type='scaffold', sequence='A'*15,
               domains=[Domain(helix_id=h.id, start_bp=0, end_bp=14, direction=Direction.FORWARD)]),
        Strand(id='stap', sequence='N'*4+'T'*15,
               domains=[Domain(helix_id=h.id, start_bp=18, end_bp=0, direction=Direction.REVERSE)]),
    ])
    return autodetect_all_overhangs(d)


def test_native_tails_are_stable_overhangs_and_can_form_sidebar_duplex(client):
    d = seed()
    native_id = d.helices[0].id
    core = d.helices[0].native_residues
    tails = [o for o in d.overhangs if o.helix_id == native_id]
    assert len(tails) == 2
    assert all(o.sub_domains[0].length_bp == 4 for o in tails)
    restored = autodetect_all_overhangs(Design.model_validate_json(d.model_dump_json()))
    assert {o.id for o in restored.overhangs} == {o.id for o in d.overhangs}
    state.load_design(restored)
    a = next(o for o in tails if o.id.endswith('3p'))
    b = next(o for o in d.overhangs if o.strand_id == 'stap')
    result = call(client, 'POST', 'duplexes/connect', json={
        'overhang_a_id': a.id, 'overhang_b_id': b.id,
        'overhang_a_attach': 'free_end', 'overhang_b_attach': 'free_end',
        'driver': 'left',
    })
    assert result['design']['duplexes']
    paired = state.get_design()
    assert not native_core_paired(paired.helices[0], paired)
    geom = _geometry_for_design(paired)
    for site in core:
        n = next(n for n in geom if n['helix_id'] == native_id and n['bp_index'] == site.bp_index and n['direction'] == 'FORWARD')
        np.testing.assert_allclose(n['backbone_position'], site.atoms["C1'"].to_array())
    # Paired tails occupy distinct backbone positions, rather than two
    # coincident copies of the folded G4 coordinates.
    for bp in range(15, 19):
        pair = [n for n in geom if n['helix_id'] == native_id and n['bp_index'] == bp]
        assert len(pair) == 2
        assert np.linalg.norm(np.subtract(pair[0]['backbone_position'], pair[1]['backbone_position'])) > 1
    assert np.isfinite([[a.x,a.y,a.z] for a in build_atomistic_model(paired).atoms]).all()


@pytest.mark.parametrize('g4_first', [True, False])
def test_forced_ligation_keeps_sequence_sites_and_history(client, g4_first):
    d = seed()
    g4 = d.strands[0]
    state.load_design(d)
    a, b = (g4.id, 'stap') if g4_first else ('stap', g4.id)
    seq = {s.id:s.sequence for s in d.strands}
    result = call(client, 'POST', 'forced-ligation', json={'three_prime_strand_id':a, 'five_prime_strand_id':b})
    merged = next(s for s in result['design']['strands'] if s['id'] == a)
    assert merged['sequence'] == seq[a] + seq[b]
    assert len(result['design']['forced_ligations']) == 1
    assert len(_geometry_for_design(state.get_design())) == len(_geometry_for_design(d))
    call(client, 'POST', 'undo')
    assert {s.id for s in state.get_design().strands} == {s.id for s in d.strands}
    call(client, 'POST', 'redo')
    assert len(state.get_design().forced_ligations) == 1
    from backend.core.sequences import assign_staple_sequences
    assigned = assign_staple_sequences(state.get_design())
    merged = next(s for s in assigned.strands if s.id == a)
    assert 'GGTTGGTGTGGTTGG' in merged.sequence
    # The free regular-staple end remains resizable after absorbing the G4.
    end = "3p" if g4_first else "5p"
    delta = -2 if g4_first else 2
    resized = resize_strand_ends(assigned, [dict(strand_id=a,helix_id='ordinary',end=end,delta_bp=delta)])
    assert 'GGTTGGTGTGGTTGG' in next(s for s in resized.strands if s.id == a).sequence


def test_cadnano_partner_selects_real_duplex_and_undo_restores_fold(client):
    d = import_aptamer(template_content('148D'))
    state.load_design(d)
    original = _geometry_for_design(d)
    result = call(client, 'POST', 'strands', json={
        'strand_type':'staple',
        'domains':[{'helix_id':d.helices[0].id,'start_bp':14,'end_bp':0,'direction':'REVERSE'}],
    })
    assert result['strand']['sequence'] == 'CCAACCACACCAACC'
    current = state.get_design()
    assert native_core_paired(current.helices[0], current)
    assert current.helices[0].native_residues == d.helices[0].native_residues
    g = _geometry_for_design(current, measured_positioning=True)
    assert len(g) == 30
    for bp in range(15):
        p = [n for n in g if n['bp_index'] == bp]
        assert np.linalg.norm(np.subtract(p[0]['backbone_position'],p[1]['backbone_position'])) > 1
    atoms = build_atomistic_model(current).atoms
    for bp in range(15):
        sugar = [a for a in atoms if a.bp_index == bp and a.name == "C1'"]
        assert len(sugar) == 2
        assert np.linalg.norm(np.subtract([sugar[0].x,sugar[0].y,sugar[0].z],[sugar[1].x,sugar[1].y,sugar[1].z])) > 1
    assert len(deformed_helix_axes(current)[0]['samples']) < 15
    call(client,'POST','undo')
    assert _geometry_for_design(state.get_design()) == original
    call(client,'POST','redo')
    call(client,'DELETE',f"strands/{result['strand']['id']}")
    assert _geometry_for_design(state.get_design()) == original


def test_tail_sequence_patch_preserves_native_core_without_scaffold(client):
    d = seed()
    d.strands = [d.strands[0]]
    d.helices = [d.helices[0]]
    d.overhangs = [o for o in d.overhangs if o.strand_id == d.strands[0].id]
    state.load_design(d)
    tail = next(o for o in d.overhangs if o.id.endswith('5p'))
    for sequence in ('ACGT', 'AACCGG', None):
        call(client, 'PATCH', f'overhang/{tail.id}', json={'sequence':sequence, 'defer_reassign':True})
        actual = state.get_design().strands[0].sequence
        assert actual == (sequence or 'N'*6) + 'GGTTGGTGTGGTTGG' + 'NNNN'
