import asyncio
from types import SimpleNamespace
import pytest
from backend.core.namd_patch_grid import patch_layout,safe_patch_overrides,ensure_safe_patch_layout,two_away_options,literal_options
from backend.core.namd_resources import configuration_memory,preparation_memory_mib
from backend.core.md_protocols import apply_conf_overrides


@pytest.mark.parametrize('atoms,box,old_grid,new_grid,old_peak,new_peak',[
    # Recorded 2026-11-01 boundary probes; 18hb uses its restart cell.
    (2_979_096, (138.313873262,153.015040575,1350.68049345),
     (2,2,23), (4,5,47), 33_152, 3_343),
    (2_930_633, (310.,310.,310.),
     (5,5,5), (10,10,10), 24_357, 3_094),
])
def test_measured_extreme_patch_failures_are_repaired_before_launch(
        tmp_path,atoms,box,old_grid,new_grid,old_peak,new_peak):
    (tmp_path/'x.psf').write_text(f'{atoms} !NATOM\n')
    source=('structure x.psf\nPME yes\nGPUresident on\n'
            f'cellBasisVector1 {box[0]} 0 0\n'
            f'cellBasisVector2 0 {box[1]} 0\n'
            f'cellBasisVector3 0 0 {box[2]}\n'
            'pairlistdist 24\nPMEGridSpacing 0.75\nmargin 30\nrun 800\n')
    conf=tmp_path/'probe.conf';conf.write_text(source)
    before=configuration_memory(conf,threads=32)
    assert before.gpu_mib < 48*1024  # Spare global VRAM cannot admit this layout.
    assert not before.supported
    assert before.patch_layout['grid']==old_grid
    assert old_peak > before.patch_layout['kernel_capacity_atoms']

    repaired=apply_conf_overrides(source,None)
    conf.write_text(repaired)
    after=configuration_memory(conf,threads=32)
    assert after.supported
    assert after.patch_layout['grid']==new_grid
    assert new_peak <= after.patch_layout['patch_atoms_allowance']
    assert after.patch_layout['patch_atoms_allowance'] <= after.patch_layout['admission_capacity_atoms']
    assert after.atoms==before.atoms
    assert repaired.index('twoAway') < repaired.index('run 800')
    # Subdivision must preserve the physical box and interaction settings.
    physical=lambda text:{k:v for k,v in literal_options(text).items() if not k.startswith('twoaway')}
    assert physical(repaired)==physical(source)


@pytest.mark.parametrize('box,atoms,margin,expected_grid',[
    ([200]*3,786194,30,(7,3,3)),([200]*3,786194,23,(4,4,4)),
    ([200]*3,786194,13,(5,5,5)),([310]*3,2930633,30,(5,5,5)),
])
def test_observed_patch_grid_transitions(box,atoms,margin,expected_grid):
    layout=patch_layout(atoms,box,pairlist=24,margin=margin,threads=32)
    assert layout['grid']==expected_grid
    # The policy reserves additional occupancy headroom even for margin13,
    # which passed the earlier short probe close to the conservative allowance.
    assert not layout['supported']
    fixes=safe_patch_overrides(atoms,box,pairlist=24,margin=margin,threads=32)
    result=patch_layout(atoms,box,pairlist=24,margin=margin,threads=32,two_away=two_away_options({k.lower():v for k,v in fixes.items()}))
    assert result['supported'] and result['patch_atoms_allowance']<=9216


def cube_conf():
    return 'structure x.psf\nPME yes\ncellBasisVector1 200 0 0\ncellBasisVector2 0 200 0\ncellBasisVector3 0 0 200\npairlistdist 24\nmargin 30\nminimize 200\n'


def test_repaired_config_is_admitted_before_integration(tmp_path):
    (tmp_path/'x.psf').write_text('786194 !NATOM\n')
    conf=tmp_path/'x.conf';conf.write_text(cube_conf())
    assert not configuration_memory(conf,threads=32).supported
    fixed=ensure_safe_patch_layout(conf.read_text())
    assert fixed.index('twoAway')<fixed.index('minimize')
    assert ensure_safe_patch_layout(fixed)==fixed
    conf.write_text(fixed)
    assert configuration_memory(conf,threads=32).supported
    assert not configuration_memory(conf,threads=32,shared_bytes=4096).supported


def test_explicit_unsafe_layout_is_not_silently_overridden():
    with pytest.raises(ValueError,match='No qualified CUDA patch layout'):
        ensure_safe_patch_layout(cube_conf().replace('minimize','twoAwayX off\ntwoAwayY off\ntwoAwayZ off\nminimize'))


def test_new_overrides_are_before_run_and_safe_layout_uses_final_values():
    source=cube_conf().replace('margin 30\n','').replace('pairlistdist 24','pairlistdist 13.5')
    fixed=apply_conf_overrides(source,{'margin':30,'pairlistdist':24})
    assert fixed.index('margin')<fixed.index('minimize')
    assert fixed.index('twoAway')<fixed.index('minimize')
    assert literal_options(fixed)['pairlistdist']=='24'


