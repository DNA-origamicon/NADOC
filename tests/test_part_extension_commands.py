"""Extension recipes preserve authored identities and refuse broken dependencies."""

from copy import deepcopy

import pytest

from backend.api import part_proof_commands as commands
from backend.api.part_extension_commands import build, parse_command
from backend.core.part_command_errors import (
    CommandContractError,
    ReferenceResolutionError,
)
from backend.core.part_edit_identity import preserve_proof_identity
from tests.test_part_extension_history import recipe


def inputs(source, *, create=True):
    return {
        "_proof_version": 1,
        "entries": [
            {
                "create": create,
                "extension": {
                    "id": "terminal",
                    "strand_id": source.strands[0].id,
                    "end": "three_prime",
                    "sequence": "AT",
                    "modification": "cy3",
                    "label": "Terminal",
                },
            }
        ],
    }


def test_extension_only_builder_is_pure_and_dependencies_are_precise():
    source = recipe()
    before = source.model_dump_json()
    params = inputs(source)
    made = build("extension-upsert", source, params)
    assert source.model_dump_json() == before
    assert made.extensions[0].id == "terminal" and made.extensions[0].sequence == "AT"
    dependency = commands.dependencies("extension-upsert", params)
    assert {(r.kind, r.identity) for r in dependency.reads} == {
        ("strand", source.strands[0].id)
    }
    assert {(r.kind, r.identity) for r in dependency.writes} == {
        ("extension", "terminal")
    }
    assert dependency.barrier
    assert not commands.dependencies(
        "extension-delete", {"_proof_version": 1, "extension_ids": ["terminal"]}
    ).barrier
    updated = inputs(source, create=False)
    updated["entries"][0]["extension"]["sequence"] = "G"
    assert build("extension-upsert", made, updated).extensions[0].sequence == "G"
    assert made.extensions[0].sequence == "AT"
    assert not build(
        "extension-delete", made, {"_proof_version": 1, "extension_ids": ["terminal"]}
    ).extensions


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "bool-version",
        "missing-field",
        "lowercase",
        "empty",
        "oversize",
        "duplicate-id",
        "duplicate-end",
        "cycle",
    ],
)
def test_closed_extension_inputs_refuse_ambiguous_or_unbounded_recipes(fault):
    params = inputs(recipe())
    ext = params["entries"][0]["extension"]
    if fault == "unknown":
        params["opaque"] = 1
    elif fault == "bool-version":
        params["_proof_version"] = True
    elif fault == "missing-field":
        ext.pop("label")
    elif fault == "lowercase":
        ext["sequence"] = "at"
    elif fault == "empty":
        ext.update(sequence=None, modification=None)
    elif fault == "oversize":
        ext["sequence"] = "A" * 4097
    elif fault == "cycle":
        params["entries"].append(params)
    else:
        second = deepcopy(params["entries"][0])
        params["entries"].append(second)
        if fault == "duplicate-end":
            second["extension"]["id"] = "different"
        else:
            second["extension"]["end"] = "five_prime"
    with pytest.raises((ValueError, CommandContractError)):
        parse_command("extension-upsert", params)
    assert not commands.dependencies("extension-upsert", params).known


@pytest.mark.parametrize(
    "fault",
    [
        "missing-strand",
        "missing-extension",
        "occupied-terminus",
        "changed-anchor",
        "duplicate-source-id",
    ],
)
def test_broken_extension_references_refuse_before_mutating_source(fault):
    source = recipe()
    params = inputs(source)
    if fault in {"occupied-terminus", "changed-anchor", "duplicate-source-id"}:
        source = build("extension-upsert", source, params)
    if fault == "missing-strand":
        params["entries"][0]["extension"]["strand_id"] = "missing"
    elif fault == "missing-extension":
        params["entries"][0]["create"] = False
    elif fault == "changed-anchor":
        params["entries"][0]["create"] = False
        params["entries"][0]["extension"]["end"] = "five_prime"
    elif fault == "duplicate-source-id":
        source.extensions.append(source.extensions[0].model_copy(deep=True))
        params["entries"][0]["create"] = False
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as caught:
        build("extension-upsert", source, params)
    assert caught.value.references and source.model_dump_json() == before


def test_created_output_slots_survive_parameter_edits_but_update_targets_are_inputs():
    source = recipe()
    old = inputs(source)
    changed = deepcopy(old)
    changed["entries"][0]["extension"].update(id="other", sequence="GG")
    changed["entries"][0]["create"] = False
    result = preserve_proof_identity(old, changed, kind="extension-upsert")
    assert result["entries"][0]["extension"]["id"] == "terminal"
    assert result["entries"][0]["extension"]["sequence"] == "GG"
    assert result["entries"][0]["create"] is True
    with pytest.raises(ValueError):
        preserve_proof_identity(old, {"entries": []}, kind="extension-upsert")
    old["entries"][0]["create"] = False
    assert (
        preserve_proof_identity(old, changed, kind="extension-upsert")["entries"][0][
            "extension"
        ]["id"]
        == "other"
    )


@pytest.mark.parametrize("kind", ["extension-upsert", "extension-delete"])
def test_extension_commands_require_snapshot_recovery_container(kind):
    from backend.core import models as m
    from backend.core.part_history_proof import command_rows

    source = recipe()
    params = (
        inputs(source)
        if kind == "extension-upsert"
        else {"_proof_version": 1, "extension_ids": ["terminal"]}
    )
    child = m.MinorMutationLogEntry.model_construct(
        id="hostile", op_subtype=kind, label=kind, params=params
    )
    source.feature_log = [m.RoutingClusterLogEntry(id="container", children=[child])]
    with pytest.raises(ValueError, match="extensions_require_snapshot"):
        list(command_rows(source, 128))


@pytest.mark.parametrize(
    "removed,failed,reference",
    [("bundle", "create", "strand"), ("create", "edit", "extension")],
)
def test_deleted_producer_is_attributed_to_first_broken_extension_consumer(
    removed, failed, reference
):
    from backend.core.part_history_contract import assess_part_history
    from tests.test_part_transform_preview import snapshot

    source = recipe()
    create = inputs(source)
    source = snapshot(source, "extension-upsert", create, "create")
    edit = inputs(source, create=False)
    edit["entries"][0]["extension"]["sequence"] = "GG"
    source = snapshot(source, "extension-upsert", edit, "edit")
    source = snapshot(
        source,
        "extension-delete",
        {"_proof_version": 1, "extension_ids": ["terminal"]},
        "delete",
    )
    source.feature_log = [entry for entry in source.feature_log if entry.id != removed]
    report = assess_part_history(
        source, execute=commands.execute, dependencies=commands.dependencies
    )
    assert report["status"] == "failed"
    issue = next(
        item for item in report["issues"] if item["code"] == "missing_reference"
    )
    assert issue["feature_id"] == failed and issue["references"][0]["kind"] == reference
    assert "delete" in issue["possible_dependents"]
