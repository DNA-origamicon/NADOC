"""Full seam review follows displayed insert order and saved residue poses."""

from types import SimpleNamespace as NS

import numpy as np
import pytest

from backend.core.bond_review_insert_positions import insert_positions
from backend.core.models import Direction
from backend.core.vr_scene_projection import crossover_extra_base_full_projections


@pytest.mark.parametrize('reversed_order', [False, True])
@pytest.mark.parametrize('forced', [False, True])
def test_native_insert_identity_and_world_pose(reversed_order, forced):
    # A component view only; no Design is authored or published by this test.
    keys = [('a', 7, 'FORWARD'), ('b', 12, 'REVERSE')]
    sites = [dict(helix_id=h, bp_index=bp, direction=d,
                  backbone_position=p, axis_tangent=t)
             for (h, bp, d), p, t in zip(keys, [[0, 0, 0], [1, 1, 0]],
                                         [[0, 0, 1], [1, 0, 0]])]
    if forced:
        record = NS(id='seam', extra_bases='ATG',
            three_prime_helix_id='a', three_prime_bp=7, three_prime_direction=Direction.FORWARD,
            five_prime_helix_id='b', five_prime_bp=12, five_prime_direction=Direction.REVERSE)
    else:
        record = NS(id='seam', extra_bases='ATG',
            half_a=NS(helix_id='a', index=7, strand=Direction.FORWARD),
            half_b=NS(helix_id='b', index=12, strand=Direction.REVERSE))
    end = keys[int(reversed_order)]
    pose = NS(kind='extra_base', crossover_id='seam', extra_base_k=1,
              pivot=[1, 0, 0], translation=[2, 0, 0], rotation=[0, 0, 1, 0])
    view = NS(crossovers=[] if forced else [record],
              forced_ligations=[record] if forced else [],
              strands=[NS(domains=[NS(helix_id=end[0], end_bp=end[1], direction=Direction(end[2]))])],
              nucleotide_transforms=[pose], photoproduct_junctions=[])
    result = insert_positions(view, sites)
    projected = crossover_extra_base_full_projections(*sites, 'ATG',
        sim_reversed=reversed_order, local_frame_reversed=False)
    assert len(result) == 3
    for row in projected:
        expected = row.bead_center.copy()
        if row.sim_k == 1:
            expected = np.array([1, 0, 0]) + (expected-[1, 0, 0])*[-1, -1, 1] + [2, 0, 0]
        np.testing.assert_allclose(result[('__xb__', 'seam', row.sim_k)], expected, atol=1e-12)
    assert insert_positions(view, sites[:1]) == {}
