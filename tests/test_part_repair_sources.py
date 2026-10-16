"""Source staging records original evidence without authorizing geometry."""

import hashlib

from pydantic import ValidationError
import pytest

from backend.api.part_proof_commands import dependencies
from backend.api.part_repair_source_policy import admit_descriptor
from backend.core.models import Design, MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import EmbeddedInput, describe, embed
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.part_repair_sources import (
    blob_expectation, capture_source_inputs, parse_source_request, prepare_source, select_source,
)


OLD = b"HEADER original protein source\n"
NEW = b"HEADER deliberately selected replacement\n"


def descriptor(raw):
    return describe(raw, format="pdb", media_type="chemical/x-pdb")


def source(*, existing=None):
    old, new = descriptor(OLD), descriptor(NEW)
    design = create_empty_part("Source proposal", "HONEYCOMB").copy_with(id="source-part")
    row = SnapshotLogEntry(id="import", op_kind="protein-import", label="Import",
        params={"_proof_version": 1, "protein_version": 1, "importer_version": 1,
            "source": old.model_dump(mode="json"), "asset_id": "asset", "name": "Protein",
            "source_filename": "protein.pdb", "exclude_dna": True})
    design.feature_log = [row]
    if existing is not None:
        design.input_sources[old.sha256] = existing
    base = repair_base_fingerprint(design)
    action = {"action": "set_input", "feature_id": "import",
        "parameter_path": ["source"], "expected_old": old.model_dump(mode="json"),
        "value": new.model_dump(mode="json")}
    design.repair_draft = RepairDraft.model_validate({"version": 1, "draft_id": "draft", "generation": 4,
        "base_design_id": design.id, "base": base.model_dump(mode="json"), "repair_version": 1,
        "actions": [action]})
    return design


def selection(design, *, operation="stage_proposed", **changes):
    raw = NEW if operation == "stage_proposed" else OLD
    return {"source_repair_version": 1, "operation": operation,
        "expected_design_id": design.id, "expected_revision": 7,
        "expected_draft_id": design.repair_draft.draft_id,
        "expected_generation": design.repair_draft.generation,
        "feature_id": "import", "child_id": None,
        "parameter": "source", "source": descriptor(raw).model_dump(mode="json"), **changes}


def captured(design):
    return capture_source_inputs(design, source_revision=7)


def admitted(design, body):
    value = parse_source_request(body, mutation="expected_blob" in body)
    value_capture = captured(design)
    select_source(value_capture, value, dependencies=dependencies, admit_descriptor=admit_descriptor)
    return value_capture, value


def mutation(design, *, operation="stage_proposed", **options):
    body = selection(design, operation=operation, **options)
    digest = body["source"]["sha256"]
    body["expected_blob"] = blob_expectation(design.input_sources.get(digest)).model_dump(mode="json")
    return body


def test_stage_requires_saved_named_input_and_leaves_published_base_and_draft_unchanged():
    design = source()
    before, draft = design.model_dump_json(), design.repair_draft
    cap, request = admitted(design, mutation(design))
    prepared = prepare_source(cap, request, NEW)
    staged = design.model_copy(update={"input_sources": prepared.sources})
    assert not prepared.published_source_changed
    assert prepared.sources[descriptor(NEW).sha256] == embed(descriptor(NEW), NEW)
    assert repair_base_fingerprint(staged) == draft.base
    assert design.model_dump_json() == before
    assert staged.repair_draft is draft and staged.repair_draft.generation == 4
    assert not hasattr(prepared, "candidate") and not hasattr(prepared, "verified")


def test_persisted_routing_child_cannot_invent_an_undeclared_source_contract():
    # Source-owning kinds are currently snapshot-only. Real persisted routing
    # children must not gain an import contract merely by carrying source JSON.
    design = source()
    child = MinorMutationLogEntry(id="minor", op_subtype="helix-update", label="Edit helix",
        params={"_proof_version": 1, "helix_id": "helix", "source": descriptor(OLD).model_dump(mode="json")})
    design.feature_log = [RoutingClusterLogEntry(id="group", children=[child])]
    design.repair_draft.actions[0].feature_id = "group"
    design.repair_draft.actions[0].child_id = "minor"
    design.repair_draft = design.repair_draft.model_copy(update={"base": repair_base_fingerprint(design)})
    loaded = Design.model_validate_json(design.model_dump_json())
    assert isinstance(loaded.feature_log[0].children[0], MinorMutationLogEntry)
    with pytest.raises(CommandContractError) as error:
        admitted(loaded, selection(loaded, operation="restore_published", feature_id="group", child_id="minor"))
    issue = error.value.as_issue()
    assert issue["code"] == "source_binding_conflict"
    assert issue["feature_id"] == "group" and issue["child_id"] == "minor"


