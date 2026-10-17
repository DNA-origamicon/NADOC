"""Pending candidates survive bounded native thiol movement and resizing.

Tests first: no applied connection, constraint solver or replacement graft is
admitted. The original particle helper remains the complete geometry oracle.
"""

from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from backend.api import doc_context, routes_nanoparticles as routes, state
from backend.api import part_thiol_patch_commands as commands
from backend.api.part_proof_commands import PART_TOPOLOGY, dependencies
from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, StrandExtension
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_verification_capture import capture
from tests.test_part_pending_np_connections import (
    CREATE, append, authored, creation, gold, graft,
    native_prefix as native_prefix, owner_inputs, proof, seed,
)
from tests.test_part_thiol_patch_commands import move


SELECTOR = "pending_connection_version_ids"


@pytest.fixture
def source(native_prefix):
    design = native_prefix.model_copy(deep=True)
    design = append(design, CREATE, creation(design), "candidate-create")
    strand = design.nanoparticle_conjugations[0].surface_strands[1].strand_id
    return append(design, CREATE, creation(design, version_id="alternate", name="Alternate",
        strand_id=strand, created_at=13.0), "alternate-create")


def params(design, **changes):
    return {"_proof_version": 1, "nanoparticle_version": 1, "thiol_version": 1,
        "nanoparticle_id": "gold", "conjugation_ids": ["gold-graft"],
        SELECTOR: [item.id for item in design.nanoparticle_connection_versions
                   if item.nanoparticle_id == "gold"], **changes}


@pytest.mark.parametrize("patch", [
    {"diameter_nm": 14.0}, {"gizmo_move": move()},
    {"pose": [1., 0., 0., 7., 0., 1., 0., -3., 0., 0., 1., 2., 0., 0., 0., 1.]},
    {"diameter_nm": 12.0, "gizmo_move": move()},
])
def test_motion_preserves_all_pending_metadata_and_matches_unchanged_native_geometry(source, patch):
    original = source.model_dump_json()
    expected = replace_gold_nanosphere(source, "gold", **patch)
    actual = commands.build("nanoparticle-patch", source, params(source, **patch))
    assert authored(actual) == authored(expected)
    assert actual.nanoparticle_connection_versions == source.nanoparticle_connection_versions
    assert actual.helices != source.helices
    assert actual.strands == source.strands and actual.overhangs == source.overhangs
    assert actual.staple_groups == source.staple_groups and actual.cluster_transforms == source.cluster_transforms
    assert source.model_dump_json() == original
    restored = Design.model_validate_json(actual.model_dump_json())
    assert authored(restored) == authored(actual)


def test_motion_reads_each_exact_pending_version_without_import_or_output_authority(source):
    values = params(source, diameter_nm=12.0)
    contract = dependencies("nanoparticle-patch", values)
    assert contract.known and contract.barrier and not contract.imported_sources
    assert {PART_TOPOLOGY, Resource("nanoparticle", "gold"),
            Resource("nanoparticle_connection_version", "candidate"),
            Resource("nanoparticle_connection_version", "alternate")} <= contract.reads
    assert Resource("nanoparticle_connection_version", "candidate") not in contract.writes


@pytest.mark.parametrize("selected,code,identity", [
    ([], "invalid_selection", None),
    (["candidate"], "invalid_selection", "alternate"),
    (["candidate", "alternate", "missing"], "missing_reference", "missing"),
])
def test_selection_must_cover_exact_current_pending_set_before_geometry(source, monkeypatch, selected, code, identity):
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Invalid pending selector reached geometry"))
    original = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", source, params(source, **{SELECTOR: selected}, diameter_nm=12.0))
    assert error.value.code == code
    assert any(ref["kind"] == "nanoparticle_connection_version" and (identity is None or ref["identity"] == identity)
               and ref["parameter_path"][0] == SELECTOR for ref in error.value.references)
    assert source.model_dump_json() == original


