import pytest
from backend.core.namd_surface_charge import charge_plan, site_charges, charge_psf, validate_charged_sites


def test_surface_charge_area_sign_and_quantization():
    spec = dict(charge_density_C_m2=-.0413, dir=[0,0,1], pore_diameter_nm=0, layers=1)
    p = charge_plan(spec, [4,5,12], 137)
    assert p['total_charge_e'] == -5
    assert sum(site_charges(p)) == pytest.approx(-5, abs=1e-10)
    assert p['realized_C_m2'] == pytest.approx(-.04005441585)
    assert charge_plan({**spec, 'dir':[1,0,0]}, [12,4,5], 137)['total_charge_e'] == -5
    assert charge_plan({**spec, 'charge_density_C_m2':.0413}, [4,5,12], 137)['total_charge_e'] == 5
    validate_charged_sites(site_charges(p), p)
    with pytest.raises(ValueError):
        validate_charged_sites([0]*137, p)


def test_charge_boundaries_and_psf():
    spec = dict(charge_density_C_m2=-.0413, dir=[0,0,1], pore_diameter_nm=0)
    for delta in [dict(charge_density_C_m2=float('nan')), dict(pore_diameter_nm=2), dict(layers=2), dict(charge_density_C_m2=1e-6)]:
        with pytest.raises(ValueError):
            charge_plan({**spec, **delta}, [4,5,12], 2)
    p=charge_plan(spec, [4,5,12], 2)
    text='PSF EXT\n\n3 !NATOM\n1 GR0 1 GRP C NGRC 0 12 0\n2 GR0 2 GRP C NGRC 0 12 0\n3 W 1 TIP3 OH2 OT -0.834 16 0\n\n0 !NBOND\n'
    charged=charge_psf(text,p)
    assert '3 W 1 TIP3 OH2 OT -0.834 16 0' in charged
    assert sum(float(s.split()[6]) for s in charged.splitlines() if ' NGRC ' in s) == -5
    assert charge_psf(text,None)==text


def test_blank_control_solvation_is_neutral_for_either_charge(monkeypatch):
    """Exercise real PSF/ion assembly with synthetic water, without engine execution."""
    import io
    import zipfile
    import json
    from backend.core import namd_solvate as solvate
    from backend.core.models import Design
    from backend.core.md_charge import audit_psf

    def water_box(pdb, *args, **kwargs):
        waters = [solvate._Water(x*.3+1, y*.3+1, z*.3+2,
                                  x*.3+1.09572, y*.3+1, z*.3+2,
                                  x*.3+.976, y*.3+1.0927, z*.3+2)
                  for x in range(6) for y in range(6) for z in range(8)]
        return waters, (4., 5., 12.), pdb

    monkeypatch.setattr(solvate, '_gmx_solvate', water_box)
    for sign in (-1, 1):
        spec=dict(dir=[0,0,1],pore_center_nm=[0,0,0],pore_diameter_nm=0,
                  layers=1,charge_density_C_m2=sign*.0413,temperature_K=298.15)
        data=solvate.build_namd_solvated_package(Design(),graphene_only=True,
             graphene_nanopore=spec,ion_conc_mM=300,mg_conc_mM=0,
             require_full_topology=True,devices='cpu')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            psf=archive.read(next(n for n in archive.namelist() if n.endswith('.psf'))).decode()
            fast=archive.read(next(n for n in archive.namelist() if n.endswith('namd_fast.conf'))).decode()
            assert 'langevinTemp       298.15' in fast
            audit=audit_psf(psf,require_neutral=True)
            assert audit.total_charge == pytest.approx(0,abs=1e-6)
            census=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('charge_audit.json'))))['ionization']
            assert census['neutral'] is True
            assert census['n_na']-census['n_cl'] == -sign*5
            assert census['surface_charge']['total_charge_e'] == sign*5


def test_screening_draft_persists_blank_control_parameters(tmp_path, monkeypatch):
    from backend.api import routes_md
    from backend.core.md_job import MdJob
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    body=routes_md.CreateJobRequest(draft=True,graphene_nanopore=True,graphene_only=True,
        graphene_pore_diameter_nm=0,graphene_charge_density_C_m2=-.0413,
        graphene_temperature_K=298.15,salt_mode='custom',ion_conc_mM=300,mg_conc_mM=0)
    job=routes_md._spawn_draft_job(body,name='charged_control')
    saved=MdJob.load(job.job_id,tmp_path).prep_params
    assert saved['graphene_charge_density_C_m2']==-.0413
    assert saved['graphene_temperature_K']==298.15
    assert saved['ion_conc_mM']==300 and saved['mg_conc_mM']==0


def test_blank_control_preparation_receives_charge_after_descriptor_rebuild(tmp_path, monkeypatch):
    """Pin the real API handoff: saving a charged draft alone is insufficient."""
    import asyncio
    from backend.api import routes_md as routes
    from backend.core.models import Design
    from backend.core.md_prep_progress import PrepTracker, build_prep_phases
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    body = routes.CreateJobRequest(autostart=False, graphene_nanopore=True,
        graphene_only=True, graphene_pore_diameter_nm=0, seed=29,
        graphene_charge_density_C_m2=-.0413, graphene_temperature_K=298.15,
        salt_mode='custom', ion_conc_mM=300, mg_conc_mM=0)
    job = routes._spawn_draft_job(body, name='charged_handoff')
    captured = {}

    def stop_at_builder(*args, **kwargs):
        captured.update(kwargs)
        raise RuntimeError('test stops before molecular preparation')

    monkeypatch.setattr(routes, 'prepare_equilibrium_aware_namd', stop_at_builder)
    monkeypatch.setattr(routes, 'prepare_mgh_slow_release', stop_at_builder)
    asyncio.run(routes._prepare_job_bg(job_id=job.job_id, body=body,
        design=Design(), seeded=False, ion_conc_mM=300, mg_conc_mM=0,
        tracker=PrepTracker(build_prep_phases(seeded=False), clock=lambda: 0.0)))
    assert captured['graphene_only'] is True
    assert captured['graphene_nanopore']['charge_density_C_m2'] == -.0413
    assert captured['graphene_nanopore']['temperature_K'] == 298.15
