"""Whole origami command, persistence and independent replay contract."""

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import (
    assembly_state,
    headless_build as hb,
    headless_assembly_build as hab,
)
from backend.api.assembly import (
    _replay_assembly_op,
    edit_assembly_feature,
    EditAssemblyFeatureRequest,
)
from backend.api.routes_assembly_patterns import AssemblyPatternBody, create_pattern
from backend.core.models import Assembly, LatticeType
from scripts.agent_structure_guard import audit


def command(kind, ids, **parameters):
    assembly = assembly_state.get_or_404()
    return create_pattern(
        kind,
        AssemblyPatternBody(
            instance_ids=ids,
            parameters=parameters,
            expected_assembly_id=assembly.id,
            expected_revision=assembly_state.revision(),
            expected_feature_ids=[e.id for e in assembly.feature_log],
        ),
    )


@pytest.fixture
def origami():
    with hb.scratch_session(), hab.assembly_scratch_session():
        hb.new_design()
        design = hb.create_bundle([(0, 0), (0, 1)], 21, lattice=LatticeType.HONEYCOMB)
        audit(design)
        hab.new_assembly("Pattern test")
        hab.add_inline_instance(
            design, name="Origami", transform=hab.translation(10, 0, 0)
        )
        yield assembly_state.get_or_404().instances[0].id


def test_grid_ring_saved_history_replays_entire_origami(origami):
    command(
        "linear-pattern",
        [origami],
        instances=3,
        spacing=-20,
        direction="X",
        two_dimensional=True,
        instances2=2,
        spacing2=30,
        direction2="Y",
    )
    grid = assembly_state.get_or_404()
    np.testing.assert_allclose(
        [i.transform.to_array()[:3, 3] for i in grid.instances],
        [[10, 0, 0], [-10, 0, 0], [-30, 0, 0], [10, 30, 0], [-10, 30, 0], [-30, 30, 0]],
    )
    command(
        "circular-pattern",
        [origami],
        instances=4,
        total_angle=360,
        axis_point=[0, 0, 0],
        axis_direction=[0, 0, 2],
    )
    result = assembly_state.get_or_404()
    np.testing.assert_allclose(
        [i.transform.to_array()[:3, 3] for i in result.instances[-3:]],
        [[0, 10, 0], [-10, 0, 0], [0, -10, 0]],
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result.instances[-3].transform.to_array()[:3, :3],
        [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=1e-12,
    )
    with TemporaryDirectory(prefix="nadoc-pattern-replay-") as scratch:
        path = Path(scratch) / "patterns.nass"
        path.write_text(result.model_dump_json())
        reopened = Assembly.model_validate_json(path.read_text())
    replay = assembly_state.lookup_pre_state(reopened.feature_log, 0)
    for entry in reopened.feature_log:
        replay = _replay_assembly_op(replay, entry.op_kind, entry.params)
    assert [i.model_dump() for i in replay.instances] == [
        i.model_dump() for i in reopened.instances
    ]
    source = reopened.instances[0].source.design.model_dump()
    assert source["feature_log"]
    assert all(i.source.design.model_dump() == source for i in reopened.instances)
    # Edit an earlier pattern with an independent later ring; stable IDs survive.
    edit_assembly_feature(1, EditAssemblyFeatureRequest(params={"parameters": {**result.feature_log[1].params["inputs"]["parameters"], "spacing": -40}}))
    edited = assembly_state.get_or_404()
    assert edited.instances[1].transform.to_array()[0, 3] == -30
    assert [i.id for i in edited.instances] == [i.id for i in result.instances]
    assert edited.instances[-1].transform == result.instances[-1].transform


def test_invalid_and_dependent_edits_are_atomic(origami):
    before = assembly_state.get_or_404()
    with pytest.raises(HTTPException):
        command("linear-pattern", [origami], instances=3, spacing=0, direction="X")
    assert assembly_state.get_or_404() is before
    command("linear-pattern", [origami], instances=3, spacing=20, direction="X")
    copy_id = assembly_state.get_or_404().instances[-1].id
    command(
        "circular-pattern",
        [copy_id],
        instances=2,
        total_angle=180,
        axis_point=[0, 0, 0],
        axis_direction=[0, 0, 1],
    )
    before = assembly_state.get_or_404()
    with pytest.raises(HTTPException):
        edit_assembly_feature(1, EditAssemblyFeatureRequest(params={"parameters": {**before.feature_log[1].params["inputs"]["parameters"], "instances": 2}}))
    assert assembly_state.get_or_404() is before


def test_custom_direction_multiple_sources_and_undo(origami):
    from backend.api.assembly import (
        undo_assembly,
        redo_assembly,
        seek_assembly_features,
        SeekAssemblyFeaturesRequest,
    )

    source = assembly_state.get_or_404().instances[0].source.design
    hab.add_inline_instance(source, name="Second", transform=hab.translation(10, 0, 40))
    ids = [i.id for i in assembly_state.get_or_404().instances]
    command(
        "linear-pattern",
        ids,
        instances=2,
        spacing=10,
        direction="Custom",
        vector=[3, 4, 0],
    )
    result = assembly_state.get_or_404()
    np.testing.assert_allclose(
        [i.transform.to_array()[:3, 3] for i in result.instances[2:]],
        [[16, 8, 0], [16, 8, 40]],
    )
    undo_assembly()
    assert len(assembly_state.get_or_404().instances) == 2
    redo_assembly()
    assert len(assembly_state.get_or_404().instances) == 4
    seek_assembly_features(SeekAssemblyFeaturesRequest(position=1))
    assert len(assembly_state.get_or_404().instances) == 2
    seek_assembly_features(SeekAssemblyFeaturesRequest(position=-1))
    assert len(assembly_state.get_or_404().instances) == 4


def test_stale_revision_is_rejected(origami):
    assembly = assembly_state.get_or_404()
    with pytest.raises(HTTPException) as error:
        create_pattern(
            "linear-pattern",
            AssemblyPatternBody(
                instance_ids=[origami],
                parameters={"instances": 2, "spacing": 10},
                expected_assembly_id=assembly.id,
                expected_revision=assembly_state.revision() - 1,
                expected_feature_ids=[e.id for e in assembly.feature_log],
            ),
        )
    assert error.value.status_code == 409
    assert assembly_state.get_or_404() is assembly
