"""Organization follows qualified native topology, never stale domain ordinals.

All native fixtures are tiny and in memory. These tests exercise the completed
builder/retry output; no state, recovery payload, worker or molecular placement
is needed to compute the membership relation.
"""

import weakref

import pytest

from backend.core import lattice
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import Crossover, Direction, Domain, HalfCrossover, Strand
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup


def api():
    from backend.core import part_group_lineage
    return part_group_lineage


def source():
    return lattice.make_bundle_design([(0, 0)], 21)


def strand_at(design, direction):
    return next(s for s in design.strands if s.domains[0].direction == direction)


def grouped(design, selections, *, whole=False):
    groups = [PartGroup(id=f"g{index}", name=f"Selection {index}", color="#abcdef",
                        opacity=0.5, helix_ids=[design.helices[0].id],
                        domain_ids=[GroupDomainRef(strand_id=sid, domain_index=di)
                                    for sid, di in refs])
              for index, refs in enumerate(selections)]
    if whole:
        groups.append(PartGroup(id="whole", helix_ids=[h.id for h in design.helices]))
    return design.copy_with(group_organization=GroupOrganization(groups=groups))


def refs(design, index=0):
    return [(r.strand_id, r.domain_index)
            for r in design.group_organization.groups[index].domain_ids]


def selected_domains(design, index=0):
    strands = {s.id: s for s in design.strands}
    return [strands[sid].domains[di] for sid, di in refs(design, index)]


def finish(before, candidate):
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    return lattice.retry_pending_ligations(
        before, reconcile_cluster_membership(before, candidate))


def native_nick(design, direction=Direction.FORWARD, bp=8):
    return lattice.make_nick(design, design.helices[0].id, bp, direction)


def cycle_source():
    design = source()
    selected = strand_at(design, Direction.FORWARD)
    h = design.helices[0]
    return design.copy_with(strands=[selected], crossovers=[Crossover(
        id="pending-cycle", half_a=HalfCrossover(helix_id=h.id, index=20,
                                                strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h.id, index=0, strand=Direction.FORWARD))])


def test_native_retry_control_actually_changes_post_nick_strand_ownership():
    design = cycle_source()
    nicked = native_nick(design)
    completed = finish(design, nicked)
    assert len(nicked.strands) == 2 and len(completed.strands) == 1
    assert completed.strands[0].id != design.strands[0].id
    assert [(d.start_bp, d.end_bp) for d in completed.strands[0].domains] == [(9, 20), (0, 8)]


def test_native_sweep_control_prepends_new_domain_without_renaming_old_strand():
    from backend.core.sweep import SweepRequest, build_sweep
    design = source()
    old = strand_at(design, Direction.FORWARD)
    body = SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, -7 * RISE)],
                        source_helix_id=design.helices[0].id, source_end="start",
                        ligate_adjacent=False)
    result = build_sweep(design, body)
    current = result.find_strand(old.id)
    assert current.domains[0].helix_id != old.domains[0].helix_id
    assert current.domains[1] == old.domains[0]


@pytest.mark.parametrize("direction", list(Direction))
def test_native_nick_preserves_overlapping_groups_and_direction(direction):
    design = source()
    selected = strand_at(design, direction)
    opposite = next(s for s in design.strands if s.id != selected.id)
    design = grouped(design, [[(selected.id, 0)], [(selected.id, 0)], [(opposite.id, 0)]], whole=True)
    before = design.model_dump(mode="json")
    plan = api().prepare_lineage(design, "nick", {"helix_id": design.helices[0].id,
                                                "bp_index": 8, "direction": direction.value})
    completed = finish(design, native_nick(design, direction))
    result = api().apply_lineage(plan, completed)
    assert len(refs(result)) == 2 and refs(result, 1) == refs(result)
    assert all(d.direction == direction for d in selected_domains(result))
    assert refs(result, 2) == [(opposite.id, 0)]
    assert result.group_organization.groups[-1].helix_ids == [design.helices[0].id]
    assert result.model_dump(exclude={"group_organization"}) == completed.model_dump(exclude={"group_organization"})
    assert design.model_dump(mode="json") == before


def test_native_batch_nick_maps_every_child_in_final_topology_order():
    from backend.api.part_command_references import build_strict_nick_batch
    design = source()
    selected = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(selected.id, 0)]])
    params = {"nicks": [{"helix_id": design.helices[0].id, "bp_index": bp,
                         "direction": "FORWARD"} for bp in (6, 13)]}
    plan = api().prepare_lineage(design, "nick-batch", params)
    completed = finish(design, build_strict_nick_batch(design, params))
    result = api().apply_lineage(plan, completed)
    expected = [(s.id, i) for s in completed.strands for i, d in enumerate(s.domains)
                if d.direction == Direction.FORWARD]
    assert refs(result) == expected and len(expected) == 3


