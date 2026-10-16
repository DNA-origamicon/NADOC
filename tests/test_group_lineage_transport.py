"""Bounded metadata admission around unchanged native crossover builders."""

import pytest

from backend.core.models import Crossover, Direction, Domain, HalfCrossover, Strand
from backend.core.part_command_errors import CommandContractError
from tests.test_part_group_lineage import api, grouped, refs


def source():
    from backend.core.lattice import make_bundle_design
    design = make_bundle_design([(0, 0), (0, 1)], 42)
    a, b = [helix.id for helix in design.helices]
    strand = Strand(id="joined", domains=[
        Domain(helix_id=a, direction=Direction.FORWARD, start_bp=0, end_bp=10),
        Domain(helix_id=b, direction=Direction.REVERSE, start_bp=10, end_bp=0),
    ])
    crossover = Crossover(id="cross", half_a=HalfCrossover(
        helix_id=a, strand=Direction.FORWARD, index=10), half_b=HalfCrossover(
        helix_id=b, strand=Direction.REVERSE, index=10))
    return grouped(design.copy_with(strands=[strand], crossovers=[crossover]),
                   [[("joined", 0)], [("joined", 1)]], whole=True)


def raw_result(before, index=7):
    a, b = before.strands[0].domains
    cross = before.crossovers[0]
    return before.copy_with(strands=[before.strands[0].model_copy(update={"domains": [
        a.model_copy(update={"end_bp": index}), b.model_copy(update={"start_bp": index})]})],
        crossovers=[cross.model_copy(update={
            "half_a": cross.half_a.model_copy(update={"index": index}),
            "half_b": cross.half_b.model_copy(update={"index": index})})])


def plan(before, **overrides):
    params = {"crossover_id": "cross", "new_index": 7, **overrides}
    return api().prepare_lineage(before, "crossover-move", params)


def test_transport_uses_native_correspondence_then_final_renamed_descendants():
    before = source()
    raw = raw_result(before)
    prepared = plan(before)
    advanced = api().advance_lineage(prepared, raw)
    # A downstream retry changes the owner without changing the material.
    final = raw.copy_with(strands=[raw.strands[0].model_copy(update={"id": "survivor"})])
    result = api().apply_lineage(advanced, final)
    assert refs(result, 0) == [("survivor", 0)]
    assert refs(result, 1) == [("survivor", 1)]
    assert refs(before, 0) == [("joined", 0)]


def test_transport_is_required_before_a_move_can_publish_membership():
    before = source()
    with pytest.raises(CommandContractError) as error:
        api().apply_lineage(plan(before), raw_result(before))
    assert error.value.code == "unsupported_group_lineage_output"


@pytest.mark.parametrize("change", ["strand_id", "domain_count", "helix", "direction",
                                    "tag", "other_endpoint", "crossover_id", "crossover_index"])
def test_transport_refuses_undeclared_raw_native_output(change):
    before = source()
    prepared = plan(before)
    raw = raw_result(before)
    strand = raw.strands[0]
    domain = strand.domains[0]
    if change == "strand_id":
        strand.id = "unexpected"
    elif change == "domain_count":
        strand.domains.pop()
    elif change == "helix":
        domain.helix_id = raw.helices[1].id
    elif change == "direction":
        domain.direction = Direction.REVERSE
    elif change == "tag":
        domain.overhang_id = "unexpected"
    elif change == "other_endpoint":
        domain.start_bp = 1
    elif change == "crossover_id":
        raw.crossovers[0].id = "unexpected"
    else:
        raw.crossovers[0].half_a.index = 8
    with pytest.raises(CommandContractError):
        api().advance_lineage(prepared, raw)


def test_duplicate_move_selector_refuses_before_native_builder(monkeypatch):
    from backend.api.part_proof_commands import execute
    before = source()

    def forbidden(*args, **kwargs):
        raise AssertionError("Ambiguous selectors must refuse before native work")

    monkeypatch.setattr("backend.api.part_crossover_moves.build", forbidden)
    with pytest.raises(CommandContractError):
        execute("crossover-move-batch", before, {"_proof_version": 1, "moves": [
            {"crossover_id": "cross", "new_index": 7},
            {"crossover_id": "cross", "new_index": 14}]})


def test_oversized_crossover_container_refuses_before_iteration():
    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("Admission must bound the list before traversal")
    before = source().copy_with(crossovers=Unvisited([None] * 30_001))
    with pytest.raises(CommandContractError) as error:
        plan(before)
    assert error.value.code == "group_lineage_limit"


@pytest.mark.parametrize("field,value", [("lattice_frame_id", "frame"), ("label", "Authored"),
                                        ("direction", Direction.FORWARD),
                                        ("native_source", "pinned")])
def test_growth_with_native_metadata_loss_is_explicitly_unqualified(field, value):
    before = source()
    before.helices[0] = before.helices[0].model_copy(update={field: value})
    with pytest.raises(CommandContractError) as error:
        plan(before, new_index=50)
    assert error.value.code == "unsupported_group_lineage_output"


def test_legacy_absent_organization_never_inventory_or_transports(monkeypatch):
    before = source().copy_with(group_organization=None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy calls must not build lineage metadata")

    monkeypatch.setattr(api(), "_inventory", forbidden)
    prepared = api().prepare_lineage(before, "crossover-move", {})
    assert prepared is None
    assert api().advance_lineage(prepared, before) is None