def test_omitted_selector_keeps_existing_no_connection_contract_closed(source, native_prefix):
    old = params(source, diameter_nm=12.0)
    old.pop(SELECTOR)
    assert authored(commands.build("nanoparticle-patch", native_prefix, old)) == authored(
        replace_gold_nanosphere(native_prefix, "gold", diameter_nm=12.0))
    with pytest.raises(ReferenceResolutionError):
        commands.build("nanoparticle-patch", source, old)


@pytest.mark.parametrize("selected", [["candidate", "candidate"], [True], "candidate",
                                      [str(index) for index in range(129)]])
def test_pending_selectors_are_unique_bounded_strict_identities(source, selected):
    with pytest.raises(ValidationError):
        commands.parse_command("nanoparticle-patch", params(source, **{SELECTOR: selected}))


@pytest.mark.parametrize("update", [
    {"applied": True}, {"relaxed": True}, {"duplex_id": "retained"}, {"residual_nm": 0.0},
    {"constraint_root_nm": [0., 0., 0.]}, {"constraint_radius_nm": 1.0},
    {"nanoparticle_attach": None}, {"target_attach": None},
])
def test_applied_retained_or_legacy_endpoint_state_never_enters_native_motion(source, monkeypatch, update):
    source.nanoparticle_connection_versions[0] = source.nanoparticle_connection_versions[0].model_copy(update=update)
    assert not commands.native_route_eligible(source, "gold")
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Coupled candidate reached geometry"))
    with pytest.raises(ReferenceResolutionError):
        commands.build("nanoparticle-patch", source, params(source, gizmo_move=move()))


@pytest.mark.parametrize("field,value", [("strand_id", "missing-strand"), ("overhang_id", "missing-target"),
                                         ("nanoparticle_attach", "root")])
def test_supported_pending_reference_damage_is_typed_and_does_not_fallback(source, monkeypatch, field, value):
    source.nanoparticle_connection_versions[0] = source.nanoparticle_connection_versions[0].model_copy(
        update={field: value})
    assert commands.native_route_eligible(source, "gold")
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Broken pending reference reached geometry"))
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", source, params(source, diameter_nm=12.0))
    assert error.value.code in {"missing_reference", "invalid_selection"}
    assert error.value.references and all(ref["parameter_path"][0] == SELECTOR
                                        for ref in error.value.references)


def test_external_consumer_is_still_protected_when_pending_rows_are_retained(source, monkeypatch):
    owner = source.nanoparticle_conjugations[0].surface_strands[0]
    source.extensions.append(StrandExtension(strand_id=owner.strand_id, end="five_prime", sequence="TT"))
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("External consumer reached geometry"))
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build("nanoparticle-patch", source, params(source, diameter_nm=12.0))
    assert error.value.code == "invalid_selection"


def test_unrelated_particle_pending_metadata_is_not_selected_or_rewritten(source):
    source = append(source, "nanoparticle-create", gold("other"), "other-particle")
    source = append(source, "nanoparticle-conjugate", graft("other", history_seed=seed(760)), "other-graft")
    owner = next(item for item in source.nanoparticle_conjugations if item.nanoparticle_id == "other")
    source = append(source, CREATE, creation(source, version_id="other-candidate", nanoparticle_id="other",
        conjugation_id=owner.id, strand_id=owner.surface_strands[0].strand_id), "other-candidate-create")
    values = params(source, diameter_nm=12.0)
    assert values[SELECTOR] == ["candidate", "alternate"]
    result = commands.build("nanoparticle-patch", source, values)
    assert result.nanoparticle_connection_versions == source.nanoparticle_connection_versions
    assert next(item for item in result.nanoparticle_conjugations if item.id == owner.id) == owner
    wrong = {**values, SELECTOR: [*values[SELECTOR], "other-candidate"]}
    with pytest.raises(ReferenceResolutionError):
        commands.build("nanoparticle-patch", source, wrong)