def test_lineage_observes_real_pending_ligation_retry_not_intermediate_nick():
    design = cycle_source()
    design = grouped(design, [[(design.strands[0].id, 0)]])
    plan = api().prepare_lineage(design, "nick", {"helix_id": design.helices[0].id,
                                                "bp_index": 8, "direction": "FORWARD"})
    completed = finish(design, native_nick(design))
    result = api().apply_lineage(plan, completed)
    assert refs(result) == [(completed.strands[0].id, 0), (completed.strands[0].id, 1)]
    assert all(sid != design.strands[0].id for sid, _ in refs(result))


@pytest.mark.parametrize("direction", list(Direction))
def test_native_actual_merge_selects_whole_descendant_for_each_parent_group(direction):
    from backend.api.crud import NickRequest
    from backend.api.part_ligation_commands import ligate
    design = native_nick(source(), direction)
    pieces = [s for s in design.strands if s.domains[0].direction == direction]
    design = grouped(design, [[(pieces[0].id, 0)], [(pieces[1].id, 0)]])
    body = NickRequest(helix_id=design.helices[0].id, bp_index=8, direction=direction)
    plan = api().prepare_lineage(design, "ligate", body.model_dump(mode="json"))
    completed = finish(design, ligate(design, body))
    result = api().apply_lineage(plan, completed)
    assert len(refs(result)) == 1 and refs(result, 1) == refs(result)
    assert abs(selected_domains(result)[0].end_bp - selected_domains(result)[0].start_bp) == 20


def joined_source():
    from backend.api.part_ligation_commands import build
    design = lattice.make_bundle_design([(0, 0), (0, 1)], 21)
    first, second = [s for s in design.strands if s.strand_type == "staple"]
    params = {"three_prime_strand_id": first.id, "five_prime_strand_id": second.id,
              "_fl_id": "forced", "is_periodic_seam": False}
    return design, params, build("forced-ligation-create", design, params)


def test_forced_ligation_concatenation_does_not_select_unrelated_domain():
    from backend.api.part_ligation_commands import build
    design, params, _ = joined_source()
    design = grouped(design, [[(params["five_prime_strand_id"], 0)]])
    plan = api().prepare_lineage(design, "forced-ligation-create", params)
    completed = finish(design, build("forced-ligation-create", design, params))
    result = api().apply_lineage(plan, completed)
    assert refs(result) == [(params["three_prime_strand_id"], 1)]


@pytest.mark.parametrize("kind", ["forced-ligation-delete", "forced-ligation-delete-batch",
                                  "crossover-delete", "crossover-delete-batch"])
def test_native_junction_delete_relocates_the_second_domain_without_adopting_first(kind):
    from backend.api.part_ligation_commands import build
    _, _, design = joined_source()
    strand = next(s for s in design.strands if len(s.domains) == 2)
    if kind.startswith("crossover"):
        a, b = strand.domains
        # Use actual adjacency with a shared junction index for the native
        # crossover-deletion selector; no crossover-placement solver is invoked.
        b = b.model_copy(update={"start_bp": a.end_bp})
        strand = strand.model_copy(update={"domains": [a, b]})
        design = design.copy_with(strands=[strand if s.id == strand.id else s for s in design.strands],
                                  forced_ligations=[], crossovers=[Crossover(id="cross", half_a=HalfCrossover(
                                      helix_id=a.helix_id, index=a.end_bp, strand=a.direction),
                                      half_b=HalfCrossover(helix_id=b.helix_id, index=b.start_bp,
                                                          strand=b.direction))])
        params = {"crossover_ids": ["cross"]} if kind.endswith("-batch") else {"crossover_id": "cross"}
    else:
        params = {"forced_ligation_ids": ["forced"]} if kind.endswith("-batch") else {"fl_id": "forced"}
    design = grouped(design, [[(strand.id, 1)]])
    old_domain = strand.domains[1].model_dump()
    plan = api().prepare_lineage(design, kind, params)
    completed = finish(design, build(kind, design, params))
    result = api().apply_lineage(plan, completed)
    assert len(refs(result)) == 1 and refs(result)[0][0] != strand.id
    assert selected_domains(result)[0].model_dump() == old_domain


