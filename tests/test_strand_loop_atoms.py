"""Insertion-loop atomistic display: rigid geometry, sequence, bonds and surfaces."""
from collections import defaultdict

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model, surface_atom_cloud
from backend.core.design_geometry import _geometry_for_design
from backend.core.md_base_frames import measured_base_frames, ordered_ring_indices
from backend.core.native_slab_placement import _frame
from tests.test_strand_loops import process, params


def loop_design(scaffold=True, length=6):
    p = process()
    strand = next(s for s in p.design.strands if s.is_scaffold == scaffold)
    p.append('strand-loop-set', params(strand, length), 'Add loop')
    seq = ('ACGT' * 40)[:21+length]
    p.append('strand-sequence', {'_proof_version': 1, 'strand_id': strand.id, 'sequence': seq}, 'Edit sequence')
    return p.design, strand.id, seq


def residue_key(a):
    return a.strand_id, a.helix_id, a.bp_index, a.direction, a.copy_k or 0


@pytest.mark.parametrize('scaffold', [True, False])
@pytest.mark.parametrize('length', [6, 30, 80])
def test_complete_residues_in_sequence_order_and_covalent_loop_chain(scaffold, length):
    design, sid, sequence = loop_design(scaffold, length)
    model = build_atomistic_model(design, strand_loop_display=True)
    residues = defaultdict(list)
    for a in model.atoms:
        if a.strand_id == sid:
            residues[a.seq_num].append(a)
    assert len(residues) == 21+length
    assert ''.join(group[0].residue[-1] for group in residues.values()) == sequence
    assert sorted(a.copy_k for a in model.atoms if a.strand_id == sid and a.name == 'P' and a.copy_k) == list(range(1,length+1))
    links = {frozenset(pair) for pair in model.bonds}
    grouped = [dict((a.name,a) for a in group) for group in residues.values()]
    for a,b in zip(grouped[:-1],grouped[1:]):
        assert frozenset((a["O3'"].serial,b['P'].serial)) in links
    assert all(a.serial == i for i,a in enumerate(model.atoms))
    assert all(0 <= min(bond) <= max(bond) < len(model.atoms) for bond in model.bonds)
    anchor = next(a for a in model.atoms if a.strand_id==sid and a.bp_index==10 and not a.copy_k and a.name=="O3'")
    following = next(a for a in model.atoms if a.strand_id==sid and a.bp_index==(11 if scaffold else 9) and not a.copy_k and a.name=='P')
    assert frozenset((anchor.serial,following.serial)) not in links


def test_atomistic_loop_backbone_and_ring_orientation_match_full_pose():
    design, _, _ = loop_design()
    model = build_atomistic_model(design, strand_loop_display=True)
    by_key = defaultdict(dict)
    for a in model.atoms: by_key[residue_key(a)][a.name] = a
    for r in _geometry_for_design(design):
        if not r.get('loop_order',0): continue
        atoms = by_key[(r['strand_id'],r['helix_id'],r['bp_index'],r['direction'],r['copy_k'])]
        names = {name:i for i,name in enumerate(atoms)}
        xyz = np.array([[a.x,a.y,a.z] for a in atoms.values()])
        np.testing.assert_allclose(xyz[names["O5'"]],r['backbone_position'],atol=1e-12)
        inward = np.full((1,3),np.nan)
        _, normals = measured_base_frames(xyz,np.array([names["O5'"]]),
            [(np.array([0]),ordered_ring_indices(names)[None])],xyz[[names["O5'"]]],None,None,inward_out=inward)
        np.testing.assert_allclose(_frame(inward[0],normals[0]),Rotation.from_quat(r['slab_quaternion']).as_matrix(),atol=1e-12)


def test_loop_display_keeps_existing_atoms_fixed_and_export_guard_closed():
    p = process()
    before = build_atomistic_model(p.design)
    strand = p.design.strands[0]
    p.append('strand-loop-set',params(strand),'Add loop')
    after = build_atomistic_model(p.design,strand_loop_display=True)
    key = lambda a: (*residue_key(a),a.name)
    existing = {key(a):(a.x,a.y,a.z) for a in after.atoms if not a.copy_k}
    assert {key(a):(a.x,a.y,a.z) for a in before.atoms} == existing
    with pytest.raises(ValueError,match='does not yet support'):
        build_atomistic_model(p.design)
    assert any('placeholder' in w for w in after.warnings)


def test_surface_cloud_includes_identical_loop_atoms_and_copy_identities():
    design, _, _ = loop_design()
    model = build_atomistic_model(design,strand_loop_display=True,fast_bridges=True)
    positions,radii,sids,keys = surface_atom_cloud(design)
    np.testing.assert_array_equal(positions,np.array([[a.x,a.y,a.z] for a in model.atoms],dtype=np.float32))
    assert len(radii)==len(sids)==len(keys)==len(model.atoms)
    assert all(radii>0)
    for i,a in enumerate(model.atoms):
        if a.copy_k: assert keys[i].endswith(f':{a.copy_k}')


def test_assembly_prefix_preserves_loop_attachment():
    from backend.core.assembly_flatten import _prefix_strand
    design,_,_ = loop_design()
    # Exercise the ordinary materialization adapters, not an authored flattened part.
    strand = next(s for s in design.strands if s.loops)
    prefixed = _prefix_strand(strand,'instance::','instance::')
    assert prefixed.loops[0].helix_id == prefixed.domains[0].helix_id


def test_display_cache_cannot_bypass_the_simulation_export_guard():
    from backend.core.atomistic_cache import build_atomistic_model_cached
    design, _, _ = loop_design()
    display = build_atomistic_model_cached(design, strand_loop_display=True)
    assert any(a.copy_k for a in display.atoms)
    with pytest.raises(ValueError, match='does not yet support'):
        build_atomistic_model_cached(design)


def test_surface_routes_use_the_complete_loop_model():
    from backend.api.routes_display_geometry import _can_use_surface_cloud, _display_atomistic_model
    design, _, _ = loop_design()
    assert not _can_use_surface_cloud(design)
    model = _display_atomistic_model(design)
    assert len({(a.strand_id,a.copy_k) for a in model.atoms if a.copy_k}) == 6