def test_box_and_salt_are_in_profile_cache_identity(monkeypatch):
    from backend.core import md_vram as v
    from tests.conftest import make_6hb_design
    d=make_6hb_design(8);v.clear_profile_cache()
    a=v.estimate_profile_from_design(d,padding_nm=2,box_mode='bbox',box_size_nm=[20,20,20])
    b=v.estimate_profile_from_design(d,padding_nm=2,box_mode='bbox',box_size_nm=[31,31,31])
    c=v.estimate_profile_from_design(d,padding_nm=2,box_mode='bbox',box_size_nm=[31,31,31],mgcl2_mM=0,nacl_mM=150)
    assert b['box_nm']==(31,31,31)
    assert b['atom_upper_bound']>=2_930_633
    assert b['atom_upper_bound']>a['atom_upper_bound']*3
    assert c['ion_atoms']!=b['ion_atoms']
    assert v.estimate_profile_from_design(d,padding_nm=2,box_mode='bbox',box_size_nm=[31,31,31]) is b
    assert v.estimate_profile_from_design(d,padding_nm=2,box_mode='bbox',box_size_nm=[20,20,20])==a


def test_preflight_uses_fine_grid_and_wide_list_overrides(monkeypatch,tmp_path):
    from backend.core import md_vram as v
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'memory'))
    monkeypatch.setattr(v,'detect_vram_mb',lambda *_:12288)
    monkeypatch.setattr(v,'detect_host_ram_mb',lambda:30000)
    monkeypatch.setattr(v,'estimate_profile_from_design',lambda *a,**k:dict(dna_atoms=2930633,full_water=0,ion_atoms=0,box_nm=[31]*3))
    out=v.preflight_vram_advice(object(),stage_overrides={'*':{'pairlistdist':24,'pmegridspacing':.75,'margin':30}},threads=32)
    assert out['tier']=='a3' and 21000<out['current_vram_mb']<23000
    assert out['execution_modes']['resident']['components']['pme_grid']==(432,432,432)
    assert out['preparation_ram_mb']>=preparation_memory_mib(2930633)
    assert out['planned_patch_overrides'][0]


def test_route_forwards_resolved_box_and_stage_settings(monkeypatch):
    from backend.api import routes_md as route
    from backend.core import md_vram
    body=route.CreateJobRequest(box_mode='bbox',box_size_nm=[31]*3,threads=32,stage_overrides={'*':{'margin':30}},salt_mode='custom',ion_conc_mM=150,mg_conc_mM=5)
    monkeypatch.setattr(route,'_apply_relax_preset',lambda x:x)
    monkeypatch.setattr(route.design_state,'get_or_404',lambda:SimpleNamespace(without_reference_geometry=lambda:object()))
    seen={}
    def advice(design,**kwargs):seen.update(kwargs);return {'tier':'a3'}
    monkeypatch.setattr(md_vram,'preflight_vram_advice',advice)
    assert asyncio.run(route.preflight_md_vram(body))['tier']=='a3'
    assert seen['box_size_nm']==(31,31,31) and seen['box_mode']=='bbox'
    assert seen['threads']==32 and seen['stage_overrides']==body.stage_overrides
    assert seen['nacl_mM']==150 and seen['mgcl2_mM']==5


def test_preparation_is_refused_before_allocating_when_budget_unavailable(monkeypatch,tmp_path):
    from backend.core import md_vram,memory_budget
    from backend.core.namd_resources import prepare_with_memory_budget
    monkeypatch.setenv('NADOC_MEMORY_BUDGET_DIR',str(tmp_path/'memory'))
    monkeypatch.setattr(md_vram,'estimate_profile_from_design',lambda *a,**k:dict(atom_upper_bound=3_000_000))
    monkeypatch.setattr(memory_budget.psutil,'virtual_memory',lambda:SimpleNamespace(available=6*1024**3))
    def forbidden(*a,**k):pytest.fail('Preparation started without the required budget')
    with pytest.raises(MemoryError):prepare_with_memory_budget(forbidden,object(),tmp_path/'job')


def test_adaptive_minimization_accepts_only_the_canonical_bounded_controller(tmp_path):
    from backend.core.md_protocols import _min_conf
    (tmp_path/'x.psf').write_text('786194 !NATOM\n')
    text=_min_conf('min','x',(200,200,200),False,9600,.5,no_enm=True,n_atoms=786194,
                   overrides={'margin':30,'pairlistdist':24})
    assert text.index('twoAway')<text.index('# NADOC_ADAPTIVE_MIN_BEGIN')
    conf=tmp_path/'x.conf';conf.write_text(text)
    assert configuration_memory(conf,threads=32).supported
    conf.write_text(text.replace('minimize $nadoc_min_this','PMEGridSpacing 0.1\n    minimize $nadoc_min_this'))
    with pytest.raises(ValueError,match='Modified adaptive'):configuration_memory(conf,threads=32)


def test_patch_failure_does_not_offer_an_ineffective_binary_or_offload_retry():
    from backend.core.md_vram import describe_failure
    result=describe_failure('FATAL ERROR: CudaTileListKernel::buildTileLists, maximum shared memory allocation exceeded. Too many atoms in a patch')
    assert result.kind=='patch_capacity' and result.severity=='hard_stop'
    assert not result.retry_other_binary and result.degrade_target is None


@pytest.mark.parametrize('unqualified',[
    'colvars on', 'source extra.conf', 'run [expr 100+100]',
    'run 100; PMEGridSpacing 0.1', 'pairlistdist $unknown', 'unknownCommand',
])
def test_uncharacterized_features_and_tcl_cannot_inherit_admission(tmp_path,unqualified):
    (tmp_path/'x.psf').write_text('786194 !NATOM\n')
    conf=tmp_path/'x.conf'
    conf.write_text(ensure_safe_patch_layout(cube_conf())+'\n'+unqualified+'\n')
    with pytest.raises(ValueError):configuration_memory(conf,threads=32)