def test_motion_rows_are_independently_replayable_and_parameter_edits_rebuild_geometry(source):
    moved = append(source, "nanoparticle-patch", params(source, gizmo_move=move()), "move-pending")
    final = append(moved, "nanoparticle-patch", params(moved, diameter_nm=14.0), "resize-pending")
    restored = Design.model_validate_json(final.model_dump_json())
    worker = VerificationWorker(capture(restored))
    try:
        worker.start()
        assert worker.wait(5), "Cold native pending motion exceeded its existing worker allowance"
        result = worker.result()
        assert result["status"] == "verified", result
    finally:
        worker.close()
    # Editing must replay the native root/commands, never a materialized helix
    # or either deliberately poisoned recovery payload.
    candidate, _ = prepare_change(restored, capture(restored, preserve_entry_types=True),
                                  len(final.feature_log) - 1, lambda: None, params={"diameter_nm": 16.0})
    expected = replace_gold_nanosphere(moved, "gold", diameter_nm=16.0)
    assert authored(candidate) == authored(expected)
    assert candidate.nanoparticle_connection_versions == source.nanoparticle_connection_versions
    altered = restored.model_copy(deep=True)
    altered.helices[0].axis_start.x += 1000
    assert authored(regenerate(altered, candidate.feature_log, lambda: None)) == authored(expected)


def test_deleting_pending_producer_exposes_motion_selector_instead_of_dropping_metadata(source):
    moved = append(source, "nanoparticle-patch", params(source, diameter_nm=12.0), "motion")
    log = [row for row in moved.feature_log if row.id != "candidate-create"]
    with pytest.raises(ReferenceResolutionError) as error:
        regenerate(moved, log, lambda: None)
    assert error.value.code == "missing_reference"
    assert any(ref["identity"] == "candidate" and ref["parameter_path"][0] == SELECTOR
               for ref in error.value.references)


@pytest.fixture
def document(source):
    identity = f"__thiol_pending_motion_{uuid4()}"
    token = doc_context.set_current_doc(identity)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(source)
        yield source
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def test_ordinary_pending_drag_resize_records_each_native_row_and_one_undo(document):
    original, revision = state.get_design_with_revision()
    before_json, depth = original.model_dump_json(), state.undo_depth()
    routes.patch_nanoparticle("gold", routes.NanoparticlePatch(gizmo_move=move()))
    moved = state.get_or_404()
    assert moved.feature_log[-1].params["thiol_version"] == 1
    assert moved.feature_log[-1].params[SELECTOR] == ["candidate", "alternate"]
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    assert len(moved.feature_log) == len(original.feature_log) + 1
    assert authored(moved) == authored(replace_gold_nanosphere(original, "gold", gizmo_move=move()))
    assert original.model_dump_json() == before_json
    routes.patch_nanoparticle("gold", routes.NanoparticlePatch(diameter_nm=14.0))
    final = state.get_or_404()
    assert final.feature_log[-1].params[SELECTOR] == ["candidate", "alternate"]
    assert state.revision() == revision + 2 and state.undo_depth() == depth + 2
    state.undo()
    assert authored(state.get_or_404()) == authored(moved)
    state.redo()
    assert authored(state.get_or_404()) == authored(final)
    assert proof(state.get_or_404())["status"] == "verified"


def test_live_record_freezes_current_pending_selector_inside_atomic_callback(source, monkeypatch):
    recorded = {}
    def transaction(kind, label, inputs, mutate):
        # The caller has no authority to pin a stale selector outside this seam.
        current = source.copy_with(nanoparticle_connection_versions=source.nanoparticle_connection_versions[1:])
        candidate = mutate(current)
        recorded.update(deepcopy(inputs))
        return candidate, None, None
    monkeypatch.setattr(state, "mutate_with_feature_log", transaction)
    result, _, _ = commands.record("nanoparticle-patch", "Move gold", {"nanoparticle_id": "gold",
                                    "gizmo_move": move()})
    assert recorded[SELECTOR] == ["alternate"]
    assert [item.id for item in result.nanoparticle_connection_versions] == ["alternate"]


