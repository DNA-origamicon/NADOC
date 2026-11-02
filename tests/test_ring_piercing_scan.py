"""Batched implementation must agree with the independent scalar intersection."""
import numpy as np
import pytest

from backend.core.ring_piercing import _scan, segment_pierces_ring


def scalar(positions, bonds, rings, limit=10000, search=0.6):
    hits = []
    for i, j in bonds:
        for label, kind, indices in rings:
            points = positions[indices]
            if np.linalg.norm(points.mean(axis=0) - (positions[i] + positions[j]) / 2) > search:
                continue
            if i in indices or j in indices:
                continue
            hit, t = segment_pierces_ring(positions[i], positions[j], points)
            if hit:
                hits.append({'bond_serials': [i,j], 'ring_serials':indices, 'ring_kind':kind,
                    'ring':label, 't':round(t,3), 'bond_len_nm':round(float(np.linalg.norm(positions[i]-positions[j])),4)})
    return hits[:limit]


@pytest.mark.parametrize('limit', [0, 1, 5, 10000])
def test_batched_scan_matches_scalar_order_hits_and_cap(limit):
    rng = np.random.default_rng(217)
    positions, rings = [], []
    for k, n in enumerate([3, 5, 6, 5, 6]):
        theta = np.linspace(0, 2*np.pi, n, endpoint=False)
        points = np.column_stack((.23*np.cos(theta), .23*np.sin(theta), .015*rng.normal(size=n)))
        indices = list(range(len(positions), len(positions)+n))
        positions.extend(points + rng.uniform(-.1, .1, size=3))
        rings.append((str(k), 'test', indices))
    start = len(positions)
    positions.extend(rng.uniform(-.35, .35, size=(600,3)))
    bonds = [(i,i+1) for i in range(start,len(positions)-1,2)] + [(0,start), (1,2)]
    positions = np.asarray(positions)
    assert _scan(positions,bonds,rings,max_report=limit) == scalar(positions,bonds,rings,limit)


def test_plane_endpoints_edges_and_shared_ring_atoms_keep_existing_decisions():
    ring = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],dtype=float) * .3
    pairs = [([.15,.15,-.2],[.15,.15,.2]), ([.15,.15,-.2],[.15,.15,0]),
             ([.15,-.1,0],[.15,.4,0]), ([.3,.15,-.2],[.3,.15,.2]),
             ([.30000001,.15,-.2],[.30000001,.15,.2])]
    positions = np.vstack([ring, *pairs])
    bonds = [(4+2*k,5+2*k) for k in range(len(pairs))] + [(0,5)]
    rings = [('square','test',[0,1,2,3])]
    assert _scan(positions,bonds,rings,max_report=100) == scalar(positions,bonds,rings)


def test_progress_is_measured_from_completed_bonds_and_can_cancel():
    positions = np.array([[0,0,0],[.3,0,0],[0,.3,0],[.1,.1,-.2],[.1,.1,.2]])
    updates = []
    hits = _scan(positions,[(3,4)]*600,[('ring','test',[0,1,2])],max_report=1000,
                 progress=lambda done,total: updates.append((done,total)))
    assert len(hits) == 600
    assert updates[-1] == (600,600)
    assert all(0 <= done <= total == 600 for done,total in updates)
    assert updates == sorted(set(updates))
    with pytest.raises(InterruptedError):
        _scan(positions,[(3,4)],[('ring','test',[0,1,2])],max_report=10,cancelled=lambda:True)
