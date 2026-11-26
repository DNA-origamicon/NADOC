"""Regression against the demonstrated, user-approved bond-only candidate."""
import json
from unittest.mock import patch
from pathlib import Path

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.strand_loop_bond_fit import ANGLES, ZERO, landmarks, optimal_states
from experiments.loop_orientation_comparison import build_input
from tests.test_strand_loop_atoms import loop_design

CASES = json.loads((Path(__file__).parent/'data/loop_bond_optimum_angles.json').read_text())['cases']


@pytest.mark.parametrize('case', CASES)
def test_production_angles_match_reviewed_bond_optimum(tmp_path, case):
    (tmp_path/'inputs').mkdir()
    _, _, design, proof = build_input(tmp_path,case['length'],case['bp'],case['direction'])
    assert proof['status']=='verified'
    records=_geometry_for_design(design)
    assert [r['loop_bond_rotation_deg'] for r in records if r.get('loop_order',0)]==case['angles']


@pytest.mark.parametrize('scaffold', [True,False])
def test_native_and_loop_landmarks_match_actual_sequence_specific_atoms(scaffold):
    design,_,_=loop_design(scaffold,30)
    model=build_atomistic_model(design,strand_loop_display=True)
    atoms={}
    for a in model.atoms:
        atoms.setdefault((a.strand_id,a.helix_id,a.bp_index,a.direction,a.copy_k or 0),{})[a.name]=a
    for r in _geometry_for_design(design):
        group=atoms[(r['strand_id'],r['helix_id'],r['bp_index'],r['direction'],r.get('copy_k',0))]
        record={**r,'nucleobase':group['P'].residue[-1]}
        np.testing.assert_allclose(landmarks(record,bool(r.get('loop_order',0))),[[group[n].x,group[n].y,group[n].z] for n in ('P',"O3'")],atol=1e-12,rtol=0)


def test_chain_solver_matches_exhaustive_two_rotor_oracle():
    rng=np.random.default_rng(6126)
    p=[rng.normal(size=(n,3)) for n in (1,72,72,1)]
    o=[rng.normal(size=(n,3)) for n in (1,72,72,1)]
    bounds=np.array([np.linalg.norm(o[0][0]-p[1][ZERO]),np.linalg.norm(o[1][ZERO]-p[2][ZERO]),np.linalg.norm(o[2][ZERO]-p[3][0])])
    candidates=[]
    for i in range(72):
        for j in range(72):
            lengths=np.array([np.linalg.norm(o[0][0]-p[1][i]),np.linalg.norm(o[1][i]-p[2][j]),np.linalg.norm(o[2][j]-p[3][0])])
            if np.all(lengths<=bounds+1e-10) and np.all(lengths>=np.minimum(bounds,.16)-1e-10):
                cost=np.sum((lengths-.16)**2)+1e-12*np.sum(np.deg2rad(ANGLES[[i,j]])**2)
                candidates.append((float(cost),[i,j]))
    assert optimal_states(p,o)==min(candidates)[1]


@pytest.mark.parametrize('scaffold', [True, False])
def test_sequence_specific_fit_never_lengthens_actual_loop_linkers(scaffold):
    design,_,_=loop_design(scaffold,30)
    from backend.core.strand_loop_bond_fit import fit_loop_bonds
    from backend.core.strand_loops import strand_entries
    with patch('backend.core.strand_loop_ring_fit.refine_loop_geometry'):
        records = _geometry_for_design(design)
    strand = next(s for s in design.strands if s.loops)
    entries = list(strand_entries(design, strand))
    by_key = {(r['helix_id'], r['bp_index'], r['direction'], r.get('copy_k', 0)): r
              for r in records if r['strand_id'] == strand.id}
    loop = strand.loops[0]
    start = entries.index((loop.helix_id, loop.bp_index, loop.direction, 0))
    chain = [dict(by_key[k], nucleobase=strand.sequence[start+i])
             for i, k in enumerate(entries[start:start+loop.length+2])]
    def lengths():
        xyz = [landmarks(r, 0<i<len(chain)-1) for i,r in enumerate(chain)]
        return np.array([np.linalg.norm(a[1]-b[0]) for a,b in zip(xyz,xyz[1:])])
    before = lengths()
    fit_loop_bonds(chain[0], chain[1:-1], chain[-1])
    assert np.all(lengths() <= before + 1e-10)
