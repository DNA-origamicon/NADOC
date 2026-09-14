"""PEG campaign checks exercise units, topology preservation and fail-closed assets."""
import json
from pathlib import Path
import numpy as np
import pytest
from experiments.peg_namd.campaign import HERE, cases, graft_sites, plan
from experiments.peg_namd.structure import read_pair, place_chain, write_chain
from experiments.peg_namd.build import stage, asset_paths
from experiments.peg_namd.render import configurations


def spec():
    return json.loads((HERE / 'campaign.json').read_text())


def pair_files(root, name, segid, coords, atom_type='C'):
    psf = root / f'{name}.psf'; pdb = root / f'{name}.pdb'
    atoms = [f'{i:8d} {segid:<4} 1 TST C{i} {atom_type} 0.0 12.0 0' for i in range(1, len(coords) + 1)]
    bonds = [(i, i + 1) for i in range(1, len(coords))] if name == 'chain' else []
    body = 'PSF\n\n       1 !NTITLE\n REMARKS SYNTHETIC SOFTWARE TEST ONLY\n\n'
    body += f'{len(coords):8d} !NATOM\n' + '\n'.join(atoms) + '\n\n'
    body += f'{len(bonds):8d} !NBOND: bonds\n' + ' '.join(str(x) for b in bonds for x in b) + '\n\n'
    for section in ['NTHETA', 'NPHI', 'NIMPHI', 'NDON', 'NACC']:
        body += f'       0 !{section}\n\n'
    body += '       0 !NNB\n' + ' '.join('0' for _ in coords) + '\n\n       1       0 !NGRP NST2\n       0       0       0\n'
    psf.write_text(body)
    lines = []
    for i, (x, y, z) in enumerate(coords, 1):
        line = f'ATOM  {i:5d} {"C"+str(i):<4} TST A{1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{0:6.2f}{0:6.2f}'
        lines.append(line.ljust(72) + f'{segid:<4}' + ' C  ')
    pdb.write_text('\n'.join(lines) + '\nEND\n')
    return psf, pdb


def test_campaign_rounding_and_units():
    rows = cases(spec())
    assert len(rows) == 27
    assert sorted({r['chains'] for r in rows}) == [81, 256, 441]
    assert len({r['id'] for r in rows}) == 27
    assert len({r['seed'] for r in rows}) == 27
    for r in rows:
        assert r['achieved_density_nm2'] == r['chains'] / 900
        assert all(0 <= x < 30 and 0 <= y < 30 for x, y, _ in r['sites_nm_deg'])


def test_grafts_reproducible_and_replicas_different():
    assert graft_sites([30, 30, 25], .3, 7) == graft_sites([30, 30, 25], .3, 7)
    assert graft_sites([30, 30, 25], .3, 7) != graft_sites([30, 30, 25], .3, 8)


@pytest.mark.parametrize('key,value', [('timestep_fs', 4), ('salt_NaCl_M', -1), ('repeat_units', [36, 36]), ('replicas', 0), ('box_nm', [30, float('nan'), 25]), ('graft_plane_nm', 30)])
def test_invalid_scientific_inputs(key, value):
    s = spec(); s[key] = value
    with pytest.raises(ValueError):
        cases(s)


def test_placement_preserves_geometry_topology_and_charge(tmp_path):
    psf, pdb = pair_files(tmp_path, 'chain', 'PEG', [(1, 2, 3), (2, 3, 4), (3, 4, 5)])
    pair = read_pair(psf, pdb)
    xyz = place_chain(pair, 1, 3, (1, 2, 2), 90, [30, 30, 25])
    np.testing.assert_allclose(xyz[0], [10, 20, 20])
    assert xyz[-1, 2] > xyz[0, 2]
    np.testing.assert_allclose(np.linalg.norm(xyz[1:] - xyz[:-1], axis=1), np.sqrt(3))
    write_chain(pair, xyz, 'P000', tmp_path / 'copy')
    copy = read_pair(tmp_path / 'copy.psf', tmp_path / 'copy.pdb')
    assert {a[1] for a in copy['atoms']} == {'P000'}
    assert psf.read_text().split('!NBOND')[1] == (tmp_path / 'copy.psf').read_text().split('!NBOND')[1]
    assert [a[5:] for a in pair['atoms']] == [a[5:] for a in copy['atoms']]


def test_pdb_order_mismatch_rejected(tmp_path):
    psf, pdb = pair_files(tmp_path, 'chain', 'PEG', [(0, 0, 0), (0, 0, 1.5)])
    pdb.write_text(pdb.read_text().replace('C1 ', 'X1 '))
    with pytest.raises(ValueError, match='identity'):
        read_pair(psf, pdb)


def test_chain_too_tall_rejected(tmp_path):
    psf, pdb = pair_files(tmp_path, 'chain', 'PEG', [(0, 0, 0), (0, 0, 300)])
    with pytest.raises(ValueError, match='vertical'):
        place_chain(read_pair(psf, pdb), 1, 2, (2, 2, 2), 0, [30, 30, 25])


