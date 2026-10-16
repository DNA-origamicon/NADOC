"""Native replay must not certify silently skipped or partially missing targets."""

import pytest

from backend.api.part_command_references import build_strict_nick_batch
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import (
    Domain,
    Helix,
    LoopSkip,
    MinorMutationLogEntry,
    OverhangSpec,
    RoutingClusterLogEntry,
    Strand,
    Vec3,
)
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_contract import assess_part_history, create_empty_part


@pytest.fixture
def part():
    helix = Helix(
        id="helix", axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=3.06), length_bp=10,
    )
    strand = Strand(id="strand", domains=[Domain(
        helix_id=helix.id, start_bp=0, end_bp=9, direction="FORWARD",
    )])
    return create_empty_part("Reference tests", "SQUARE").copy_with(
        helices=[helix], strands=[strand]
    )


def nick(helix_id="helix", bp=3):
    return {"helix_id": helix_id, "bp_index": bp, "direction": "FORWARD"}


def test_single_nick_reports_removed_helix_without_native_execution(part, monkeypatch):
    from backend.api import crud

    original = part.model_dump_json()
    monkeypatch.setattr(crud, "_build_nick", lambda *_: pytest.fail("native nick before reference check"))
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("nick", part, {"_proof_version": 1, **nick("removed")})
    assert caught.value.as_issue() == {"code": "missing_reference",
        "detail": "Command targets no longer exist", "references": [{
            "kind": "helix", "identity": "removed", "parameter_path": ["helix_id"]}]}
    assert part.model_dump_json() == original


def test_single_nick_keeps_valid_native_inputs_and_output(part):
    from backend.api.crud import NickRequest, _build_nick

    params = {"_proof_version": 1, **nick()}
    original = part.model_dump_json()
    expected = _build_nick(part, NickRequest.model_validate(nick()))
    result = execute("nick", part, params)
    assert result.strands == expected.strands
    assert params == {"_proof_version": 1, **nick()}
    assert part.model_dump_json() == original


@pytest.mark.parametrize("nicks, index", [
    ([nick("missing")], 0),
    ([nick(), nick("missing")], 1),
])
def test_missing_nick_targets_fail_before_any_partial_effect(part, nicks, index):
    before = part.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("nick-batch", part, {"_proof_version": 1, "nicks": nicks})
    assert caught.value.as_issue() == {
        "code": "missing_reference",
        "detail": "Command targets no longer exist",
        "references": [{
            "kind": "helix", "identity": "missing",
            "parameter_path": ["nicks", index, "helix_id"],
        }],
    }
    assert part.model_dump_json() == before


@pytest.mark.parametrize("nicks, failed_index", [
    ([nick(bp=20)], 0),
    ([nick(bp=9)], 0),
    ([nick(), nick()], 1),
    ([nick(), nick(bp=20)], 1),
])
def test_batch_checks_each_nick_against_sequential_state(part, nicks, failed_index):
    before = part.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("nick-batch", part, {"_proof_version": 1, "nicks": nicks})
    issue = caught.value.as_issue()
    assert issue["code"] == "invalid_selection"
    assert issue["references"][0]["parameter_path"] == [
        "nicks", failed_index, "helix_id"
    ]
    assert part.model_dump_json() == before


def test_missing_backbone_is_not_a_successful_nick(part):
    part = part.copy_with(strands=[])
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("nick-batch", part, {"_proof_version": 1, "nicks": [nick()]})
    assert caught.value.code == "invalid_selection"


def test_valid_native_batch_matches_established_builder(part):
    from backend.api.crud import NickBatchRequest, _build_nick_batch

    params = {"nicks": [nick(bp=3), nick(bp=6)]}
    assert build_strict_nick_batch(part, params) == _build_nick_batch(
        part, NickBatchRequest.model_validate(params)
    )


def test_legacy_batch_builder_retains_its_skip_behavior(part):
    from backend.api.crud import NickBatchRequest, _build_nick_batch

    one = _build_nick_batch(part, NickBatchRequest(nicks=[nick()]))
    skipped = _build_nick_batch(
        part, NickBatchRequest(nicks=[nick(), nick(), nick("missing")])
    )
    assert one == skipped


