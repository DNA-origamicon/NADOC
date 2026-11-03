import pytest
from backend.core.namd_pme import pme_grid
from backend.core.namd_resources import estimate_memory


@pytest.mark.parametrize('box,spacing,observed',[
    ((310.,310.,310.),.75,(432,432,432)),
    ((138.313873262,153.015040575,1350.68049345),.75,(192,216,1848)),
])
def test_pme_grid_matches_recorded_extreme_namd_logs(box,spacing,observed):
    assert pme_grid(box,spacing)==observed


@pytest.mark.parametrize('box,spacing',[
    ((float('nan'),10.,10.),1.),((10.,10.,10.),0.),((10.,10.),1.),
])
def test_unknown_grid_is_not_invented(box,spacing):
    with pytest.raises(ValueError):pme_grid(box,spacing)


def test_excessive_grid_is_returned_as_unsupported():
    result=estimate_memory(100000,box_angstrom=(1e9,100.,100.),check_patch=False)
    assert not result.supported
    assert result.components['pme_grid'] is None


def test_resolved_grid_tightens_cube_budget_without_removing_workspace_allowance():
    # Keep topology/neighbor allowances; resolve the formerly padded PME grid.
    e=estimate_memory(3_000_788,box_angstrom=(310.,)*3,extra_bonds=2_600_000,
                      pairlist=24,pme_spacing=.75,margin=30,threads=32,two_away=(True,)*3)
    assert e.ram_mib==11791 and e.gpu_mib<23902
    assert e.components['pme_grid']==(432,)*3
    assert e.components['gpu']['fine_pme_allowance_mib']==(432**3-216**3)*48/1024**2
    assert sum(e.components['gpu'].values()) <= e.gpu_mib