@pytest.mark.parametrize("kind", ["strand-delete", "strand-delete-batch", "domain-delete"])
def test_native_delete_last_selected_domain_keeps_empty_group_without_broadening(kind):
    from backend.api.crud import (_build_delete_domain, _build_delete_strand,
                                  _build_delete_strands_batch, StrandBatchDeleteRequest)
    design = source()
    target = strand_at(design, Direction.REVERSE)
    design = grouped(design, [[(target.id, 0)]], whole=True)
    params = ({"strand_ids": [target.id]} if kind.endswith("-batch")
              else {"strand_id": target.id, **({"domain_index": 0} if kind == "domain-delete" else {})})
    plan = api().prepare_lineage(design, kind, params)
    if kind == "domain-delete":
        candidate = _build_delete_domain(design, target.id, 0)
    elif kind == "strand-delete-batch":
        candidate = _build_delete_strands_batch(design, StrandBatchDeleteRequest(**params))
    else:
        candidate = _build_delete_strand(design, target.id)
    result = api().apply_lineage(plan, finish(design, candidate))
    empty = result.group_organization.groups[0]
    assert empty.id == "g0" and empty.name == "Selection 0" and empty.color == "#abcdef"
    assert empty.domain_ids == [] and empty.helix_ids == []
    assert result.group_organization.groups[1].helix_ids == [design.helices[0].id]


@pytest.mark.parametrize("end", ["start", "end"])
@pytest.mark.parametrize("detach", [False, True])
def test_native_sweep_never_retargets_old_ordinal_to_new_material(end, detach):
    from backend.core.sweep import SweepRequest, build_sweep
    design = source()
    selected = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(selected.id, 0)], [(selected.id, 0)]], whole=True)
    before = design.model_dump(mode="json")
    sign = 1 if end == "end" else -1
    body = SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, sign * 7 * RISE)],
                        source_helix_id=design.helices[0].id, source_end=end,
                        detach_source=detach, ligate_adjacent=False)
    plan = api().prepare_lineage(design, "sweep", body.model_dump(mode="json"))
    completed = finish(design, build_sweep(design, body))
    result = api().apply_lineage(plan, completed)
    assert len(completed.helices) > len(design.helices)
    assert len(refs(result)) == 1 and refs(result, 1) == refs(result)
    assert selected_domains(result)[0].model_dump() == selected.domains[0].model_dump()
    assert result.group_organization.groups[-1].helix_ids == [design.helices[0].id]
    assert design.model_dump(mode="json") == before


@pytest.mark.parametrize("kind", ["loop-skip-insert", "assign-staple-sequences"])
def test_native_topology_preserving_commands_keep_exact_selection(kind):
    from backend.api.part_native_commands import build_loop, build_sequence
    design = source()
    if kind == "assign-staple-sequences":
        design = build_sequence("assign-scaffold-sequence", design,
                                {"custom_sequence": "ACG" * 7})
    selected = strand_at(design, Direction.REVERSE)
    design = grouped(design, [[(selected.id, 0)]])
    params = ({"helix_id": design.helices[0].id, "bp_index": 3, "delta": 1}
              if kind == "loop-skip-insert" else {})
    plan = api().prepare_lineage(design, kind, params)
    completed = finish(design, (build_loop if kind == "loop-skip-insert" else build_sequence)(kind, design, params))
    result = api().apply_lineage(plan, completed)
    assert result.group_organization == design.group_organization


@pytest.mark.parametrize("kind", ["domain-shift", "strand-end-resize", "auto-scaffold", "unknown"])
def test_unqualified_kinds_refuse_during_preparation(kind):
    design = grouped(source(), [[]])
    with pytest.raises(CommandContractError) as error:
        api().prepare_lineage(design, kind, {})
    assert error.value.code == "unsupported_group_lineage_command"


def test_legacy_absent_organization_is_an_exact_no_walk_noop():
    class NoWalk(list):
        def __iter__(self):
            raise AssertionError("Legacy topology must not be inventoried")
    design = source().copy_with(helices=NoWalk(), strands=NoWalk())
    assert api().prepare_lineage(design, "unknown", {}) is None
    assert api().apply_lineage(None, design) is design