@pytest.mark.parametrize("kind, params", [
    ("nick-batch", {"nicks": [nick("missing")]}),
    ("loop-skip-clear", {
        "helix_ids": ["missing"], "plane_a_bp": 0, "plane_b_bp": 10,
    }),
])
def test_empty_recipe_with_dangling_noop_cannot_verify(kind, params):
    design = create_empty_part("Reference tests", "SQUARE")
    design.feature_log = [RoutingClusterLogEntry(children=[MinorMutationLogEntry(
        label="Missing target", op_subtype=kind,
        params={"_proof_version": 1, **params},
    )])]
    result = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert result["status"] == "failed"
    assert result["checked_commands"] == 0
    assert result["native_editable"] is False


def test_loop_clear_requires_every_selected_helix(part):
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("loop-skip-clear", part, {
            "_proof_version": 1, "helix_ids": ["helix", "missing"],
            "plane_a_bp": 0, "plane_b_bp": 10,
        })
    assert caught.value.as_issue()["references"] == [{
        "kind": "helix", "identity": "missing", "parameter_path": ["helix_ids", 1],
    }]


def test_valid_loop_clear_still_removes_only_selected_range(part):
    from backend.api.part_native_commands import build_loop

    part.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=-1), LoopSkip(bp_index=8, delta=1)]
    params = {"helix_ids": ["helix"], "plane_a_bp": 0, "plane_b_bp": 5}
    result = execute("loop-skip-clear", part, {"_proof_version": 1, **params})
    assert result.helices == build_loop("loop-skip-clear", part, params).helices
    assert result.helices[0].loop_skips == [LoopSkip(bp_index=8, delta=1)]


def test_partial_overhang_delete_reports_missing_selection(part):
    part = part.copy_with(overhangs=[OverhangSpec(
        id="overhang", helix_id="helix", strand_id="strand"
    )])
    before = part.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("overhang-bulk", part, {
            "_proof_version": 1, "action": "delete-selected",
            "overhang_ids": ["overhang", "missing"],
        })
    assert caught.value.as_issue()["references"] == [{
        "kind": "overhang", "identity": "missing", "parameter_path": ["overhang_ids", 1],
    }]
    assert part.model_dump_json() == before


@pytest.mark.parametrize("strand_id, domain_index, resource, identity, path", [
    ("missing", 0, "strand", "missing", "strand_id"),
    ("strand", 1, "domain", "strand:1", "domain_index"),
    ("strand", -1, "domain", "strand:-1", "domain_index"),
])
def test_domain_shift_exposes_missing_strand_or_domain(
    part, strand_id, domain_index, resource, identity, path
):
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("domain-shift", part, {"_proof_version": 1, "entries": [{
            "strand_id": strand_id, "domain_index": domain_index, "delta_bp": 1,
        }]})
    assert caught.value.as_issue()["references"] == [{
        "kind": resource, "identity": identity, "parameter_path": ["entries", 0, path],
    }]


@pytest.mark.parametrize("strand_id, helix_id, code", [
    ("missing", "helix", "missing_reference"),
    ("strand", "missing", "missing_reference"),
    ("strand", "other", "invalid_selection"),
])
def test_resize_requires_existing_matching_terminal_selection(part, strand_id, helix_id, code):
    part = part.copy_with(helices=[
        *part.helices, part.helices[0].model_copy(update={"id": "other"})
    ])
    with pytest.raises(ReferenceResolutionError) as caught:
        execute("strand-end-resize", part, {"_proof_version": 1, "entries": [{
            "strand_id": strand_id, "helix_id": helix_id, "end": "3p", "delta_bp": 1,
        }]})
    assert caught.value.code == code


def test_internal_key_error_is_not_reclassified_as_a_dependency(part, monkeypatch):
    from backend.core import lattice

    def broken(*_args):
        raise KeyError("implementation defect")

    monkeypatch.setattr(lattice, "shift_domains", broken)
    with pytest.raises(KeyError, match="implementation defect"):
        execute("domain-shift", part, {"_proof_version": 1, "entries": [{
            "strand_id": "strand", "domain_index": 0, "delta_bp": 1,
        }]})


def test_diagnostic_paths_are_independent_json_values():
    reference = {"kind": "helix", "identity": "missing", "parameter_path": ["helix_ids", 0]}
    error = ReferenceResolutionError("Missing target", references=[reference])
    reference["parameter_path"].append("changed")
    issue = error.as_issue()
    issue["references"][0]["parameter_path"].append("changed again")
    assert error.as_issue()["references"][0]["parameter_path"] == ["helix_ids", 0]
