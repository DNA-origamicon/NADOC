"""Saved simulation insert particles must not break column-based result views."""
import copy
import numpy as np
from backend.core.oxdna_health import geometry_deviation_map
from backend.core.mrdna_curvature import _slab_centroids


def core():
    return [dict(helix_id='h', bp_index=i, direction='FORWARD',
                 backbone_position=[float(i), float(i % 3), float(i % 2)])
            for i in range(30)]


def insert():
    return dict(helix_id='__xb__', bp_index='54c5689d-127b-4693-bc11-f51121719fad',
                direction=0, copy=0, backbone_position=[1000., 1000., 1000.])


def test_deviation_reference_intersection_ignores_unreferenced_insert_without_mutation():
    reference = core()
    positions = core() + [insert()]
    before = copy.deepcopy(positions)
    assert geometry_deviation_map(positions, reference) == geometry_deviation_map(core(), reference)
    assert positions == before


def test_curvature_slabs_exclude_crossover_particles_without_moving_them():
    positions = core() + [insert()]
    before = copy.deepcopy(positions)
    np.testing.assert_array_equal(_slab_centroids(positions), _slab_centroids(core()))
    assert positions == before