def test_missing_assets_no_partial_package(tmp_path):
    plan(HERE / 'campaign.json', tmp_path / 'plan')
    with pytest.raises(ValueError, match='parameterized asset missing'):
        stage(tmp_path / 'plan', 'n36_s0p1_r1', HERE / 'assets.example.json', tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
    assert asset_paths(HERE / 'assets.example.json', 36)[3]


def test_no_overwrite(tmp_path):
    plan(HERE / 'campaign.json', tmp_path / 'plan')
    with pytest.raises(FileExistsError):
        plan(HERE / 'campaign.json', tmp_path / 'plan')


def test_namd_units_restart_and_no_electrode_claim():
    c = configurations(spec(), 4, 2)
    assert 'cellBasisVector1 300.0 0 0' in c['02_pilot.conf']
    assert 'run 10000000' in c['02_pilot.conf']
    assert 'binVelocities output/equilibrate.vel' in c['02_pilot.conf']
    assert 'langevinPiston off' in c['02_pilot.conf']
    assert 'eFieldOn' not in c['02_pilot.conf']
    assert 'temperature 294.0' in c['01_equilibrate.conf']


def synthetic_package(root):
    """Small, deliberately nonphysical system to exercise the file pipeline only."""
    s = spec(); s.update(box_nm=[4, 4, 5], repeat_units=[1], graft_density_nm2=[.0625], replicas=1,
                         graft_plane_nm=1, salt_NaCl_M=0)
    specfile = root / 'spec.json'; specfile.write_text(json.dumps(s))
    plan(specfile, root / 'plan')
    psf, pdb = pair_files(root, 'chain', 'PEG', [(0, 0, 0), (0, 0, 1.5), (0, 0, 3)])
    apsf, apdb = pair_files(root, 'surface', 'GOLD', [(5, 5, 5), (15, 15, 5)], 'AU')
    prm = root / 'synthetic.str'; prm.write_text('* NONPHYSICAL SOFTWARE FIXTURE\n*\nEND\n')
    registry = dict(schema_version=1, compatibility_evidence='Synthetic software fixture only',
                    water_ions_parameters=[str(HERE.parents[1] / 'backend/data/forcefield/toppar_water_ions_na.str')],
                    surface=dict(psf=str(apsf), pdb=str(apdb), parameters=[str(prm)], source='synthetic',
                                 model='neutral_fixed_gold', box_xy_nm=[4,4], top_z_nm=.5, periodic_xy_verified=True),
                    chains={'1':dict(psf=str(psf), pdb=str(pdb), parameters=[str(prm)], source='synthetic',
                                     repeat_units=1, anchor_index=1, end_index=3, chemistry='software fixture')})
    registryfile = root / 'assets.json'; registryfile.write_text(json.dumps(registry))
    output = root / 'package'
    stage(root / 'plan', 'n1_s0p0625_r1', registryfile, output)
    return output


def test_stage_supplied_assets_preserves_provenance_and_load_order(tmp_path):
    output = synthetic_package(tmp_path)
    package = json.loads((output / 'package.json').read_text())
    assert package['status'] == 'staged_not_solvated_not_engine_verified'
    assert len(package['parameters']) == 2
    assert 'readpsf chains/P000.psf' in (output / 'build.tcl').read_text()
    assert 'Au-S' in (output / '02_pilot.conf').read_text()
    assert package['inputs']['chain_psf']['sha256']
    assert not (output / 'system.psf').exists()


def test_seal_rejects_modified_built_files(tmp_path, monkeypatch):
    from experiments.peg_namd.verify_package import verify
    from experiments.peg_namd.campaign import digest
    psf, pdb = pair_files(tmp_path, 'system', 'GOLD', [(1, 1, 1), (2, 2, 2)])
    lines = pdb.read_text().splitlines()
    lines[0] = lines[0][:54] + f'{1:6.2f}{0:6.2f}' + lines[0][66:]
    lines[1] = lines[1][:54] + f'{0:6.2f}{5:6.2f}' + lines[1][66:]
    (tmp_path / 'masks.pdb').write_text('\n'.join(lines) + '\n')
    (tmp_path / 'build.complete').write_text('success')
    (tmp_path / 'package.json').write_text(json.dumps(dict(case=dict(chains=1), files=[])))
    monkeypatch.chdir(tmp_path)
    verify(seal=True)
    verify()
    before = digest('system.pdb')
    with Path('system.pdb').open('a') as f:
        f.write('REMARK changed\n')
    assert digest('system.pdb') != before
    with pytest.raises(ValueError, match='Built input modified'):
        verify()


def test_seal_does_not_accept_mask_reordering(tmp_path, monkeypatch):
    from experiments.peg_namd.verify_package import verify
    _, pdb = pair_files(tmp_path, 'system', 'GOLD', [(1, 1, 1), (2, 2, 2)])
    lines = pdb.read_text().splitlines()
    (tmp_path / 'masks.pdb').write_text('\n'.join([lines[1], lines[0]]) + '\n')
    (tmp_path / 'build.complete').write_text('success')
    (tmp_path / 'package.json').write_text(json.dumps(dict(case=dict(chains=1), files=[])))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='ordering'):
        verify(seal=True)
