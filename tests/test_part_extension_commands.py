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


def inputs(source, *, create=True, version=1):
    return {
        "_proof_version": version,
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


@pytest.mark.parametrize("version", [1, 2])
def test_extension_only_builder_is_pure_and_dependencies_are_precise(version):
    source = recipe()
    before = source.model_dump_json()
    params = inputs(source, version=version)
    made = build("extension-upsert", source, params)
    assert source.model_dump_json() == before
    assert made.extensions[0].id == "terminal" and made.extensions[0].sequence == "AT"
    dependency = commands.dependencies("extension-upsert", params)
    inventory = {("part", "extensions")} if version == 2 else set()
    assert {(r.kind, r.identity) for r in dependency.reads} == {
        ("strand", source.strands[0].id)
    } | inventory
    assert {(r.kind, r.identity) for r in dependency.writes} == {
        ("extension", "terminal")
    } | inventory
    assert dependency.barrier is (version == 1)
    assert not commands.dependencies(
        "extension-delete", {"_proof_version": 1, "extension_ids": ["terminal"]}
    ).barrier
    updated = inputs(source, create=False, version=version)
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
@pytest.mark.parametrize("version", [1, 2])
def test_closed_extension_inputs_refuse_ambiguous_or_unbounded_recipes(fault, version):
    params = inputs(recipe(), version=version)
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
@pytest.mark.parametrize("version", [1, 2])
def test_broken_extension_references_refuse_before_mutating_source(fault, version):
    source = recipe()
    params = inputs(source, version=version)
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


@pytest.mark.parametrize("version", [1, 2])
def test_created_output_slots_survive_parameter_edits_but_update_targets_are_inputs(version):
    source = recipe()
    old = inputs(source, version=version)
    changed = deepcopy(old)
    changed["entries"][0]["extension"].update(id="other", sequence="GG")
    changed["entries"][0]["create"] = False
    result = preserve_proof_identity(old, changed, kind="extension-upsert")
    assert result["entries"][0]["extension"]["id"] == "terminal"
    assert result["entries"][0]["extension"]["sequence"] == "GG"
    assert result["entries"][0]["create"] is True
    assert result["_proof_version"] == version
    with pytest.raises(ValueError):
        preserve_proof_identity(old, {"entries": []}, kind="extension-upsert")
    old["entries"][0]["create"] = False
    assert (
        preserve_proof_identity(old, changed, kind="extension-upsert")["entries"][0][
            "extension"
        ]["id"]
        == "other"
    )


@pytest.mark.parametrize("kind,version", [("extension-upsert", 1), ("extension-upsert", 2),
                                         ("extension-delete", 1)])
def test_extension_commands_require_snapshot_recovery_container(kind, version):
    from backend.core import models as m
    from backend.core.part_history_proof import command_rows

    source = recipe()
    params = (
        inputs(source, version=version)
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


@pytest.mark.parametrize("version", [True, False, 0, 3, 2.0, "2", None])
def test_upsert_version_admission_is_strict_and_local(version):
    from backend.core.part_overlay_commands import proof_version_supported

    params = inputs(recipe(), version=version)
    with pytest.raises(CommandContractError):
        parse_command("extension-upsert", params)
    assert not commands.dependencies("extension-upsert", params).known
    assert not proof_version_supported("extension-upsert", version)


def test_v2_support_is_local_and_visible_without_changing_global_proof_version():
    from backend.core.part_overlay_commands import proof_version_supported

    assert proof_version_supported("extension-upsert", 1)
    assert proof_version_supported("extension-upsert", 2)
    assert proof_version_supported("cluster_create", 2)
    assert not proof_version_supported("extension-delete", 2)
    assert not proof_version_supported("cluster_op", 2)
    assert not proof_version_supported("bundle-create", 2)
    params = {"_proof_version": 2, "extension_ids": ["terminal"]}
    with pytest.raises(CommandContractError):
        parse_command("extension-delete", params)
    assert not commands.dependencies("extension-delete", params).known
    capabilities = commands.capabilities()
    assert capabilities["proof_version"] == 1
    assert capabilities["proof_version_overrides"]["extension-upsert"] == {
        "supported": [1, 2], "authoring": 2,
    }


@pytest.mark.parametrize("organized", [False, True])
def test_v2_dispatch_is_extension_only_and_never_enters_topology_postprocessing(monkeypatch, organized):
    from backend.core import cluster_reconcile, lattice
    from tests.test_part_transform_preview import snapshot

    source = recipe()
    if organized:
        source = snapshot(source, "group-organize", {
            "expected_placement_ids": [owner.id for owner in source.cluster_transforms],
        }, "organize")
    before = source.model_dump_json()
    params = inputs(source, version=2)
    expected = build("extension-upsert", source, params)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Version 2 extension authoring entered global topology postprocessing")

    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", forbidden)
    monkeypatch.setattr(lattice, "retry_pending_ligations", forbidden)
    result = commands.execute("extension-upsert", source, params)
    assert result.model_dump_json() == expected.model_dump_json()
    assert source.model_dump_json() == before
    result.extensions[0].sequence = "G"
    assert not source.extensions and params["entries"][0]["extension"]["sequence"] == "AT"


def test_v1_dispatch_retains_reconciliation_then_retry(monkeypatch):
    from backend.core import cluster_reconcile, lattice

    source = recipe()
    params = inputs(source)
    calls = []
    reconcile = cluster_reconcile.reconcile_cluster_membership
    retry = lattice.retry_pending_ligations

    def observe_reconcile(*args, **kwargs):
        calls.append("reconcile")
        return reconcile(*args, **kwargs)

    def observe_retry(*args, **kwargs):
        calls.append("retry")
        return retry(*args, **kwargs)

    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", observe_reconcile)
    monkeypatch.setattr(lattice, "retry_pending_ligations", observe_retry)
    result = commands.execute("extension-upsert", source, params)
    assert calls == ["reconcile", "retry"]
    assert result.extensions[0].id == "terminal"


def test_v2_parser_returns_owned_inputs():
    params = inputs(recipe(), version=2)
    parsed = parse_command("extension-upsert", params)
    parsed["entries"][0]["extension"]["sequence"] = "GG"
    assert params["entries"][0]["extension"]["sequence"] == "AT"


def test_v2_delete_recreate_has_conservative_extension_order_without_topology_barrier():
    from backend.core.part_dependencies import Dependencies, DependencyIndex, Resource

    source = recipe()
    first = inputs(source, version=2)
    deletion = {"_proof_version": 1, "extension_ids": ["terminal"]}
    second = deepcopy(first)
    second["entries"][0]["extension"]["id"] = "replacement"
    # Different extension IDs do not make the same terminal slot independent.
    created = commands.execute("extension-upsert", source, first)
    emptied = commands.execute("extension-delete", created, deletion)
    replaced = commands.execute("extension-upsert", emptied, second)
    assert [extension.id for extension in replaced.extensions] == ["replacement"]
    index = DependencyIndex()
    for identity, kind, params in (("create", "extension-upsert", first),
                                   ("delete", "extension-delete", deletion),
                                   ("recreate", "extension-upsert", second)):
        contract = commands.dependencies(kind, params)
        assert contract.known and not contract.barrier
        assert Resource("part", "extensions") in contract.reads & contract.writes
        index.append(identity, contract)
    assert index.parents["delete"] == {"create"}
    assert index.parents["recreate"] == {"delete"}
    assert index.affected(["delete"]) == {"delete", "recreate"}
    # The inventory is deliberately conservative for other extension termini,
    # but cannot turn a disjoint placement operation into a topology dependent.
    third = deepcopy(first)
    third["entries"][0]["extension"].update(id="other-end", end="five_prime")
    index.append("other-end", commands.dependencies("extension-upsert", third))
    assert index.parents["other-end"] == {"recreate"}
    index.append("unrelated-pose", Dependencies(
        writes=frozenset({Resource("cluster", source.cluster_transforms[0].id)})))
    assert index.parents["unrelated-pose"] == set()
