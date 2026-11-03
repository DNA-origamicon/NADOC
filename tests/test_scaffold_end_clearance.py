"""End-turn search must validate the final bow site, on both helices."""
import pytest

from backend.api import headless_build as build, state
from backend.api.routes_sweep import create_sweep
from backend.core.models import LatticeType
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.sweep import SweepRequest
from tests.test_group_organization_history import _verified
from tests.test_scaffold_continuations import _assert_routed_contract

CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2),
         (1, 4), (1, 5), (0, 5), (0, 4)]


def test_same_cell_extrude_sweep_skips_near_site_with_two_bp_clearance():
    # Reproduce test.nadoc through public, recorded authoring operations.
    with build.scratch_session():
        source = build.create_bundle(CELLS, 56, lattice=LatticeType.HONEYCOMB)
        create_sweep(SweepRequest(
            cells=CELLS,
            points_nm=[(0, 0, 0), (0, 13.01427642891104, 18.408057500584952),
                       (-25.977535346791882, 26.02855285782208, 36.816115001169905)],
            source_helix_id=next(h.id for h in source.helices if h.grid_pos == (1, 2)),
            source_end='end',
        ))
        seed = state.get_or_404().model_copy(deep=True)
        out = build.auto_scaffold()
        _assert_routed_contract(seed, out, seamed=True)
        vertical = [x for x in out.crossovers if x.process_id == 'create_near_ends'
                    and out.find_helix(x.half_a.helix_id).grid_pos[0]
                    != out.find_helix(x.half_b.helix_id).grid_pos[0]]
        assert vertical
        assert {x.half_a.index for x in vertical} == {-12}  # next legal bow-right, past -2
        assert len(out.feature_log) == len(seed.feature_log) + 1
        _verified(out)  # independent replay must reproduce the complete routed process


@pytest.mark.parametrize('length', [42, 43, 49, 50, 51, 54, 56, 63, 232])
def test_matched_far_turns_reserve_clearance_after_left_partner_normalization(length):
    with build.scratch_session():
        build.create_bundle(CELLS, length, lattice=LatticeType.HONEYCOMB)
        out = build.auto_scaffold()
        assert scaffold_routing_invariants(out) == []
        near = {tuple(sorted((x.half_a.helix_id, x.half_b.helix_id))): x.half_a.index
                for x in out.crossovers if x.process_id == 'create_near_ends'}
        far = {tuple(sorted((x.half_a.helix_id, x.half_b.helix_id))): x.half_a.index
               for x in out.crossovers if x.process_id == 'create_far_ends'}
        assert len(near) == len(far) == 5
        assert len({far[pair] - bp for pair, bp in near.items()}) == 1
        assert all(bp >= length - 1 + 3 for bp in far.values())