@pytest.mark.parametrize("existing", [None, EmbeddedInput(data_b64="corrupt"), EmbeddedInput(data_b64="\u2602\u00e9")])
def test_explicit_restore_checks_exact_prior_bytes_and_requires_later_rebase(existing):
    design = source(existing=existing)
    cap, request = admitted(design, mutation(design, operation="restore_published"))
    prepared = prepare_source(cap, request, OLD)
    restored = design.model_copy(update={"input_sources": prepared.sources})
    assert prepared.published_source_changed
    assert repair_base_fingerprint(restored) != design.repair_draft.base
    assert restored.repair_draft is design.repair_draft
    assert design.input_sources.get(descriptor(OLD).sha256) is existing


@pytest.mark.parametrize("changed", ["old", "other_feature", "legacy_binding"])
def test_staging_cannot_implicitly_restore_any_published_digest(changed):
    design = source()
    if changed == "old":
        value = descriptor(OLD)
        design.repair_draft.actions[0].value = value.model_dump(mode="json")
    else:
        value = descriptor(NEW)
        other = design.feature_log[0].model_copy(deep=True, update={"id": "other"})
        other.params["source"] = value.model_dump(mode="json")
        if changed == "legacy_binding":
            other.params["unexpected_legacy_field"] = True
        design.feature_log.append(other)
    body = selection(design, source=value.model_dump(mode="json"))
    with pytest.raises(CommandContractError) as error:
        admitted(design, body)
    assert error.value.code == "restore_published_required"
    assert error.value.as_issue()["feature_id"] == "import"


@pytest.mark.parametrize("change,code", [
    ({"feature_id": "absent"}, "missing_feature"),
    ({"child_id": "import"}, "missing_feature"),
    ({"parameter": "geometry"}, "source_binding_conflict"),
    ({"source": descriptor(b"unselected").model_dump(mode="json")}, "source_binding_conflict"),
    ({"expected_revision": 8}, "draft_conflict"),
    ({"expected_generation": 5}, "draft_conflict"),
])
def test_selection_cannot_retarget_or_guess(change, code):
    design = source()
    with pytest.raises(CommandContractError) as error:
        admitted(design, selection(design, **change))
    assert error.value.code == code
    assert error.value.as_issue()["parameter_path"] == [change.get("parameter", "source")]


def test_proposed_input_must_be_explicit_and_old_expectation_is_not_rebased():
    design = source()
    design.repair_draft.actions[0].expected_old["size_bytes"] += 1
    with pytest.raises(CommandContractError) as error:
        admitted(design, selection(design))
    assert error.value.code == "repair_conflict"
    assert error.value.as_issue()["feature_id"] == "import"
    # A corrupt proposal does not prevent restoring the separately selected
    # published source. It remains corrupt, and must be explicitly corrected.
    admitted(design, selection(design, operation="restore_published"))


def test_old_blob_receipt_detects_changed_corruption_before_replacement():
    design = source(existing=EmbeddedInput(data_b64="broken one"))
    request = mutation(design, operation="restore_published")
    design.input_sources[descriptor(OLD).sha256] = EmbeddedInput(data_b64="broken two")
    cap, parsed = admitted(design, request)
    with pytest.raises(CommandContractError) as error:
        prepare_source(cap, parsed, OLD)
    assert error.value.code == "source_blob_conflict"


@pytest.mark.parametrize("change", ["legacy", "output", "geometry_format"])
def test_staging_does_not_admit_legacy_or_baked_geometry_contract(change):
    design = source()
    if change == "legacy":
        design.feature_log[0].params["_proof_version"] = 0
    elif change == "output":
        design.feature_log[0].params["atoms"] = [[0, 0, 0]]
    else:
        design.repair_draft.actions[0].value["format"] = "nadoc"
    value = selection(design)
    if change == "geometry_format":
        value["source"]["format"] = "nadoc"
    with pytest.raises(CommandContractError) as error:
        admitted(design, value)
    assert error.value.code in {"missing_proof_contract", "unsupported_source"}


def test_hash_and_length_pin_cannot_change_in_restore():
    design = source()
    cap, request = admitted(design, mutation(design, operation="restore_published"))
    with pytest.raises(CommandContractError) as error:
        prepare_source(cap, request, b"x" * len(OLD))
    assert error.value.code == "source_integrity_mismatch"
    assert design.input_sources == {}


def test_identical_source_upload_does_not_create_fake_revision_work():
    design = source(existing=embed(descriptor(OLD), OLD))
    cap, request = admitted(design, mutation(design, operation="restore_published"))
    with pytest.raises(CommandContractError) as error:
        prepare_source(cap, request, OLD)
    assert error.value.code == "source_unchanged"


