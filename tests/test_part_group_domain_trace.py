"""Contributor observations are bounded and never use temporary union ancestry."""

import gc
import weakref

import pytest

from backend.core.models import Direction, Domain, Strand
from backend.core.part_command_errors import CommandContractError
from tests.test_part_group_lineage import api, grouped, refs, source as bundle


def source(*, gap=False):
    design = bundle()
    hid = design.helices[0].id
    domains = [Domain(helix_id=hid, direction=Direction.FORWARD, start_bp=0, end_bp=4 if gap else 9),
               Domain(helix_id=hid, direction=Direction.FORWARD, start_bp=10, end_bp=14 if gap else 15)]
    return grouped(design.copy_with(strands=[Strand(id="s", domains=domains)]),
                   [[("s", 0)], [("s", 1)]])


def prepare(design):
    plan = api().prepare_lineage(design, "strand-end-resize", {"entries": []})
    return plan, api().start_lineage(plan)


def candidate(design, domains):
    return design.copy_with(strands=[design.strands[0].model_copy(update={"domains": domains})])


def test_temporary_inversion_does_not_create_tail_ancestry_in_surviving_core():
    before = source()
    core, tail = before.strands[0].domains
    plan, trace = prepare(before)
    inverted = tail.model_copy(update={"end_bp": 5})
    trace.resize("s", 1, tail, inverted, end="3p")
    merged = core.model_copy(update={"end_bp": 5})
    trace.repartition("s", 0, [core, inverted], [merged])
    raw = candidate(before, [merged])
    result = api().apply_lineage(api().advance_lineage(plan, raw, trace=trace), raw)
    assert refs(result, 0) == [("s", 0)]
    assert refs(result, 1) == []


def test_native_created_gap_has_no_ancestry_but_is_required_in_final_material():
    before = source(gap=True)
    core, tail = before.strands[0].domains
    plan, trace = prepare(before)
    merged = core.model_copy(update={"end_bp": 14})
    trace.repartition("s", 0, [core, tail], [merged])
    remainder = tail.model_copy(update={"start_bp": 5})
    trace.repartition("s", 0, [merged], [core, remainder])
    gap = remainder.model_copy(update={"end_bp": 9})
    trace.repartition("s", 1, [remainder], [gap, tail])
    raw = candidate(before, [core, gap, tail])
    completed = api().advance_lineage(plan, raw, trace=trace)
    result = api().apply_lineage(completed, raw)
    assert refs(result, 0) == [("s", 0)]
    assert refs(result, 1) == [("s", 2)]
    with pytest.raises(CommandContractError) as error:
        api().apply_lineage(completed, candidate(before, [core, tail]))
    assert error.value.code == "unsupported_group_lineage_output"


def test_unobserved_native_domain_change_cannot_publish_membership():
    before = source()
    plan, trace = prepare(before)
    raw = candidate(before, [before.strands[0].domains[0].model_copy(update={"end_bp": 3}),
                             before.strands[0].domains[1]])
    with pytest.raises(CommandContractError):
        api().advance_lineage(plan, raw, trace=trace)


def test_post_retry_cannot_add_unobserved_directional_material():
    before = source()
    plan, trace = prepare(before)
    completed = api().advance_lineage(plan, before, trace=trace)
    extra = Strand(id="unobserved", domains=[before.strands[0].domains[0].model_copy(
        update={"direction": Direction.REVERSE, "start_bp": 3, "end_bp": 0})])
    with pytest.raises(CommandContractError) as error:
        api().apply_lineage(completed, before.copy_with(strands=[*before.strands, extra]))
    assert error.value.code == "unsupported_group_lineage_output"


def test_trace_is_bound_to_its_prepared_source_and_cannot_be_reused():
    before = source()
    plan, trace = prepare(before)
    other, _ = prepare(before)
    with pytest.raises(CommandContractError):
        api().advance_lineage(other, before, trace=trace)
    api().advance_lineage(plan, before, trace=trace)
    core = before.strands[0].domains[0]
    with pytest.raises(CommandContractError):
        trace.resize("s", 0, core, core, end="3p")
    with pytest.raises(CommandContractError):
        api().advance_lineage(plan, before, trace=trace)


@pytest.mark.parametrize("change", ["wrong-source", "wrong-helix", "wrong-direction", "wrong-end"])
def test_observation_cannot_relabel_or_move_unreported_endpoint(change):
    before = source()
    _, trace = prepare(before)
    core = before.strands[0].domains[0]
    old, new = core, core.model_copy(update={"end_bp": 8})
    if change == "wrong-source":
        old = old.model_copy(update={"end_bp": 7})
    elif change == "wrong-helix":
        new = new.model_copy(update={"helix_id": "elsewhere"})
    elif change == "wrong-direction":
        new = new.model_copy(update={"direction": Direction.REVERSE})
    else:
        new = new.model_copy(update={"start_bp": 1})
    with pytest.raises(CommandContractError):
        trace.resize("s", 0, old, new, end="3p")


def test_trace_retains_only_scalar_state_not_design_or_domain_objects():
    before = source()
    core = before.strands[0].domains[0]
    design_ref, domain_ref = weakref.ref(before), weakref.ref(core)
    plan, trace = prepare(before)
    trace.resize("s", 0, core, core, end="3p")
    del before, core
    gc.collect()
    assert design_ref() is None and domain_ref() is None
    assert plan is not None and trace is not None


def test_repeated_observations_have_a_cumulative_work_bound(monkeypatch):
    before = source()
    _, trace = prepare(before)
    core = before.strands[0].domains[0]
    monkeypatch.setattr(api(), "MAX_RELATIONS", 10)
    with pytest.raises(CommandContractError) as error:
        for _ in range(100):
            trace.resize("s", 0, core, core, end="3p")
    assert error.value.code == "group_lineage_limit"
