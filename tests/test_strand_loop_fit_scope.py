"""Spatial pruning must preserve every mutable full-detector piercing."""
from types import SimpleNamespace
import numpy as np
from scipy.spatial.transform import Rotation
from backend.core.ring_piercing import SUGAR_RING, model_piercings
from backend.core.strand_loop_fit_scope import RotorPiercingIndex


def atom(name, residue):
    return SimpleNamespace(name=name, strand_id=str(residue), helix_id='h', bp_index=residue,
        direction='FORWARD', crossover_id=None, extra_base_k=None, copy_k=0,
        extension_id=None, ext_k=None, chain_id='A', seq_num=residue, residue='DA')


def test_scope_matches_full_detector_with_long_bonds_partial_rings_and_remote_hits():
    # Multiple rings plus a long incident bond: include its fixed distant endpoint,
    # not just the moving atom's radius, when bounding possible bond midpoints.
    atoms=[];xyz=[];bonds=[]
    for r in range(12):
        start=len(atoms)
        for j,name in enumerate(SUGAR_RING):
            atoms.append(atom(name,r))
            theta=2*np.pi*j/5
            xyz.append([r*1.5+.23*np.cos(theta),.23*np.sin(theta),0])
        atoms.extend([atom('P',r+20),atom("O3'",r+20)])
        xyz.extend([[r*1.5,0,-.4],[r*1.5,0,.4]])
        bonds.append((start+5,start+6))
    bonds.append((5, 11*7+6))
    model=SimpleNamespace(atoms=atoms,bonds=bonds)
    xyz=np.array(xyz)
    index=RotorPiercingIndex(model)
    for serials in [np.arange(5),np.array([0,1]),np.array([5]),np.array([5,6])]:
        states=Rotation.from_rotvec(np.deg2rad(np.arange(0,360,15))[:,None]*np.array([0,1,0])).apply(xyz[serials[0]])[:,None,:]
        states=np.repeat(states,len(serials),axis=1)+xyz[serials]-xyz[serials[0]]
        scope=index.scope(xyz,serials,states)
        own=set(serials)
        for trial in states:
            positions=xyz.copy();positions[serials]=trial
            expected={(tuple(h['bond_serials']),tuple(h['ring_serials']))
                for h in model_piercings(model,positions=positions,max_report=100000)
                if own.intersection((*h['bond_serials'],*h['ring_serials']))}
            assert scope(positions)==expected


def test_animation_changes_reuse_fit_but_sequence_edits_recompute(monkeypatch):
    from backend.core import strand_loop_ring_fit as fit
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.models import DesignAnimation
    from tests.test_strand_loops import process, params
    p = process()
    strand = p.design.strands[0]
    p.append('strand-loop-set', params(strand, 6), 'Add loop')
    calls = []
    original = fit._fit_poses
    def counted(design, records):
        calls.append(1)
        return original(design, records)
    monkeypatch.setattr(fit, '_POSE_CACHE', fit.OrderedDict())
    monkeypatch.setattr(fit, '_fit_poses', counted)
    before = _geometry_for_design(p.design)
    # Presentation-only state; no molecular authoring or history change.
    animated = p.design.model_copy(update={'animations': [DesignAnimation(name='Viewer animation')]})
    assert _geometry_for_design(animated) == before
    assert len(calls) == 1
    p.append('strand-sequence', {'_proof_version': 1, 'strand_id': strand.id,
        'sequence': 'A'*27}, 'Assign sequence')
    _geometry_for_design(p.design)
    assert len(calls) == 2


def test_remote_helix_edits_reuse_fit_but_entering_neighborhood_invalidates(monkeypatch):
    from backend.core import strand_loop_ring_fit as fit
    from backend.core.design_geometry import _geometry_for_design
    from experiments.recorded_review_process import Process
    from tests.test_strand_loops import params
    p = Process('Local fit invalidation')
    p.append('bundle-create', {'_proof_version': 1,
        'history_seed': '00000000-0000-0000-0000-000000000298',
        'cells': [[0, 0], [0, 40]], 'length_bp': 21,
        'name': 'Local fit invalidation', 'lattice_type': 'HONEYCOMB',
        'ligate_adjacent': False}, 'Create distant helices')
    p.append('strand-loop-set', params(p.design.strands[0], 6), 'Add loop')
    calls = []
    original = fit._fit_poses
    def counted(design, records):
        calls.append(1)
        return original(design, records)
    monkeypatch.setattr(fit, '_POSE_CACHE', fit.OrderedDict())
    monkeypatch.setattr(fit, '_fit_poses', counted)
    before = _geometry_for_design(p.design)
    far = p.design.helices[1]
    def move(x):
        p.append('helix-update', {'_proof_version': 1, 'helix_id': far.id,
            'length_bp': far.length_bp,
            'axis_start': {'x': x, 'y': 0, 'z': 0},
            'axis_end': {'x': x, 'y': 0, 'z': far.axis_end.z}}, 'Move other helix')
    move(150)
    after = _geometry_for_design(p.design)
    assert len(calls) == 1
    assert [r for r in before if r.get('loop_order')] == [r for r in after if r.get('loop_order')]
    # The changed helix is actually recomputed, rather than serving cached
    # whole-document geometry.
    assert [r for r in before if r['helix_id'] == far.id] != [r for r in after if r['helix_id'] == far.id]
    move(2)
    _geometry_for_design(p.design)
    assert len(calls) == 2
