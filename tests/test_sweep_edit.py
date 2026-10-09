"""Edits upstream of authored routing must survive Apply, seek and persistence."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state
from backend.api.crud import _seek_feature_log
from backend.core.models import Design, Direction, StrandType
from backend.core.deformation import deformed_nucleotide_arrays, deformed_frame_at_bp
from backend.core.sweep import _site_frame

client = TestClient(app)


def post(path, body):
    r = client.post('/api/design/' + path, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def create():
    state.set_design(Design())
    post('sweep', dict(cells=[[0,0],[0,1]], points_nm=[[0,0,0],[0,0,14]], ligate_adjacent=False))
    return state.get_or_404()


def params():
    return {**state.get_or_404().feature_log[0].params, 'points_nm': [[0,0,0],[8,0,28]]}


def assert_path(design):
    assert design.deformations[0].params.points_nm[-1] == (8,0,28)


@pytest.mark.parametrize('mutation', ['nick', 'resize', 'ligation', 'crossover'])
def test_routing_survives_apply_seek_reload_and_undo(mutation):
    d = create()
    a,b = d.helices
    if mutation == 'nick':
        post('nick', dict(helix_id=a.id, bp_index=10, direction='FORWARD'))
    elif mutation == 'resize':
        s = next(s for s in d.strands if s.domains[0].helix_id==a.id and s.strand_type == StrandType.STAPLE)
        end = '3p' if s.domains[0].direction == Direction.FORWARD else '5p'
        post('strand-end-resize', {'entries':[dict(strand_id=s.id,helix_id=a.id,end=end,delta_bp=10)]})
    elif mutation == 'ligation':
        strands = [s for s in d.strands if s.domains[0].helix_id==a.id]
        post('forced-ligation', dict(three_prime_strand_id=strands[0].id,five_prime_strand_id=strands[1].id))
    else:
        from tests.test_crossover_placement import _nick_positions
        na,nb = _nick_positions(7,'REVERSE','FORWARD')
        post('crossovers/place',dict(half_a=dict(helix_id=a.id,index=7,strand='REVERSE'),half_b=dict(helix_id=b.id,index=7,strand='FORWARD'),nick_bp_a=na,nick_bp_b=nb))
    old = state.get_or_404()
    p = params()
    preview = post('sweep/preview?feature_index=0', p)
    assert state.get_or_404() == old
    response = post('features/0/edit', {'params':p})
    after = state.get_or_404()
    assert_path(after)
    assert [s.id for s in after.strands] == [s.id for s in old.strands]
    assert [x.id for x in after.crossovers] == [x.id for x in old.crossovers]
    assert [f.id for f in after.forced_ligations] == [f.id for f in old.forced_ligations]
    assert len(preview['edit_backbones_nm']) == len(after.strands)
    if mutation == 'resize':
        oh = [dom for s in after.strands for dom in s.domains if dom.overhang_id]
        assert len(oh)==1
        assert abs(oh[0].end_bp-oh[0].start_bp)+1 == 10
    if mutation == 'nick':
        domains = sorted((min(dom.start_bp,dom.end_bp),max(dom.start_bp,dom.end_bp)) for s in after.strands for dom in s.domains if dom.helix_id==a.id and dom.direction==Direction.FORWARD)
        assert len(domains)==2 and domains[0][1]+1==domains[1][0]
        assert domains[0][1]>10
    if mutation == 'crossover':
        assert any('register' in w for w in response['placement_warnings'])
    loaded = Design.model_validate_json(after.model_dump_json())
    for at in [0,1,-1]:
        assert_path(_seek_feature_log(loaded, at))
    assert_path(_seek_feature_log(loaded,1,0))
    assert client.post('/api/design/undo').status_code==200
    assert state.get_or_404().deformations[0].params.points_nm[-1]==(0,0,14)
    assert client.post('/api/design/redo').status_code==200
    assert_path(state.get_or_404())


@pytest.mark.parametrize('end', ['start','end'])
def test_attached_extrusion_moves_rigidly_with_cross_section(end):
    d=create()
    h=d.helices[0]
    bp=h.bp_start if end=='start' else h.bp_start+h.length_bp-1
    frame=deformed_frame_at_bp(d,bp,h.id)
    post('bundle-deformed-continuation',dict(cells=[[0,0],[0,1]],length_bp=-12 if end=='start' else 12,
        ref_helix_id=h.id,source_bp=bp,**frame))
    before=state.get_or_404()
    added=[h for h in before.helices if h.id not in {a.id for a in d.helices}]
    assert added
    old={h.id:deformed_nucleotide_arrays(h,before)['positions'] for h in added}
    p,a=_site_frame(before,before.find_helix(h.id),end)
    post('features/0/edit',{'params':params()})
    after=state.get_or_404()
    q,b=_site_frame(after,after.find_helix(h.id),end)
    rotation=b@a.T
    for helix in added:
        actual=deformed_nucleotide_arrays(after.find_helix(helix.id),after)['positions']
        np.testing.assert_allclose(actual,(old[helix.id]-p)@rotation.T+q,atol=1e-8)
        assert after.find_helix(helix.id).length_bp==helix.length_bp
        restored=_seek_feature_log(Design.model_validate_json(after.model_dump_json()),-1)
        np.testing.assert_allclose(deformed_nucleotide_arrays(restored.find_helix(helix.id),restored)['positions'],actual,atol=1e-8)
    assert not any(c.id.startswith('sweep-follow:') for c in _seek_feature_log(after,0).cluster_transforms)


def test_independent_later_snapshot_is_preserved_and_preview_matches_apply():
    create()
    post('bundle-segment',dict(cells=[[3,0]],length_bp=21,ligate_adjacent=False))
    before=state.get_or_404()
    independent=before.helices[-1]
    preview=post('sweep/preview?feature_index=0',params())
    post('features/0/edit',{'params':params()})
    after=state.get_or_404()
    assert independent.id not in preview['edit_helix_ids']
    assert set(preview['edit_helix_ids']) == {h.id for h in before.helices if h.id != independent.id}
    assert preview['helix_path_ids'] == [h.id for h in after.helices]
    assert after.find_helix(independent.id)==independent
    assert_path(after)
    from backend.core.deformation import deformed_helix_axes
    for expected,actual in zip(preview['helix_paths_nm'],deformed_helix_axes(after),strict=True):
        np.testing.assert_allclose(expected,actual.get('samples') or [actual['start'],actual['end']])


def test_failed_shortening_is_atomic():
    d=create()
    post('nick',dict(helix_id=d.helices[0].id,bp_index=1,direction='FORWARD'))
    before=state.get_or_404().model_dump_json()
    r=client.post('/api/design/features/0/edit',json={'params':{**params(),'points_nm':[[0,0,0],[0,0,.34]]}})
    assert r.status_code==422
    assert 'collapses' in r.text
    assert state.get_or_404().model_dump_json()==before


@pytest.mark.parametrize('end', ['5p','3p'])
@pytest.mark.parametrize('delta', [-10,10])
def test_terminal_resize_offsets_survive_repeated_length_changes(end, delta):
    d=create()
    s=next(s for s in d.strands if s.strand_type==StrandType.STAPLE)
    dom=s.domains[0]
    initial=dom.start_bp if end=='5p' else dom.end_bp
    post('strand-end-resize',{'entries':[dict(strand_id=s.id,helix_id=dom.helix_id,end=end,delta_bp=delta)]})
    for z in [28,20,35]:
        p={**params(),'points_nm':[[0,0,0],[8,0,z]]}
        post('features/0/edit',{'params':p})
        after=state.get_or_404()
        strand=next(a for a in after.strands if a.id==s.id)
        terminal=strand.domains[0 if end=='5p' else -1]
        expected=(after.deformations[0].plane_a_bp if initial==0 else after.deformations[0].plane_b_bp)+delta
        assert (terminal.start_bp if end=='5p' else terminal.end_bp)==expected
        middle=_seek_feature_log(after,1,0)
        assert middle.strands==after.strands
        assert middle.overhangs==after.overhangs


def test_mixed_history_and_repeated_attachment_edit_preserves_later_nick():
    d=create(); h=d.helices[0]; bp=h.length_bp-1
    post('bundle-deformed-continuation',dict(cells=[[0,0],[0,1]],length_bp=12,
        ref_helix_id=h.id,source_bp=bp,**deformed_frame_at_bp(d,bp,h.id)))
    appended=next(a for a in state.get_or_404().helices if a.id not in {x.id for x in d.helices})
    post('nick',dict(helix_id=appended.id,bp_index=appended.bp_start+4,direction='FORWARD'))
    old=state.get_or_404()
    for z in [28,20,35]:
        p={**params(),'points_nm':[[0,0,0],[8,0,z]]}
        preview=post('sweep/preview?feature_index=0',p)
        assert appended.id in preview['edit_helix_ids']
        assert any(appended.id in g['helix_ids'] and g['end'] == 'end' for g in preview['edit_attachment_groups'])
        post('features/0/edit',{'params':p})
        after=state.get_or_404()
        old_domains=[dm for s in old.strands for dm in s.domains if dm.helix_id==appended.id]
        new_domains=[dm for s in after.strands for dm in s.domains if dm.helix_id==appended.id]
        shift=after.find_helix(appended.id).bp_start-old.find_helix(appended.id).bp_start
        assert [d.model_copy(update={'start_bp':d.start_bp+shift,'end_bp':d.end_bp+shift}) for d in old_domains]==new_domains
        assert len([c for c in after.cluster_transforms if c.id.startswith('sweep-follow:')])==1
        from backend.core.deformation import deformed_helix_axes
        for expected,axis in zip(preview['helix_paths_nm'],deformed_helix_axes(after),strict=True):
            np.testing.assert_allclose(expected,axis.get('samples') or [axis['start'],axis['end']])


def test_trim_offset_survives_ligation_that_changes_strand_identity():
    d=create(); a,b=d.helices
    first=next(s for s in d.strands if s.domains[0].helix_id==a.id and s.domains[0].direction==Direction.FORWARD)
    second=next(s for s in d.strands if s.domains[0].helix_id==b.id and s.domains[0].direction==Direction.FORWARD)
    post('strand-end-resize',{'entries':[dict(strand_id=first.id,helix_id=a.id,end='3p',delta_bp=-5)]})
    post('forced-ligation',dict(three_prime_strand_id=first.id,five_prime_strand_id=second.id))
    post('features/0/edit',{'params':params()})
    after=state.get_or_404()
    fl=after.forced_ligations[0]
    assert fl.three_prime_bp==after.deformations[0].plane_b_bp-5
    joined=next(s for s in after.strands if len(s.domains)>1)
    assert joined.domains[0].end_bp==fl.three_prime_bp


def test_legacy_resize_diffs_recover_overhang_metadata_for_substep_seek():
    import json
    from backend.core.design_diff import _gzip_b64, _ungzip_b64
    d=create(); s=next(s for s in d.strands if s.strand_type==StrandType.STAPLE)
    dm=s.domains[0]
    post('strand-end-resize',{'entries':[dict(strand_id=s.id,helix_id=dm.helix_id,end='3p' if dm.direction==Direction.FORWARD else '5p',delta_bp=10)]})
    d=state.get_or_404(); item=d.feature_log[1]; child=item.children[0]
    # Emulate a saved design from before OverhangSpec entered the diff fields.
    payload=json.loads(_ungzip_b64(child.diff_added_b64)); payload.pop('overhangs',None)
    child=child.model_copy(update={'diff_added_b64':_gzip_b64(json.dumps(payload).encode())})
    item=item.model_copy(update={'children':[child]})
    state.set_design(d.copy_with(feature_log=[d.feature_log[0],item]))
    post('features/0/edit',{'params':params()})
    after=state.get_or_404()
    assert _seek_feature_log(after,1,0).overhangs==after.overhangs


@pytest.mark.parametrize('end', ['start','end'])
def test_attached_sweep_keeps_ordinary_backbone_continuations(end):
    from backend.core.backbone_continuations import backbone_continuation_edges
    d=create()
    post('sweep',dict(cells=[[0,0],[0,1]],source_helix_id=d.helices[0].id,source_end=end,
        points_nm=[[0,0,0],[0,0,8 if end=='end' else -8]],ligate_adjacent=False))
    before=state.get_or_404()
    assert len(backbone_continuation_edges(before))==4
    post('features/0/edit',{'params':params()})
    after=state.get_or_404()
    assert len(backbone_continuation_edges(after))==4
    assert len(backbone_continuation_edges(_seek_feature_log(after,-1)))==4