@pytest.mark.parametrize("field,value", [("source_repair_version", True), ("expected_revision", True),
    ("candidate", {}), ("ready", True), ("raw", "whole-design"), ("source_repair_version", 2)])
def test_metadata_schema_excludes_output_bytes_and_coercions(field, value):
    design = source()
    body = mutation(design)
    body[field] = value
    with pytest.raises((ValueError, ValidationError)):
        parse_source_request(body, mutation=True)


def test_old_blob_receipt_hashes_exact_invalid_unicode_without_decoding():
    text = "!\ud800\u00e9"
    # A deliberately poisoned in-memory record; persisted inputs reject lone
    # surrogates, while diagnostic hashing still needs to tolerate corruption.
    receipt = blob_expectation(EmbeddedInput.model_construct(data_b64=text))
    assert receipt.encoded_size == len(text)
    assert receipt.encoded_sha256 == hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def test_capture_is_independent_of_geometry_and_source_decoding(monkeypatch):
    design = source(existing=EmbeddedInput(data_b64="!" * 600_000))
    class Poison:
        def __iter__(self):
            pytest.fail("Source capture visited geometry")
    design.helices = Poison()
    monkeypatch.setattr("backend.core.part_input_sources.decode", lambda *_: pytest.fail("Decoded under capture"))
    monkeypatch.setattr("backend.core.part_repair_sources.blob_expectation", lambda *_: pytest.fail("Hashed under capture"))
    cap = captured(design)
    assert cap.sources[descriptor(OLD).sha256] is design.input_sources[descriptor(OLD).sha256]
    assert cap.definitions.input_sources == {}
    design.repair_draft.actions[0].value["format"] = "client mutation"
    assert cap.definitions.draft.actions[0].value["format"] == "pdb"


def test_existing_source_entry_count_and_cumulative_byte_bounds_apply(monkeypatch):
    design = source()
    design.input_sources = {f"{i:064x}": EmbeddedInput(data_b64="") for i in range(257)}
    with pytest.raises(CommandContractError) as error:
        captured(design)
    assert error.value.code == "source_limit"
    # Lower the existing resolver default via a test wrapper, without allocating
    # a 67 MB fixture. Both capture and publication must use the same envelope.
    import backend.core.part_repair_sources as repair
    original = repair.EmbeddedResolver
    monkeypatch.setattr(repair, "EmbeddedResolver", lambda table: original(table, max_encoded_bytes=12))
    design.input_sources = {"f" * 64: EmbeddedInput(data_b64="a" * 13)}
    with pytest.raises(CommandContractError):
        captured(design)
    design.input_sources = {}
    cap, request = admitted(design, mutation(design))
    with pytest.raises(CommandContractError):
        prepare_source(cap, request, NEW)


@pytest.mark.parametrize("kind,params,parameter,format,media,limit", [
    ("protein-import", {}, "source", "pdb", "chemical/x-pdb", 250_000),
    ("aptamer-import", {}, "source", "pdb", "chemical/x-pdb", 150_000),
    ("cadnano-import", {}, "source", "cadnano-v2", "application/json", 100_000),
    ("nanoparticle-create", {"quantum_dot_version": 1}, "source", "quantum-dot-catalog", "application/json", 65_536),
    ("nanoparticle-patch", {"coating_version": 1, "action": "set"}, "coverage_source", "json", "application/json", 4_096),
])
def test_global_upload_ceiling_does_not_relax_command_family(kind, params, parameter, format, media, limit):
    good = descriptor(b"x").model_copy(update={"size_bytes": limit, "format": format, "media_type": media})
    admit_descriptor(kind, params, parameter, good)
    for changes, code in [({"size_bytes": limit + 1}, "source_limit"), ({"format": "nadoc"}, "unsupported_source"),
                           ({"media_type": "application/octet-stream"}, "unsupported_source")]:
        with pytest.raises(CommandContractError) as error:
            admit_descriptor(kind, params, parameter, good.model_copy(update=changes))
        assert error.value.code == code


def test_coating_retains_exact_original_complete_assembly_pin():
    from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE
    value = descriptor(b"x").model_copy(update={"sha256": PDB_SHA256, "size_bytes": PDB_SIZE})
    args = ("nanoparticle-patch", {"coating_version": 1, "action": "set"}, "pdb_source")
    admit_descriptor(*args, value)
    with pytest.raises(CommandContractError) as error:
        admit_descriptor(*args, value.model_copy(update={"sha256": "f" * 64}))
    assert error.value.code == "unsupported_source"