@pytest.mark.parametrize("selection", ["missing-strand", "missing-domain", "duplicate-ref", "missing-helix"])
def test_invalid_group_selection_has_typed_reference_diagnostic(selection):
    design = source()
    sid = design.strands[0].id
    chosen = [("missing", 0)] if selection == "missing-strand" else [(sid, 9)] if selection == "missing-domain" else [(sid, 0)]
    if selection == "duplicate-ref":
        chosen *= 2
    design = grouped(design, [chosen])
    if selection == "missing-helix":
        design.group_organization.groups[0].helix_ids = ["missing"]
    before = design.model_dump()
    with pytest.raises(ReferenceResolutionError) as error:
        api().prepare_lineage(design, "nick", {})
    issue = error.value.as_issue()
    assert issue["references"] and issue["references"][0]["parameter_path"][:3] == ["group_organization", "groups", 0]
    assert design.model_dump() == before


def test_same_direction_occupancy_is_ambiguous_but_opposite_direction_is_not():
    design = source()
    design = grouped(design, [[(design.strands[0].id, 0)]])
    api().prepare_lineage(design, "nick", {})
    duplicate = design.strands[0].model_copy(update={"id": "overlapping"})
    bad = design.copy_with(strands=[*design.strands, duplicate])
    with pytest.raises(CommandContractError) as error:
        api().prepare_lineage(bad, "nick", {})
    assert error.value.code == "ambiguous_group_lineage"


def test_declared_conserving_operation_cannot_rebind_to_new_or_relocated_material():
    design = source()
    target = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(target.id, 0)]])
    plan = api().prepare_lineage(design, "nick", {})
    moved = target.domains[0].model_copy(update={"start_bp": 100, "end_bp": 120})
    after = design.copy_with(strands=[s.model_copy(update={"domains": [moved]}) if s.id == target.id else s
                                      for s in design.strands])
    before = after.model_dump()
    with pytest.raises(CommandContractError) as error:
        api().apply_lineage(plan, after)
    assert error.value.code == "unsupported_group_lineage_output"
    assert after.model_dump() == before


def test_no_per_base_expansion_or_model_serialization_for_interval_mapping(monkeypatch):
    design = source()
    h = design.helices[0]
    dom = Domain(helix_id=h.id, start_bp=0, end_bp=10**9, direction=Direction.FORWARD)
    design = grouped(design.copy_with(strands=[Strand(id="long", domains=[dom])]), [[("long", 0)]])
    def forbidden(*args, **kwargs):
        raise AssertionError("Lineage uses scalar metadata, not serialization or geometry")
    monkeypatch.setattr(type(design), "model_dump", forbidden)
    monkeypatch.setattr(Domain, "model_dump", forbidden)
    monkeypatch.setattr("backend.core.design_geometry._geometry_for_design", forbidden)
    plan = api().prepare_lineage(design, "nick", {})
    after = design.copy_with(strands=[Strand(id="left", domains=[dom.model_copy(update={"end_bp": 5})]),
                                      Strand(id="right", domains=[dom.model_copy(update={"start_bp": 6})])])
    result = api().apply_lineage(plan, after)
    assert refs(result) == [("left", 0), ("right", 0)]


def test_source_count_bound_precedes_iteration(monkeypatch):
    class NoWalk(list):
        def __iter__(self):
            raise AssertionError("Count admission must precede iteration")
    design = grouped(source(), [[]]).copy_with(strands=NoWalk([None] * 4))
    monkeypatch.setattr(api(), "MAX_ITEMS", 3)
    with pytest.raises(CommandContractError) as error:
        api().prepare_lineage(design, "nick", {})
    assert error.value.code == "group_lineage_limit"


def test_total_emitted_selection_bound_counts_overlapping_groups_times_splits(monkeypatch):
    design = source()
    selected = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(selected.id, 0)], [(selected.id, 0)], [(selected.id, 0)]])
    plan = api().prepare_lineage(design, "nick", {})
    after = finish(design, native_nick(design))
    before = after.model_dump()
    monkeypatch.setattr(api(), "MAX_EMITTED_REFS", 5)
    with pytest.raises(CommandContractError) as error:
        api().apply_lineage(plan, after)
    assert error.value.code == "group_lineage_limit"
    assert after.model_dump() == before


def test_plan_detaches_source_and_each_result_membership():
    design = source()
    selected = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(selected.id, 0)]])
    plan = api().prepare_lineage(design, "nick", {})
    after = finish(design, native_nick(design)).model_copy(deep=True)
    owner = weakref.ref(design)
    del design
    assert owner() is None, "Lineage plan must retain scalars, not the source Design"
    first = api().apply_lineage(plan, after)
    first.group_organization.groups[0].domain_ids.clear()
    first.group_organization.groups[0].name = "mutated result"
    second = api().apply_lineage(plan, after)
    assert len(refs(second)) == 2 and second.group_organization.groups[0].name == "Selection 0"
    assert after.group_organization.groups[0].name == "Selection 0"