def test_broken_pending_target_fails_atomically_without_legacy_record(document, monkeypatch):
    broken = state.get_or_404().model_copy(deep=True)
    target = owner_inputs(broken)["overhang_id"]
    broken.overhangs = [item for item in broken.overhangs if item.id != target]
    state.load_design(broken)
    original, revision = state.get_design_with_revision()
    before, depth = original.model_dump_json(), state.undo_depth()
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Missing target reached native geometry"))
    monkeypatch.setattr(routes, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Missing target fell through to legacy geometry"))
    with pytest.raises(HTTPException) as error:
        routes.patch_nanoparticle("gold", routes.NanoparticlePatch(diameter_nm=12.0))
    assert error.value.status_code == 404
    assert state.revision() == revision and state.undo_depth() == depth
    assert state.get_or_404().model_dump_json() == before


def test_many_pending_alternatives_use_one_reference_and_backing_inventory(source, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as pending

    original = source.nanoparticle_connection_versions[0]
    source.nanoparticle_connection_versions = [original.model_copy(update={"id": f"alternative-{i}"})
                                               for i in range(128)]
    counts = {"_prepare_source": 0, "_target_backings": 0, "resolve_owned_handles": 0}
    for module, name in ((pending, "_prepare_source"), (pending, "_target_backings"),
                         (commands, "resolve_owned_handles")):
        function = getattr(module, name)
        def counted(*args, _function=function, _name=name, **kwargs):
            counts[_name] += 1
            return _function(*args, **kwargs)
        monkeypatch.setattr(module, name, counted)
    assert authored(commands.build("nanoparticle-patch", source, params(source, diameter_nm=12.0))) == authored(
        replace_gold_nanosphere(source, "gold", diameter_nm=12.0))
    assert counts == {"_prepare_source": 1, "_target_backings": 1, "resolve_owned_handles": 1}
    source.nanoparticle_connection_versions.append(original.model_copy(update={"id": "over-limit"}))
    assert not commands.native_route_eligible(source, "gold")


def test_custom_target_identity_uses_same_unique_native_polarity_rule(source):
    target_id = owner_inputs(source)["overhang_id"]
    for spec in source.overhangs:
        if spec.id == target_id:
            spec.id = "custom-target"
    for strand in source.strands:
        for domain in strand.domains:
            if domain.overhang_id == target_id:
                domain.overhang_id = "custom-target"
    for version in source.nanoparticle_connection_versions:
        version.overhang_id = "custom-target"
    assert authored(commands.build("nanoparticle-patch", source, params(source, gizmo_move=move()))) == authored(
        replace_gold_nanosphere(source, "gold", gizmo_move=move()))


def test_pending_motion_does_not_advertise_unqualified_generated_scope(source, monkeypatch):
    from backend.api.part_proof_commands import execute

    values = {**params(source, diameter_nm=12.0), "_generated_scope": {
        "version": 2, "group_id": seed(761), "input_ids": []}}
    assert not dependencies("nanoparticle-patch", values).known
    monkeypatch.setattr(commands, "replace_gold_nanosphere",
                        lambda *_a, **_kw: pytest.fail("Unqualified scope reached geometry"))
    with pytest.raises(NotImplementedError):
        execute("nanoparticle-patch", source, values)


def test_oversize_pending_source_is_classified_before_reference_inventory(source, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as pending
    from backend.core.part_command_errors import CommandContractError

    values = params(source, diameter_nm=12.0)
    source.nanoparticle_connection_versions *= 6000
    monkeypatch.setattr(pending, "identity_index", lambda *_a: pytest.fail("Oversize inventory was indexed"))
    assert not commands.native_route_eligible(source, "gold")
    with pytest.raises(CommandContractError) as error:
        commands.build("nanoparticle-patch", source, values)
    assert error.value.code == "unsupported_np_connection_source"
