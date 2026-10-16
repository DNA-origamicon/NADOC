"""Complete native replay and Fine Routing recovery share organization lineage."""

import pytest

from backend.api import crud
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import regenerate
from backend.core import models as m
from backend.core.design_geometry import _geometry_for_design
from backend.core.feature_evaluation import recorded_effects
from backend.core.part_history_contract import assess_part_history
from tests.test_group_organization_history import history
from tests.test_group_organization_diffs import recorded, source, organization


def test_recorded_organization_changes_are_not_described_as_superseded_noops():
    pre = source()
    post = pre.copy_with(group_organization=organization("Changed"))
    assert recorded_effects(recorded(pre, post, encode=False)).known is False


@pytest.mark.parametrize("optimized", [False, True])
def test_native_routing_children_recover_each_group_selection_and_regenerate_without_bodies(optimized):
    design, _ = history(padding=26 if optimized else 0)
    helix = design.helices[0]
    inputs = {"_proof_version": 1, "helix_id": helix.id, "bp_index": 5, "direction": "FORWARD"}
    children = [m.MinorMutationLogEntry(id="split", label="Nick", op_subtype="nick", params=inputs),
                m.MinorMutationLogEntry(id="merge", label="Ligate", op_subtype="ligate", params=inputs)]
    routing = m.RoutingClusterLogEntry(id="routing", label="Routing", children=children)
    original = design.model_dump(mode="json")
    rebuilt = regenerate(design, [*design.feature_log, routing], lambda: None)
    selected = next(g for g in rebuilt.group_organization.groups if g.id == "regrouped")
    assert len(selected.domain_ids) == 1
    split = execute("nick", design, inputs)
    assert len(next(g for g in split.group_organization.groups if g.id == "regrouped").domain_ids) == 2
    loaded = m.Design.model_validate_json(rebuilt.model_dump_json())
    index = len(loaded.feature_log) - 1
    for cursor, expected in [(-2, design), (0, split), (1, rebuilt), (0, split), (-2, design)]:
        recovered = crud._seek_feature_log(loaded, index, cursor, optimized=optimized)
        assert recovered.group_organization == expected.group_organization
        assert _geometry_for_design(recovered) == _geometry_for_design(expected)
    for entry in loaded.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned"
        elif entry.feature_type == "routing-cluster":
            entry.pre_state_gz_b64 = entry.post_state_gz_b64 = "poisoned"
            for child in entry.children:
                child.diff_added_b64 = child.diff_removed_b64 = child.diff_modified_b64 = "poisoned"
    proof = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert proof["status"] == "verified", proof
    assert design.model_dump(mode="json") == original


def test_registered_sweep_keeps_selected_original_domain_after_prepend():
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.sweep import SweepRequest
    from tests.test_part_group_lineage import grouped, source as bundle, strand_at, refs

    design = bundle()
    selected = strand_at(design, m.Direction.FORWARD)
    design = grouped(design, [[(selected.id, 0)]])
    request = SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, -7 * BDNA_RISE_PER_BP)],
        source_helix_id=design.helices[0].id, source_end="start", ligate_adjacent=False,
        sweep_id="27fca6b8-7581-4a6e-8c7f-c8859a4e230c")
    params = {**request.model_dump(mode="json"), "_proof_version": 1}
    expected = execute("sweep", design.copy_with(group_organization=None), params)
    actual = execute("sweep", design, params)
    assert refs(actual) == [(selected.id, 1)]
    assert actual.model_dump(exclude={"group_organization"}) == expected.model_dump(exclude={"group_organization"})
    assert _geometry_for_design(actual) == _geometry_for_design(expected)


def test_registered_nick_tracks_the_actual_post_retry_surviving_strand():
    from tests.test_part_group_lineage import cycle_source, grouped, refs
    design = cycle_source()
    old_id = design.strands[0].id
    design = grouped(design, [[(old_id, 0)]])
    params = {"_proof_version": 1, "helix_id": design.helices[0].id,
              "bp_index": 8, "direction": "FORWARD"}
    current = execute("nick", design, params)
    assert len(current.strands) == 1 and current.strands[0].id != old_id
    assert refs(current) == [(current.strands[0].id, 0), (current.strands[0].id, 1)]
