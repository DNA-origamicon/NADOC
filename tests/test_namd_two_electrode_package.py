import json
import math
import pytest
from backend.core.namd_two_electrode_package import electrode_layout, build_qualification_package, qualification_config
from backend.core.md_charge import parse_psf_atoms


def test_equal_opposite_charge_and_cartesian_layout():
    for axis in 'xyz':
        spec = dict(normal=axis,gap_nm=10,width_nm=4,depth_nm=5,working_charge_C_m2=-.0413)
        plan = electrode_layout(spec)
        n = plan['sites_per_electrode']
        assert math.fsum(plan['charges'][:n]) == pytest.approx(-5)
        assert plan['charges'][n:] == [-q for q in plan['charges'][:n]]
        assert {p[plan['axis']] for p in plan['positions_nm']} == {0,10}
        assert plan['realized_working_C_m2'] == pytest.approx(-.04005441585)
    with pytest.raises(ValueError,match='3×'):
        electrode_layout(spec,2)


def test_package_has_one_compartment_all_charge_correction_and_fixed_cell(tmp_path,monkeypatch):
    from backend.core import namd_solvate as solvate
    spec = dict(normal='z',gap_nm=4,width_nm=4,depth_nm=4,working_charge_C_m2=-.0413)
    def fake_water(pdb,padding,tmpdir,**kwargs):
        return [solvate._Water(1,1,z,1.095,1,z,1,1.095,z) for z in (.1,1.,2.,3.,3.9)], (4,4,4), pdb
    monkeypatch.setattr(solvate,'_gmx_solvate',fake_water)
    dest = tmp_path/'package'
    manifest = build_qualification_package(dest,spec,salt_mM=0)
    assert manifest['n_waters'] == 3
    assert manifest['cell_nm'] == [4,4,12]
    assert manifest['normal_bounds_A'] == [40,80]
    atoms = parse_psf_atoms((dest/'system.psf').read_text())
    assert math.fsum(a.charge for a in atoms) == pytest.approx(0)
    assert manifest['n_atoms'] == len(atoms)
    records = [row for row in (dest/'system.pdb').read_text().splitlines() if row.startswith('HETATM')]
    assert len(records) == len(atoms)
    assert all(40 <= float(row[46:54]) <= 80 for row in records)
    tcl = (dest/'slab.tcl').read_text()
    assert f'{len(atoms)} 0.417' in tcl
    conf = qualification_config(manifest,resident=True,steps=100)
    assert 'GPUresident on' in conf and 'tclForcesScript slab.tcl' in conf
    assert 'wrapAll off' in conf and 'langevinPiston' not in conf
    assert json.loads((dest/'manifest.json').read_text())['qualified'] is False


def test_water_clearance_uses_oxygen_center_not_hydrogen_extent(tmp_path,monkeypatch):
    from backend.core import namd_solvate as s
    water=s._Water(1,1,.34,1,1,.2443,1.092,1,.364)
    monkeypatch.setattr(s,'_gmx_solvate',lambda pdb,*a,**k:([water],(4,4,4),pdb))
    spec=dict(normal='z',gap_nm=4,width_nm=4,depth_nm=4,working_charge_C_m2=0)
    result=build_qualification_package(tmp_path/'package',spec,salt_mM=0)
    assert result['n_waters']==1


def test_experimental_water_loading_keeps_whole_molecules_and_records_clearance(tmp_path,monkeypatch):
    from backend.core import namd_solvate as s
    waters=[s._Water(1,1,z,1.095,1,z,1,1.095,z) for z in (.25,1.,3.75)]
    monkeypatch.setattr(s,'_gmx_solvate',lambda pdb,*a,**k:(waters,(4,4,4),pdb))
    spec=dict(normal='z',gap_nm=4,width_nm=4,depth_nm=4,working_charge_C_m2=0)
    default=build_qualification_package(tmp_path/'default',spec,salt_mM=0)
    candidate=build_qualification_package(tmp_path/'candidate',spec,salt_mM=0,water_oxygen_clearance_nm=.22)
    assert default['n_waters']==1
    assert candidate['n_waters']==3
    assert candidate['water_oxygen_clearance_nm']==.22
    assert candidate['n_atoms']-default['n_atoms']==6
    for value in (.1,.6,float('nan')):
        with pytest.raises(ValueError,match='Water oxygen clearance'):
            build_qualification_package(tmp_path/'invalid',spec,water_oxygen_clearance_nm=value)
