"""Displayed history must equal construction prefixes, not merely render something."""
import pytest

from backend.api import crud, part_proof_commands as commands, state
from backend.api.routes_feature_log import GeometryBatchBody, geometry_batch
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.part_overlay_commands import command_input
from backend.core.part_history_proof import root_design
from tools.member_motion_native_example import build


@pytest.fixture(scope='module')
def construction():
    tip = Design.from_json(build().to_json())
    prefix = root_design(tip.recipe_root)
    stages = {-2: prefix}
    for index, entry in enumerate(tip.feature_log):
        kind, params = command_input(entry)
        prefix = commands.execute(kind, prefix, params)
        stages[index] = prefix
    stages[-1] = prefix
    return tip, stages


@pytest.mark.parametrize('optimized', [False, True])
def test_scrub_back_forward_and_reset_match_independent_prefixes(construction, optimized):
    tip, stages = construction
    live = tip
    # Include a repeated tip/reset/initial visit: seeking itself replaces live state.
    for position in [0, 10, 2, 6, 7, -2, -1, 5, 1, 9, 3, 8, 4, 0, -1]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        expected = stages[position]
        assert live.nucleotide_transforms == expected.nucleotide_transforms
        assert _geometry_for_design(live) == _geometry_for_design(expected)
        assert build_atomistic_model(live, fast_bridges=True) == build_atomistic_model(expected, fast_bridges=True)


def test_animation_batch_uses_historical_base_poses_without_mutating_live_state(construction):
    tip, stages = construction
    state.load_design(tip)
    before = state.get_or_404().model_dump_json()
    try:
        samples = geometry_batch(GeometryBatchBody(positions=list(range(len(tip.feature_log)))))
        for position in range(len(tip.feature_log)):
            historical = Design.model_validate(samples[str(position)]['display_design'])
            assert historical.nucleotide_transforms == stages[position].nucleotide_transforms
            assert _geometry_for_design(historical) == _geometry_for_design(stages[position])
        assert state.get_or_404().model_dump_json() == before
    finally:
        state.close_session()


def test_make_cluster_does_not_move_geometry_and_next_feature_moves_it(construction):
    tip, stages = construction
    for index in (3, 8):
        assert tip.feature_log[index].feature_type == 'cluster_create'
        assert tip.feature_log[index + 1].feature_type == 'cluster_op'
        assert _geometry_for_design(stages[index]) == _geometry_for_design(stages[index - 1])
        assert build_atomistic_model(stages[index], fast_bridges=True) == build_atomistic_model(stages[index - 1], fast_bridges=True)
        assert _geometry_for_design(stages[index + 1]) != _geometry_for_design(stages[index])
    assert [k.feature_log_index for k in tip.animations[0].keyframes] == list(range(11))
