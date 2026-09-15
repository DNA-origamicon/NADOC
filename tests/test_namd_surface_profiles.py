import numpy as np
import pytest
from backend.core.namd_surface_profiles import summarize_profiles, fit_screening


def test_slab_concentration_charge_and_two_face_normalization():
    # One Na+ and Cl- per 1 nm³ bin = 1660.54 mM, each face individually.
    counts=np.ones((8,2,2,10))
    result=summarize_profiles(counts,np.linspace(0,5,11),2,0)
    assert result['concentration_mM']['positive']['Na+']==pytest.approx([1660.539067]*10)
    assert result['concentration_mM']['negative']['Cl-']==pytest.approx([1660.539067]*10)
    assert result['net_charge_e']==0
    assert result['screening_fit']['available'] is False
    assert result['concentration_block_sem_mM']['positive']['Na+']==[0]*10


def test_finite_slit_oracle_recovers_length_and_rejects_overscreening():
    x=np.linspace(.1,3.65,100); length=.55
    residual=np.sinh((3.65-x)/length)/np.sinh(3.65/length)
    fit=fit_screening(x,residual,3.65,.6,2.)
    assert fit['available']
    assert fit['lambda_nm']==pytest.approx(length,rel=1e-5)
    assert fit['r_squared']>.9999
    assert not fit_screening(x,-residual,3.65,.6,2.)['available']


def test_exact_neutralization_and_block_change_not_hidden():
    counts=np.ones((8,2,2,10))
    counts[:,:,0,0]+=5
    result=summarize_profiles(counts,np.linspace(0,5,11),2,-10)
    assert result['net_charge_e']==0
    assert result['compensated_fraction'][-1]==1
    counts[-2:,:,0,0]+=2
    result=summarize_profiles(counts,np.linspace(0,5,11),2,-10)
    assert result['first_last_concentration_rms_mM']>0


def test_api_rejects_bad_options():
    from backend.api.routes_md_surface_profiles import SurfaceProfileRequest
    for kwargs in [dict(bins=0),dict(discard_fraction=1),dict(dielectric=float('nan'))]:
        with pytest.raises(ValueError): SurfaceProfileRequest(**kwargs)


def test_live_dcd_profile_wraps_surface_and_discards_rollback(tmp_path, monkeypatch):
    import json
    from backend.core.dcd_fast import write_trajectory
    from backend.core.namd_surface_profiles import analyze_surface_package
    from backend.core import namd_graphene
    monkeypatch.setattr(namd_graphene,'validate_graphene_wall_package',lambda p:None)
    spec=dict(pore_diameter_nm=0,layers=1,cell_policy='fixed_volume',periodic_box_nm=[2,2,6],dir=[0,0,1],plane_point_nm=[1,1,3],temperature_K=298.15)
    (tmp_path/'manifest.json').write_text(json.dumps({'graphene_nanopore':spec}))
    (tmp_path/'test.psf').write_text('PSF\n\n3 !NATOM\n1 G 1 GRP C NGRC 0 12 0\n2 I 1 SOD NA SOD 1 23 0\n3 I 2 CLA CL CLA -1 35 0\n')
    xyz=np.array([[10,10,30],[10,10,92.5],[10,10,28]],dtype=np.float32)
    base=tmp_path/'stage.dcd'; cont=tmp_path/'stage.cont1.dcd'
    write_trajectory(base,3,[xyz]*4,4,istart=0,nsavc=10)
    write_trajectory(cont,3,[xyz]*2,2,istart=20,nsavc=10)
    with cont.open('ab') as f:f.write(b'partial frame')
    result=analyze_surface_package(tmp_path,'test',[('stage','NVT',base),('stage','NVT',cont)],bins=30,discard_fraction=0)
    assert result['frames']==4 # continuation replaces old frames at steps 20 and 30
    assert result['net_charge_e']==0
    assert result['concentration_mM']['positive']['Na+'][2]>0 # 92.5Å wraps to +0.25nm
    assert sum(result['concentration_mM']['negative']['Na+'])==0


def test_api_persists_and_reloads_result_and_reports_pending(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_md, routes_md_surface_profiles as routes
    from types import SimpleNamespace
    job=SimpleNamespace(name_stem='test',status=SimpleNamespace(value='running'),package_dir=lambda ws:tmp_path,job_dir=lambda ws:tmp_path)
    monkeypatch.setattr(routes_md,'_load_job',lambda id:job)
    monkeypatch.setattr(routes_md,'_workspace',lambda:tmp_path)
    monkeypatch.setattr(routes_md,'_md_segment_dcds',lambda job:[])
    monkeypatch.setattr(routes,'analyze_surface_package',lambda *a,**k:{'frames':8,'net_charge_e':0})
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    assert client.get('/md/jobs/test/surface-profiles').status_code==404
    posted=client.post('/md/jobs/test/surface-profiles',json={})
    assert posted.status_code==200
    assert client.get('/md/jobs/test/surface-profiles').json()==posted.json()
    def pending(*a,**k):raise ValueError('No complete frames yet')
    monkeypatch.setattr(routes,'analyze_surface_package',pending)
    assert client.post('/md/jobs/test/surface-profiles',json={}).status_code==409
    assert client.get('/md/jobs/test/surface-profiles').json()==posted.json()


@pytest.mark.parametrize('changing', [False, True])
def test_pressure_equilibrated_profiles_use_actual_nvt_cell(tmp_path, monkeypatch, changing):
    import io, json, struct
    from backend.core.dcd_fast import write_header, append_frame
    from backend.core import namd_graphene
    from backend.core.namd_surface_profiles import analyze_surface_package
    monkeypatch.setattr(namd_graphene, 'validate_graphene_wall_package', lambda p: None)
    spec = dict(pore_diameter_nm=0, layers=1, cell_policy='fixed_area_normal_pressure',
                periodic_box_nm=[2, 2, 6], dir=[0, 0, 1], plane_point_nm=[1, 1, 1])
    (tmp_path/'manifest.json').write_text(json.dumps({'graphene_nanopore': spec}))
    (tmp_path/'test.psf').write_text('PSF\n\n3 !NATOM\n1 G 1 GRP C NGRC 0 12 0\n2 I 1 SOD NA SOD 1 23 0\n3 I 2 CLA CL CLA -1 35 0\n')
    stream = io.BytesIO(); write_header(stream, 3, 2)
    header = bytearray(stream.getvalue()); struct.pack_into('<i', header, 48, 1)
    path = tmp_path/'production.dcd'
    with path.open('wb') as f:
        f.write(header)
        for z in [50, 52 if changing else 50]:
            f.write(struct.pack('<i6di', 48, 20, 0, 20, 0, 0, z, 48))
            append_frame(f, np.array([[10, 10, 10], [10, 10, 12.5], [10, 10, 7.5]], dtype=np.float32))
    def analyze():
        return analyze_surface_package(tmp_path, 'test', [('production', 'NVT', path)], bins=25, discard_fraction=0)
    if changing:
        with pytest.raises(ValueError, match='cell changed'):
            analyze()
    else:
        result = analyze()
        assert result['half_depth_nm'] == 2.5
        assert result['net_charge_e'] == 0
        assert result['concentration_mM']['positive']['Na+'][2] == pytest.approx(1660.539067 / .4)
