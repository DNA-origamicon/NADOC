"""Admission boundaries must precede traversal and native geometry fitting."""

import pytest

from backend.api import part_np_application_commands as commands
from backend.core import design_geometry
from backend.core.models import Direction, LoopSkip
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from tests.test_part_np_application_commands import application_params
from tests.test_part_pending_np_connections import CREATE, native_prefix as native_prefix, pending_model


def test_aggregate_loop_descriptor_bound_refuses_before_traversing_next_list(native_prefix):
    class UnvisitedLoops(list):
        def __iter__(self):
            pytest.fail("An unadmitted aggregate loop list was traversed")

    # Each list individually fits. Deletions add no emitted bases, so only an
    # aggregate descriptor check can bound this work before the second walk.
    limit = commands.MAX_APPLICATION_BASES
    entry = LoopSkip(bp_index=0, delta=-1)
    first, second = native_prefix.helices[:2]
    source = native_prefix.model_copy(update={"helices": [
        first.model_copy(update={"length_bp": 1, "loop_skips": [entry] * limit}),
        second.model_copy(update={"length_bp": 1, "loop_skips": UnvisitedLoops([entry] * limit)}),
    ]})
    with pytest.raises(CommandContractError) as error:
        commands._work_admission(source)
    assert error.value.code == "unsupported_np_application_source"


def test_target_cannot_share_selected_radial_carrier_even_in_opposite_direction(native_prefix, monkeypatch):
    source = native_prefix.model_copy(deep=True)
    values = application_params(source)
    surface = source.find_strand(values["strand_id"])
    radial = surface.domains[0]
    target = next(item for item in source.overhangs if item.id == values["overhang_id"])
    backing = source.find_strand(target.strand_id)
    opposite = Direction.REVERSE if radial.direction == Direction.FORWARD else Direction.FORWARD
    extra = radial.model_copy(update={"direction": opposite, "overhang_id": None})
    backing.domains.append(extra)
    if backing.sequence is not None:
        backing.sequence += "A" * (abs(extra.end_bp - extra.start_bp) + 1)
    original = source.model_dump_json()
    monkeypatch.setattr(design_geometry, "fitting_geometry",
        lambda *_args, **_kwargs: pytest.fail("Shared radial carrier reached geometry fitting"))

    # The target's ordinary backing domain is valid. Its second domain would
    # keep the radial helix live after relocation, preventing a later restore.
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build(CREATE, source, values)
    assert error.value.code == "invalid_selection"
    assert any(item["parameter_path"] == ["handle_overhang_id"] for item in error.value.references)
    assert source.model_dump_json() == original


@pytest.mark.parametrize("count", [127, 128])
def test_creation_reserves_the_output_version_within_the_existing_limit(native_prefix, monkeypatch, count):
    source = native_prefix.copy_with(nanoparticle_connection_versions=[
        pending_model(native_prefix, version_id=f"retained-{index}") for index in range(count)])
    values = application_params(source)
    before = source.model_dump_json()
    if count == commands.MAX_VERSIONS:
        monkeypatch.setattr(commands, "_materialize",
            lambda *_args: pytest.fail("An over-limit output reached native materialization"))
        with pytest.raises(CommandContractError) as error:
            commands.build(CREATE, source, values)
        assert error.value.code == "unsupported_np_application_source"
    else:
        result = commands.build(CREATE, source, values)
        assert len(result.nanoparticle_connection_versions) == commands.MAX_VERSIONS
        assert sum(version.applied for version in result.nanoparticle_connection_versions) == 1
    assert source.model_dump_json() == before
