"""A Corner must retain native Sweep transport and its loop/skip topology."""

import numpy as np
import pytest

from backend.api import headless_build as hb, state
from backend.api.crud import CreateDesignRequest, create_design
from backend.api.part_corner_commands import preflight
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_corner import CreateCornerRequest, create_corner
from backend.api.routes_sweep import create_sweep
from backend.core.corner_topology import corner_output_id
from backend.core.design_geometry import native_full_arrays_for_helix
from backend.core.models import LatticeType
from backend.core.part_history_contract import assess_part_history
from backend.core.sweep import SweepRequest
from tests.conftest import SIX_HB_CELLS


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
def test_corner_on_recorded_sweep_preserves_every_retained_site(plane):
    with hb.scratch_session(LatticeType.HONEYCOMB):
        create_design(CreateDesignRequest(name='Corner Sweep source', lattice_type='HONEYCOMB'))
        create_sweep(SweepRequest(cells=SIX_HB_CELLS, plane=plane,
            points_nm=[(0, 0, 0), (1, 2, 8), (5, 4, 24), (8, 4, 42)], ligate_adjacent=False))
        source, revision = state.copy_for_persist()
        assert any(h.loop_skips for h in source.helices)
        owner = next(c for c in source.cluster_transforms if c.name == 'Sweep')
        args = dict(cluster_id=owner.id, position_bp=63, angle_deg=90, direction_deg=15)
        guide, _ = preflight(source, args)
        create_corner(CreateCornerRequest(**args, expected_design_id=source.id, expected_revision=revision))
        result = state.get_or_404()
        center, matrix = np.asarray(guide['center_nm']), np.asarray(guide['rotation'])
        for helix in source.helices:
            before = native_full_arrays_for_helix(helix, source)
            outgoing = corner_output_id(result.feature_log[-1].params['operation_id'], 'outgoing-helix', helix.id)
            for hid, rotated in [(helix.id, False), (outgoing, True)]:
                h = result.find_helix(hid)
                assert h.loop_skips == helix.loop_skips
                after = native_full_arrays_for_helix(h, result)
                np.testing.assert_array_equal(after['bp_indices'], before['bp_indices'])
                for field in ('positions', 'base_positions'):
                    expected = (before[field]-center) @ matrix.T + center if rotated else before[field]
                    np.testing.assert_allclose(after[field], expected, atol=1e-9, rtol=0)
        proof = assess_part_history(result, execute=execute, dependencies=dependencies)
        assert proof['status'] == 'verified', repr(proof)
