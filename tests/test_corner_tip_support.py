"""Cut planning uses the actual native rigid-atom envelope, not cylinder radius."""

import math
from collections import defaultdict

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import headless_build as hb, state
from backend.api.corner_guide import corner_guide
from backend.api.routes_deformation import AddDeformationBody, add_deformation
from backend.core.atomistic import build_atomistic_model, VDW_RADIUS, DEFAULT_VDW_RADIUS
from backend.core.corner_plan import CornerParameters
from backend.core.corner_routing import DuplexCut
from backend.core.corner_tip_support import FLEXIBLE_PHOSPHATE_ATOMS, rigid_tip_support, refine_duplex_cuts
from backend.core.models import LatticeType
from tests.conftest import SIX_HB_CELLS


@pytest.mark.parametrize('lattice,cells,plane', [
    (LatticeType.HONEYCOMB, SIX_HB_CELLS, 'XY'),
    (LatticeType.SQUARE, [[0, i] for i in range(8)], 'XZ'),
])
def test_rigid_support_matches_independent_atomistic_build(lattice, cells, plane):
    with hb.scratch_session(lattice):
        hb.create_bundle(cells, 168, lattice=lattice, plane=plane, separate_fresh_extrusions=False)
        marked = state.get_or_404().helices[0].id
        hb.loop_skip(marked, 80, 1)
        hb.loop_skip(marked, 85, -1)
        hb.full_sequence()
        hb.add_cluster('Tip support', [h.id for h in state.get_or_404().helices], log=True)
        owner = next(c for c in state.get_or_404().cluster_transforms if c.name == 'Tip support')
        add_deformation(AddDeformationBody(type='twist', plane_a_bp=0, plane_b_bp=126,
            cluster_ids=[owner.id], params={'kind': 'twist', 'total_degrees': 30}))
        hb.transform_cluster(owner.id, translation=[3, -2, 5], pivot=[1, 3, 7],
            rotation=Rotation.from_euler('xyz', [15, 20, -10], degrees=True).as_quat().tolist(),
            commit=True, log=True)
        source = state.get_or_404()
        before = source.model_dump_json()
        guide = corner_guide(source, owner.id, CornerParameters(84, 90, 15))
        center, normal, matrix = (np.asarray(guide[k]) for k in ('center_nm', 'plane_normal', 'rotation'))
        support = rigid_tip_support(source, source.helices, center, normal, matrix)
        model = build_atomistic_model(source)
        atom_rows = defaultdict(list)
        for atom in model.atoms:
            if atom.name not in FLEXIBLE_PHOSPHATE_ATOMS:
                atom_rows[(atom.helix_id, atom.bp_index)].append(atom)
        for helix in source.helices:
            rows = support[helix.id]
            for i, bp in enumerate(rows['stations']):
                atoms = atom_rows[(helix.id, bp)]
                xyz = np.asarray([[a.x, a.y, a.z] for a in atoms])
                radius = np.asarray([VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) for a in atoms])
                assert rows['incoming_max'][i] == pytest.approx(((xyz-center) @ normal+radius).max(), abs=1e-10)
                assert rows['outgoing_min'][i] == pytest.approx(((xyz-center) @ matrix.T @ normal-radius).min(), abs=1e-10)
        original = [DuplexCut(c['helix_id'], math.floor(c['incoming_bp']), math.ceil(c['outgoing_bp']))
                    for c in guide['cuts']]
        refined = refine_duplex_cuts(original, support)
        for old, new in zip(original, refined):
            row = support[new.helix_id]
            assert new.incoming_last_bp <= old.incoming_last_bp
            assert new.outgoing_first_bp >= old.outgoing_first_bp
            assert row['incoming_max'][row['stations'] <= new.incoming_last_bp].max() <= 0
            assert row['outgoing_min'][row['stations'] >= new.outgoing_first_bp].min() >= 0
        assert source.model_dump_json() == before
