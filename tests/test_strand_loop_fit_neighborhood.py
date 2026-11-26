"""The compact working set preserves mutable native contacts and piercings."""
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from backend.core.atomistic import build_atomistic_model, VDW_RADIUS
from backend.core.design_geometry import _geometry_for_design
from backend.core.ring_piercing import model_piercings
from backend.core.strand_loop_fit_neighborhood import neighborhood
from experiments.recorded_review_process import Process
from tests.test_strand_loops import params


def test_native_neighborhood_preserves_full_interactions_across_rotations():
    p = Process('Neighborhood test')
    p.append('bundle-create', {'_proof_version': 1,
        'history_seed': '00000000-0000-0000-0000-000000000198',
        'cells': [[0,0],[0,1]], 'length_bp': 126, 'name': 'Neighborhood test',
        'lattice_type': 'HONEYCOMB', 'ligate_adjacent': False}, 'Create helices')
    p.append('strand-loop-set', params(p.design.strands[0], 6), 'Add loop')
    records = _geometry_for_design(p.design)
    full = build_atomistic_model(p.design, strand_loop_display=True)
    from backend.core.strand_loop_fit_sites import fit_sites
    sites = fit_sites(p.design, records)
    assert sites is not None and len(sites) < len(records) // 2
    scoped = build_atomistic_model(p.design, strand_loop_display=True, _loop_fit_sites=sites)
    def identity(atom):
        return (atom.strand_id, atom.helix_id, atom.bp_index, atom.direction,
                atom.copy_k, atom.name)
    native = {identity(a): a for a in full.atoms}
    for atom in scoped.atoms:
        original_atom = native[identity(atom)]
        np.testing.assert_array_equal(
            [atom.x, atom.y, atom.z],
            [original_atom.x, original_atom.y, original_atom.z])
    lookup = {(r['strand_id'],r['helix_id'],r['bp_index'],r['direction'],r.get('copy_k',0)): i
              for i,r in enumerate(records)}
    ri = np.array([lookup.get((a.strand_id,a.helix_id,a.bp_index,a.direction,a.copy_k or 0),-1)
                   for a in full.atoms])
    moving = np.array([i>=0 and records[i].get('loop_order',0)>0 for i in ri])
    radii = np.array([VDW_RADIUS[a.element] for a in full.atoms])
    required = set(ri[moving])
    small, _, small_moving, _ = neighborhood(full,records,ri,required,moving,radii)
    assert len(small.atoms) < len(full.atoms)//2
    original = {id(a):i for i,a in enumerate(full.atoms)}
    serials = np.array([original[id(a)] for a in small.atoms])
    xyz = np.array([[a.x,a.y,a.z] for a in full.atoms])
    own = set(np.flatnonzero(moving))
    def keys(model, positions, mapping):
        return {(tuple(mapping[i] for i in h['bond_serials']),
                 tuple(mapping[i] for i in h['ring_serials']))
            for h in model_piercings(model,positions=positions,max_report=100000)
            if own.intersection(mapping[i] for i in (*h['bond_serials'],*h['ring_serials']))}
    for degrees in [-180,-90,-5,0,5,90,175]:
        trial = xyz.copy()
        for r in required:
            ids = np.flatnonzero(ri==r)
            bead = np.array(records[r]['backbone_position'])
            axis = np.array(records[r]['slab_position'])-bead
            axis /= np.linalg.norm(axis)
            trial[ids] = Rotation.from_rotvec(axis*np.deg2rad(degrees)).apply(xyz[ids]-bead)+bead
        assert keys(full,trial,np.arange(len(xyz))) == keys(small,trial[serials],serials)
        # Every fixed atom in the clash search radius remains available.
        large_tree = cKDTree(trial[~moving])
        small_tree = cKDTree(trial[serials[~small_moving]])
        large_ids = np.flatnonzero(~moving)
        small_ids = serials[~small_moving]
        radius = 2*radii.max()-.04
        for a,b in zip(large_tree.query_ball_point(trial[moving],radius),
                       small_tree.query_ball_point(trial[moving],radius)):
            assert set(large_ids[a]) == set(small_ids[b])
