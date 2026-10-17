"""Terminal extension authoring is an input recipe, including ordinary route edits."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import crud, routes_extensions as routes, state
from backend.core import models as m
from backend.core.part_history_contract import create_empty_part
from tests.test_part_transform_preview import snapshot
from tests.test_part_transform_preview_sessions import document, verified  # noqa: F401
from tests.test_part_deformation_preview_sessions import checkpoint, unchanged


def recipe():
    return snapshot(
        create_empty_part("Terminal history", "HONEYCOMB"),
        "bundle-create",
        crud.BundleRequest(
            cells=[[0, 0]], length_bp=8, ligate_adjacent=False, history_seed=uuid4()
        ).model_dump(mode="json"),
        "bundle",
    )


def add(source, **values):
    return routes.add_strand_extension(
        routes.StrandExtensionRequest(
            strand_id=source.strands[0].id, end="three_prime", sequence="acg", **values
        )
    )


def test_route_create_update_delete_replay_without_recovery(document, monkeypatch):  # noqa: F811
    source = recipe()
    state.load_design(source)
    before = checkpoint()
    created = add(source)["extension"]
    current = state.get_or_404()
    assert current.feature_log[-1].op_kind == "extension-upsert"
    assert (
        current.feature_log[-1].params["entries"][0]["extension"]["id"] == created["id"]
    )
    routes.update_strand_extension(
        created["id"],
        routes.StrandExtensionUpdateRequest(sequence="TT", label="Edited"),
    )
    assert state.get_or_404().extensions[0].sequence == "TT"
    verified(state.get_or_404())
    # Deletion must retain the existing synthetic-geometry-only fast path.
    with monkeypatch.context() as patch:
        patch.setattr(
            state,
            "reconcile_cluster_membership",
            lambda *_: pytest.fail("Deletion reconciled topology"),
        )
        routes.delete_strand_extension(created["id"])
    final = state.get_or_404()
    assert not final.extensions and final.feature_log[-1].op_kind == "extension-delete"
    verified(m.Design.model_validate_json(final.model_dump_json()))
    for _ in range(3):
        state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_batch_upsert_preserves_ids_and_records_all_results_once(document):  # noqa: F811
    source = recipe()
    state.load_design(source)
    first = add(source)["extension"]
    before = checkpoint()
    routes.upsert_strand_extensions_batch(
        routes.StrandExtensionBatchRequest(
            items=[
                routes.StrandExtensionBatchItem(
                    strand_id=source.strands[0].id, end="three_prime", sequence="tt"
                ),
                routes.StrandExtensionBatchItem(
                    strand_id=source.strands[1].id, end="five_prime", modification="cy3"
                ),
            ]
        )
    )
    current = state.get_or_404()
    assert current.extensions[0].id == first["id"]
    assert current.extensions[0].sequence == "TT" and len(current.extensions) == 2
    assert state.undo_depth() == len(before["history"]) + 1
    assert current.feature_log[-1].op_kind == "extension-upsert"
    assert [item["create"] for item in current.feature_log[-1].params["entries"]] == [
        False,
        True,
    ]
    verified(current)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


@pytest.mark.parametrize("failure", ["missing-strand", "invalid-sequence"])
def test_invalid_batch_preserves_document_and_history(document, failure):  # noqa: F811
    source = recipe()
    state.load_design(source)
    before = checkpoint()
    item = {"strand_id": source.strands[0].id, "end": "three_prime", "sequence": "AT"}
    items = [item, {**item, "strand_id": source.strands[1].id}]
    if failure == "missing-strand":
        items[1]["strand_id"] = "missing"
    else:
        items[1]["sequence"] = "AX"
    with pytest.raises(HTTPException):
        routes.upsert_strand_extensions_batch(
            routes.StrandExtensionBatchRequest(items=items)
        )
    unchanged(before)


def test_repeated_batch_terminus_keeps_last_valid_item_and_one_output(document):  # noqa: F811
    source = recipe()
    state.load_design(source)
    routes.upsert_strand_extensions_batch(
        routes.StrandExtensionBatchRequest(
            items=[
                {
                    "strand_id": source.strands[0].id,
                    "end": "five_prime",
                    "sequence": "A",
                },
                {
                    "strand_id": source.strands[0].id,
                    "end": "five_prime",
                    "sequence": "",
                    "modification": "cy3",
                },
            ]
        )
    )
    current = state.get_or_404()
    assert len(current.extensions) == 1
    assert (
        current.extensions[0].sequence is None
        and current.extensions[0].modification == "cy3"
    )
    assert len(current.feature_log[-1].params["entries"]) == 1
    verified(current)


def test_update_preserves_omitted_values_and_explicitly_clears_fields(document):  # noqa: F811
    source = recipe()
    state.load_design(source)
    identity = add(source, modification="cy3", label="Original")["extension"]["id"]
    routes.update_strand_extension(
        identity, routes.StrandExtensionUpdateRequest(sequence="", label="")
    )
    extension = state.get_or_404().extensions[0]
    assert (
        extension.sequence is None
        and extension.modification == "cy3"
        and extension.label == ""
    )
    before = checkpoint()
    with pytest.raises(HTTPException):
        routes.update_strand_extension(
            identity, routes.StrandExtensionUpdateRequest(modification="")
        )
    unchanged(before)
    verified(state.get_or_404())


def test_validation_failure_rolls_back_extension_history_and_revision(
    document, monkeypatch  # noqa: F811
):
    source = recipe()
    state.load_design(source)
    before = checkpoint()
    monkeypatch.setattr(
        state,
        "validate_design",
        lambda *_: (_ for _ in ()).throw(RuntimeError("publication failed")),
    )
    with pytest.raises(RuntimeError, match="publication failed"):
        add(source)
    after = checkpoint()
    # The shared legacy recorder restores its isolated snapshot on failure.
    for key in (
        "json",
        "revision",
        "history",
        "redo",
        "request_revision",
        "request_entry",
    ):
        assert after[key] == before[key]


def test_extension_delete_preserves_organization_but_upsert_requires_lineage_qualification():
    from tests.test_part_extension_commands import inputs
    from backend.api import part_proof_commands as commands
    from backend.core.part_command_errors import CommandContractError

    source = recipe()
    source = snapshot(source, "extension-upsert", inputs(source), "terminal")
    source = snapshot(
        source,
        "group-organize",
        {"expected_placement_ids": [owner.id for owner in source.cluster_transforms]},
        "organize",
    )
    expected = source.model_dump(mode="json", exclude={"extensions", "feature_log"})
    verified(source)
    changed = inputs(source, create=False)
    with pytest.raises(CommandContractError) as caught:
        commands.execute("extension-upsert", source, changed)
    assert caught.value.code == "unsupported_group_organization_command"
    removed = snapshot(
        source,
        "extension-delete",
        {"_proof_version": 1, "extension_ids": ["terminal"]},
        "remove",
    )
    assert (
        removed.model_dump(mode="json", exclude={"extensions", "feature_log"})
        == expected
    )
    verified(removed)


def test_earlier_extension_input_edit_preserves_identity_and_later_move_replays():
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    from tests.test_part_extension_commands import inputs
    from tests.test_part_deformation_preview import _append
    from tests.test_part_transform_preview import FEATURE, service
    from tests.test_part_deformation_preview import owned_capture

    source = recipe()
    source = snapshot(source, "extension-upsert", inputs(source), "terminal")
    owner = source.cluster_transforms[0]
    source = _append(
        source,
        m.ClusterOpLogEntry(
            id=FEATURE,
            cluster_id=owner.id,
            translation=[1, 2, 0],
            rotation=[0, 0, 0, 1],
            pivot=[0, 0, 0],
            proof_version=1,
        ),
    )
    prepared = service().prepare_from_capture(owned_capture(source), FEATURE)
    assert prepared.copy_prefix().extensions[0].sequence == "AT"
    changed = inputs(source)
    changed["entries"][0]["extension"].update(sequence="GATT", id="attempted-new-id")
    rebuilt, _preview = prepare_change(
        source, capture(source), 1, lambda: None, params=changed
    )
    assert (
        rebuilt.extensions[0].id == "terminal"
        and rebuilt.extensions[0].sequence == "GATT"
    )
    assert rebuilt.cluster_transforms[0].translation == [1, 2, 0]
    verified(rebuilt)


@pytest.mark.parametrize("invalid", [{"sequence": "AX"}, {"modification": "not-valid"}])
def test_valid_duplicate_cannot_hide_an_invalid_earlier_batch_item(document, invalid):  # noqa: F811
    source = recipe()
    state.load_design(source)
    before = checkpoint()
    valid = {"strand_id": source.strands[0].id, "end": "five_prime", "sequence": "AT"}
    with pytest.raises(HTTPException):
        routes.upsert_strand_extensions_batch(
            routes.StrandExtensionBatchRequest(
                items=[
                    {**valid, **invalid},
                    valid,
                ]
            )
        )
    unchanged(before)
