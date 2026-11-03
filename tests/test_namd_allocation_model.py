import json
import numpy as np
import pytest
from backend.core import namd_allocation_model as model


def test_pme_accounting_matches_independent_recorded_runtime_allocations():
    # Recorded CUDA allocation events, not values obtained from this function.
    workspace=dict(forward_bytes=3870720,backward_bytes=3870720,texture_alignment=512)
    p=model.pme_allocation(313861,(56,60,288),workspace)
    assert p['plan_pairs']==2
    assert p['expected_mib']==pytest.approx(38.179138,abs=.01)
    fine=dict(forward_bytes=30965760,backward_bytes=30965760,texture_alignment=512)
    assert model.pme_allocation(313861,(112,120,576),fine)['expected_mib']==pytest.approx(245.691986,abs=.01)


def test_unknown_workspace_is_not_assumed_zero():
    assert model.pme_allocation(100,(32,32,32),{'unavailable':'different build'})=={'unavailable':'different build'}


def test_patch_counts_wrap_and_preserve_translation():
    xyz=np.array([[1,1,1],[9,9,9],[11,11,11]],dtype=float)
    a=model.coordinate_features(xyz,(10,10,10),(2,2,2),(1,1,1))
    b=model.coordinate_features(xyz+10,(10,10,10),(2,2,2),(1,1,1))
    assert a==b and a['atoms']==3 and a['max_bin_atoms']==2
    assert a['padded_atoms']==64 and a['candidate_jtiles']>0


def test_spatial_tiles_reject_distant_pairs_without_enumerating_atom_pairs():
    # Two full tiles separated farther than cutoff, then brought together.
    a=np.repeat([[1.,1.,1.],[25.,25.,25.]],32,axis=0)
    far=model.spatial_tile_features(a,(40.,)*3,(2,)*3,(1,)*3,5.)
    a[32:]=[4.,4.,1.]
    close=model.spatial_tile_features(a,(40.,)*3,(2,)*3,(1,)*3,5.)
    assert far['spatial_jtiles']==2
    assert close['spatial_jtiles']==3


def test_summary_never_substitutes_partial_expected_peak_for_missing_stage(tmp_path,monkeypatch):
    from backend.core import namd_resources as resources,md_protocols
    from types import SimpleNamespace
    (tmp_path/'manifest.json').write_text(json.dumps({'minimization':{'name':'min'}}))
    monkeypatch.setattr(md_protocols,'segments_from_manifest',lambda _: (None,[SimpleNamespace(name='late')]))
    def estimate(path,**kwargs):
        expected={'ram_mib':900,'gpu_mib':800} if path.stem=='min' else None
        return resources.MemoryEstimate(100000,True,1500,1600,True,expected=expected)
    monkeypatch.setattr(resources,'configuration_memory',estimate)
    result=resources.prepared_resource_summary(tmp_path)
    assert result['expected_engine_peak']=={'ram_mib':None,'gpu_mib':None}
    assert result['admission']['workflow_ram_mib']==1500+resources.health_memory_mib(100000)


def test_detailed_forecast_cannot_silently_exceed_admission(tmp_path,monkeypatch):
    from backend.core.namd_resources import configuration_memory
    (tmp_path/'x.psf').write_text('100000 !NATOM\n')
    conf=tmp_path/'x.conf';conf.write_text('structure x.psf\n')
    monkeypatch.setattr(model,'prepared_allocation',lambda *a,**kw:dict(exceeds_admission=True))
    result=configuration_memory(conf,fallback_box=(100.,100.,200.))
    assert not result.supported and 'Detailed allocation' in result.limitations[-1]


def test_coordinate_topology_mismatch_does_not_produce_expected_usage(tmp_path):
    p=tmp_path/'x.pdb';p.write_text('')
    with pytest.raises(ValueError,match='count mismatch'):
        model.prepared_features(p,3,(10,10,10),{'grid':(2,2,2),'away':(1,1,1)})


def test_mismatched_build_never_executes_helper(tmp_path,monkeypatch):
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'engine_sha256':model.QUALIFIED_ENGINE}))
    monkeypatch.setenv('NADOC_CUFFT_PROBE_MANIFEST',str(manifest))
    engine=tmp_path/'namd';engine.write_text('different binary')
    def forbidden(*a,**kw):raise AssertionError('Mismatched helper executed')
    monkeypatch.setattr(model.subprocess,'run',forbidden)
    assert 'does not match' in model.matching_workspace((32,32,32),engine_binary=engine)['unavailable']
