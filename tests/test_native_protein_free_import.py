"""Explicitly enabled experimental free import records source and placement."""

import asyncio
from copy import deepcopy
from threading import Event
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import part_protein_import_recording as recording
from backend.api import routes_design_interchange as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_verification_worker import VerificationWorker
from backend.core import protein
from backend.core.models import Annotation, CameraPose, Design, DesignLoadout, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, EmbeddedResolver, InputSource, describe, embed
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_verification_capture import CaptureLimit, capture
from tests.test_protein import _SYNTH_PDB, _SYNTH_PROT_DNA


PATH = "/api/design/import/pdb-auto"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "NATIVE_FREE_IMPORT_ENABLED", True)
    identity = f"native-free-protein-{uuid4()}"
    token = set_current_doc(identity)
    library = dict(state._protein_library)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    state.load_design(create_empty_part("Protein test", "HONEYCOMB"))
    try:
        with TestClient(app) as api:
            yield api
    finally:
        with state._lock:
            state._sessions.pop(identity, None)
            state._protein_library.clear()
            state._protein_library.update(library)
        reset_current_doc(token)


def post(client, **changes):
    return client.post(PATH, json={"content": _SYNTH_PDB, "name": "synthetic.pdb",
        "expected_revision": state.revision(), "operation_id": str(uuid4()), **changes})


def signature():
    return (deepcopy(state.get_design()), state.revision(), list(state._session().history),
            list(state._session().redo), dict(state._protein_library))


def unchanged(before):
    design, revision, history, redo, library = before
    assert state.get_design() == design
    assert state.revision() == revision
    assert list(state._session().history) == history and list(state._session().redo) == redo
    assert state._protein_library == library


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_closed_host_gate_preserves_legacy_path_and_request_cannot_enable_it(client, monkeypatch):
    monkeypatch.setattr(routes, "NATIVE_FREE_IMPORT_ENABLED", False)
    monkeypatch.setattr(recording, "capture_import", lambda *_a, **_k: pytest.fail("Closed native gate reached capture"))
    response = post(client, native_free_import_enabled=True)
    assert response.status_code == 200, response.text
    design = state.get_or_404()
    assert [row.op_kind for row in design.feature_log] == ["protein-import"]
    assert not design.input_sources
    assert response.json()["recipe_recording"] == {
        "status": "legacy_unverified", "reason": "experimental_native_import_disabled"}


def test_exact_original_source_one_parse_two_editable_rows_one_revision_undo_and_browser_payload(client, monkeypatch):
    native_parse, calls = protein.parse_protein_pdb, []
    oracle = native_parse(_SYNTH_PDB, name="synthetic.pdb", source_filename="synthetic.pdb")

    def counted(text, **choices):
        calls.append((text, choices))
        return native_parse(text, **choices)

    monkeypatch.setattr(protein, "parse_protein_pdb", counted)
    before, revision, depth = deepcopy(state.get_or_404()), state.revision(), state.undo_depth()
    response = post(client)
    assert response.status_code == 200, response.text
    assert len(calls) == 1 and calls[0][0] == _SYNTH_PDB
    design = state.get_or_404()
    assert design.id == before.id and design.recipe_root == before.recipe_root
    assert [row.op_kind for row in design.feature_log] == ["protein-import", "protein-attach"]
    source = InputSource.model_validate(design.feature_log[0].params["source"])
    assert EmbeddedResolver(design.input_sources)(source) == _SYNTH_PDB.encode()
    asset, attachment = design.protein_assets[0], design.protein_attachments[0]
    assert asset.model_dump(exclude={"id"}) == oracle.model_dump(exclude={"id"})
    assert attachment.asset_id == asset.id and attachment.target.kind == "free"
    assert attachment.conjugation_atom_serial == oracle.default_conjugation_atom_serial
    assert design.feature_log[1].params["conjugation_atom_serial"] == attachment.conjugation_atom_serial
    assert "atoms" not in design.feature_log[0].params and "operation_id" not in design.feature_log[0].params
    payload = response.json()
    assert payload["recipe_recording"] == {"status": "native_suffix", "whole_design_verified": False,
        "feature_ids": [row.id for row in design.feature_log]}
    for row in payload["design"]["feature_log"]:
        assert row["design_snapshot_gz_b64"] and row["post_state_gz_b64"]
    assert state.revision() == payload["revision"] == revision + 1
    assert state.undo_depth() == depth + 1
    assert state._protein_library[asset.id] == asset
    state.undo()
    assert state.get_or_404() == before
    state.redo()
    assert state.get_or_404() == design


def test_private_candidate_is_admitted_without_another_isolated_copy(client, monkeypatch):
    source = state.get_or_404()
    source.annotations = [Annotation(text="Retain metadata within the shared source budget")]
    native_capture, native_admit = recording.capture, recording.admit
    captures, admissions = [], []

    def capture_source(design, **limits):
        captures.append((design, limits))
        return native_capture(design, **limits)

    def admit_candidate(design, **limits):
        assert design is not source and state.get_or_404() is source
        assert len(design.protein_assets) == 1 and not source.protein_assets
        admissions.append((design, limits))
        return native_admit(design, **limits)

    monkeypatch.setattr(recording, "capture", capture_source)
    monkeypatch.setattr(recording, "admit", admit_candidate)
    response = post(client)
    assert response.status_code == 200, response.text
    assert len(captures) == len(admissions) == 1
    assert captures[0][0] is source and 0 < captures[0][1]["seconds"] <= .025
    assert "seconds" not in admissions[0][1]
    for key in ("max_nodes", "max_bytes", "preserve_entry_types"):
        assert captures[0][1][key] == admissions[0][1][key]
    assert admissions[0][1]["max_nodes"] < 30_000
    assert admissions[0][1]["max_bytes"] < 2_000_000
    assert state.get_or_404().annotations == source.annotations


def test_cold_replay_ignores_recovery_and_library_and_both_features_remain_editable(client):
    response = post(client)
    assert response.status_code == 200, response.text
    design = Design.from_json(state.get_or_404().to_json())
    for row in design.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    state._protein_library.clear()
    worker = VerificationWorker(capture(design))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 2
    finally:
        worker.close()
    renamed = prepare_change(design, capture(design), 0, lambda: None, params={"name": "Edited source label"})
    updated = renamed[0]
    assert updated.protein_assets[0].name == "Edited source label"
    assert updated.protein_attachments[0].id == design.protein_attachments[0].id
    pose = [1., 0., 0., 2., 0., 1., 0., 3., 0., 0., 1., 4., 0., 0., 0., 1.]
    moved = prepare_change(updated, capture(updated), 1, lambda: None, params={"pose": pose})[0]
    assert moved.protein_attachments[0].pose.values == pose
    assert proof(moved)["status"] == "reproduced_import"
    preview = prepare_change(moved, capture(moved), 0, lambda: None)
    assert preview["needs_cascade_decision"]
    assert preview["dependents"][0]["feature_ids"] == [moved.feature_log[1].id]
    deleted = prepare_change(moved, capture(moved), 0, lambda: None, cascade=True)[0]
    assert not deleted.protein_assets and not deleted.protein_attachments and not deleted.feature_log


@pytest.mark.parametrize("absent", [False, True])
def test_only_actually_absent_document_gets_new_empty_root(client, absent):
    state.load_design(None if absent else Design())
    revision = state.revision()
    response = post(client)
    assert response.status_code == 200, response.text
    design = state.get_or_404()
    assert (design.recipe_root is not None) is absent
    result = proof(design)
    assert result["status"] == ("reproduced_import" if absent else "unverified"), result
    assert state.revision() == revision + 1 and state.undo_depth() == 1
    state.undo()
    assert not state.get_or_404().protein_assets
    assert (state.get_or_404().recipe_root is not None) is absent


@pytest.mark.parametrize("remove_dna", [False, True])
def test_mixed_source_retains_original_bytes_and_explicit_filtering_choice(client, remove_dna):
    response = post(client, content=_SYNTH_PROT_DNA, remove_dna_from_protein=remove_dna)
    assert response.status_code == 200, response.text
    design = state.get_or_404()
    row = design.feature_log[0]
    assert row.params["exclude_dna"] is remove_dna
    assert EmbeddedResolver(design.input_sources)(InputSource.model_validate(row.params["source"])) == _SYNTH_PROT_DNA.encode()
    assert len(design.protein_assets[0].atoms) == (9 if remove_dna else 12)


def test_broken_prefix_and_draft_remain_diagnosable_without_whole_prefix_proof(client):
    design = state.get_or_404()
    design.feature_log = [SnapshotLogEntry(op_kind="protein-attach", label="Already missing", params={
        "_proof_version": 1, "protein_version": 1, "attachment_id": "absent-placement", "asset_id": "absent",
        "target": {"kind": "free"}, "conjugation_atom_serial": 1, "handle_complement_bp": 0, "handle_spacer_nt": 0},
        design_snapshot_gz_b64="original prefix pre", post_state_gz_b64="original prefix post")]
    design.annotations = [Annotation(text="Keep this annotation")]
    design.camera_poses = [CameraPose()]
    draft_raw = b"unpublished proposed replacement"
    descriptor = describe(draft_raw, format="blob", media_type="application/octet-stream")
    design.input_sources[descriptor.sha256] = embed(descriptor, draft_raw)
    design.repair_draft = RepairDraft.model_validate({"version": 1, "draft_id": "pending", "generation": 0,
        "base_design_id": design.id, "base": {"version": 1, "root_sha256": "a" * 64,
        "commands_sha256": "b" * 64, "sources_sha256": "c" * 64}, "repair_version": 1,
        "actions": [{"action": "set_input", "feature_id": design.feature_log[0].id,
                     "parameter_path": ["asset_id"], "expected_old": "absent", "value": "future-source"}]})
    before = deepcopy(design)
    response = post(client)
    assert response.status_code == 200, response.text
    after = state.get_or_404()
    assert after.feature_log[0] == before.feature_log[0]
    assert after.annotations == before.annotations and after.camera_poses == before.camera_poses
    assert after.repair_draft == before.repair_draft
    assert after.input_sources[descriptor.sha256] == before.input_sources[descriptor.sha256]
    assert proof(after)["status"] != "reproduced_import"
    rows = response.json()["design"]["feature_log"]
    assert not rows[0]["post_state_gz_b64"]
    assert all(row["post_state_gz_b64"] for row in rows[1:])


@pytest.mark.parametrize("corrupt", [False, True])
def test_same_source_upload_cannot_heal_existing_missing_or_corrupt_declaration(client, monkeypatch, corrupt):
    assert post(client).status_code == 200
    design = state.get_or_404()
    digest = design.feature_log[0].params["source"]["sha256"]
    design.input_sources = {digest: EmbeddedInput(data_b64="AAAA")} if corrupt else {}
    before = signature()
    monkeypatch.setattr(protein, "parse_protein_pdb", lambda *_a, **_k: pytest.fail("Bad old input reached parser"))
    response = post(client)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == ("source_integrity_mismatch" if corrupt else "source_unavailable")
    unchanged(before)


def test_repeated_source_reuses_bytes_but_new_operations_have_independent_outputs(client):
    first = post(client)
    second = post(client)
    assert first.status_code == second.status_code == 200
    design = state.get_or_404()
    assert len(design.input_sources) == 1 and len(design.feature_log) == 4
    assert len({asset.id for asset in design.protein_assets}) == len({item.id for item in design.protein_attachments}) == 2
    assert second.json()["protein"]["duplicate_detected"] and not second.json()["protein"]["deduplicated"]
    assert proof(design)["status"] == "reproduced_import"


@pytest.mark.parametrize("stale", [False, True])
def test_idempotent_and_stale_requests_fail_before_parse(client, monkeypatch, stale):
    assert post(client, operation_id="same action").status_code == 200
    before = signature()
    monkeypatch.setattr(protein, "parse_protein_pdb", lambda *_a, **_k: pytest.fail("Rejected input reached parser"))
    response = post(client, operation_id="same action", expected_revision=state.revision() - int(stale))
    assert response.status_code == 409
    unchanged(before)


@pytest.mark.parametrize("failure", ["source_size", "atom_count", "heavy_physical", "capture", "metadata", "row_reserve"])
def test_recipe_backed_preflight_limits_fail_before_parse_or_legacy_fallback(client, monkeypatch, failure):
    changes = {}
    if failure == "source_size":
        changes["content"] = _SYNTH_PDB + "REMARK " + "x" * 250_000
    elif failure == "atom_count":
        changes["content"] = _SYNTH_PDB + "ATOM      1 ignored\n" * 1001
    elif failure == "heavy_physical":
        state.get_or_404().loadouts = [DesignLoadout(name="Stored simulation", design_snapshot_gz_b64="retained")]
    elif failure == "metadata":
        state.get_or_404().annotations = [Annotation(text="x" * 2_000) for _ in range(40)]
    elif failure == "row_reserve":
        state.get_or_404().feature_log = [SnapshotLogEntry(op_kind="protein-import", label="row") for _ in range(1999)]
    else:
        def limited(*_a, **_k):
            raise CaptureLimit("injected bounded capture")
        monkeypatch.setattr(recording, "capture", limited)
    before = signature()
    monkeypatch.setattr(protein, "parse_protein_pdb", lambda *_a, **_k: pytest.fail("Preflight reached parser"))
    monkeypatch.setattr(routes, "_import_protein_free", lambda *_a, **_k: pytest.fail("Native admission fell back"))
    response = post(client, **changes)
    assert response.status_code == 413, response.text
    unchanged(before)


def test_rootless_unsupported_state_retains_explicit_legacy_compatibility_before_native_work(client, monkeypatch):
    state.load_design(Design(loadouts=[DesignLoadout(name="Retained", design_snapshot_gz_b64="opaque")]))
    monkeypatch.setattr(recording, "prepare_import", lambda *_a: pytest.fail("Legacy selection ran native builder"))
    response = post(client)
    assert response.status_code == 200, response.text
    assert response.json()["recipe_recording"]["status"] == "legacy_unverified"
    assert "loadouts" in response.json()["recipe_recording"]["reason"]
    assert state.get_or_404().recipe_root is None


@pytest.mark.parametrize("stage", ["recovery", "candidate_admission", "response", "library", "undo"])
def test_preparation_and_publication_failures_preserve_document_stacks_and_library(client, monkeypatch, stage):
    before = signature()
    def fail(*_a, **_k):
        raise RuntimeError("injected import failure")
    if stage == "recovery":
        monkeypatch.setattr(state, "encode_design_snapshot", fail)
    elif stage == "candidate_admission":
        def fail_candidate(*_args, **_kwargs):
            raise CaptureLimit("injected candidate refusal")
        monkeypatch.setattr(recording, "admit", fail_candidate)
    elif stage == "response":
        from backend.api import crud
        monkeypatch.setattr(crud, "_design_response", fail)
    elif stage == "library":
        original = recording._store_library_asset_locked
        def partially_add(asset):
            original(asset)
            fail()
        monkeypatch.setattr(recording, "_store_library_asset_locked", partially_add)
    else:
        monkeypatch.setattr(state, "_snapshot_copy", fail)
    if stage in {"library", "undo"}:
        with pytest.raises(RuntimeError, match="injected"):
            post(client)
    else:
        response = post(client)
        assert response.status_code == (413 if stage == "candidate_admission" else 400), response.text
    unchanged(before)


def test_absent_document_failed_library_publication_restores_absence(client, monkeypatch):
    state.load_design(None)
    before = signature()
    def fail(_asset):
        raise RuntimeError("injected library failure")
    monkeypatch.setattr(recording, "_store_library_asset_locked", fail)
    with pytest.raises(RuntimeError, match="injected"):
        post(client)
    unchanged(before)


def test_concurrent_edit_during_private_parse_is_retained_with_no_library_leak(client, monkeypatch):
    original = recording.prepare_import
    changed = []
    def prepare_then_edit(captured):
        result = original(captured)
        current = state.get_or_404()
        state.set_design(current.copy_with(metadata=current.metadata.model_copy(update={"name": "Concurrent edit"})))
        changed.append(signature())
        return result
    monkeypatch.setattr(recording, "prepare_import", prepare_then_edit)
    response = post(client)
    assert response.status_code == 409, response.text
    unchanged(changed[0])


def test_disconnect_after_private_preparation_never_publishes(client, monkeypatch):
    before, checks = signature(), []
    async def disconnect_after_prepare(*_a):
        checks.append(True)
        if len(checks) == 2:
            raise HTTPException(499, detail="Disconnected after preparation")
    monkeypatch.setattr(routes, "_reject_disconnected_import", disconnect_after_prepare)
    response = post(client)
    assert response.status_code == 499 and len(checks) == 2
    unchanged(before)


def test_cancelled_async_task_may_finish_private_parse_but_cannot_publish(client, monkeypatch):
    before = signature()
    entered, released, finished = Event(), Event(), Event()
    original = recording.prepare_import
    def private_work(captured):
        entered.set()
        assert released.wait(5)
        try:
            return original(captured)
        finally:
            finished.set()
    monkeypatch.setattr(recording, "prepare_import", private_work)
    async def connected(*_a):
        return None
    monkeypatch.setattr(routes, "_reject_disconnected_import", connected)
    async def exercise():
        task = asyncio.create_task(routes.import_pdb_auto(routes.PdbAutoImportRequest(content=_SYNTH_PDB,
            expected_revision=state.revision(), operation_id="cancel-private-work"), object()))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 5)
    asyncio.run(exercise())
    unchanged(before)


def test_rootless_private_response_never_normalizes_or_publishes(client, monkeypatch):
    from backend.api import crud
    from backend.core.models import ClusterRigidTransform
    from tests.conftest import make_minimal_design

    source = make_minimal_design()
    source.cluster_transforms = [ClusterRigidTransform(id="empty-legacy-auto", auto_created=True)]
    state.load_design(source)
    before = signature()
    monkeypatch.setattr(crud, "_ensure_default_cluster", lambda *_a, **_k: pytest.fail("Native response normalized legacy state"))
    captured, reason = recording.capture_import(_SYNTH_PDB, "native", False, "private", state.revision())
    assert reason is None
    prepared = recording.prepare_import(captured)
    unchanged(before)
    assert prepared.candidate.recipe_root is None
    assert prepared.candidate.cluster_transforms == source.cluster_transforms
    assert prepared.response["design"]["cluster_transforms"] == [item.model_dump() for item in source.cluster_transforms]


def test_metadata_and_authoring_share_one_capture_deadline_and_allowance(client, monkeypatch):
    original, observed = recording._retained_metadata, []
    now = [100.0]
    monkeypatch.setattr(recording, "monotonic", lambda: now[0])
    def metadata(design, deadline):
        result = original(design, deadline)
        now[0] += 0.010
        observed.append(result[1:])
        return result
    def bounded(_design, **kwargs):
        assert kwargs["seconds"] == pytest.approx(0.015)
        assert kwargs["max_nodes"] == 30_000 - observed[0][0]
        assert kwargs["max_bytes"] == 2_000_000 - observed[0][1]
        raise CaptureLimit("observed one shared allowance")
    monkeypatch.setattr(recording, "_retained_metadata", metadata)
    monkeypatch.setattr(recording, "capture", bounded)
    with pytest.raises(HTTPException) as error:
        recording.capture_import(_SYNTH_PDB, "bounded", False, "shared-budget", state.revision())
    assert error.value.status_code == 413


def test_unrelated_malformed_old_source_is_not_a_whole_prefix_admission_requirement(client):
    source = state.get_or_404()
    source.feature_log = [SnapshotLogEntry(op_kind="protein-import", label="Existing broken source", params={
        "_proof_version": 1, "source": {"sha256": "invalid-old-digest"}})]
    response = post(client)
    assert response.status_code == 200, response.text
    assert state.get_or_404().feature_log[0] == source.feature_log[0]
    assert response.json()["recipe_recording"]["whole_design_verified"] is False


def test_cumulative_recovery_refusal_is_atomic_after_one_parse(client, monkeypatch):
    source = state.get_or_404()
    source.feature_log = [SnapshotLogEntry(op_kind="protein-import", label="Retained legacy recovery",
        design_snapshot_gz_b64="x" * (recording.MAX_RECOVERY_BYTES - 1))]
    before = signature()
    original, calls = protein.parse_protein_pdb, []
    def parse_once(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(protein, "parse_protein_pdb", parse_once)
    response = post(client)
    assert response.status_code == 413, response.text
    assert len(calls) == 1
    unchanged(before)


class RejectReentrantLock:
    """Turn a same-thread second Lock acquisition into a deterministic failure."""

    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.owner = None
        self.acquisitions = 0

    def acquire(self, *args, **kwargs):
        from threading import get_ident
        identity = get_ident()
        if self.owner == identity:
            raise AssertionError("Reentrant state lock acquisition would deadlock")
        acquired = self.wrapped.acquire(*args, **kwargs)
        if acquired:
            self.owner = identity
            self.acquisitions += 1
        return acquired

    def release(self):
        self.owner = None
        self.wrapped.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()


def test_real_route_uses_lock_owned_publication_without_reentrant_state_wrappers(client, monkeypatch):
    from backend.api import part_replacement_transaction
    from threading import get_ident

    guarded = RejectReentrantLock(state._lock)
    monkeypatch.setattr(state, "_lock", guarded)
    original_publish = part_replacement_transaction.publish_replacement
    original_store = recording._store_library_asset_locked
    entered = []
    def publish(session, candidate):
        assert guarded.owner == get_ident()
        entered.append("document")
        return original_publish(session, candidate)
    def store(asset):
        assert guarded.owner == get_ident()
        entered.append("library")
        return original_store(asset)
    monkeypatch.setattr(part_replacement_transaction, "publish_replacement", publish)
    monkeypatch.setattr(recording, "_store_library_asset_locked", store)
    response = post(client)
    assert response.status_code == 200, response.text
    assert entered == ["document", "library"] and guarded.acquisitions > 0
    assert state.undo_depth() == 1


@pytest.mark.parametrize("absent", [False, True])
def test_close_reopen_same_source_and_revision_cannot_admit_old_preparation(client, absent):
    from backend.api.doc_context import get_current_doc

    if absent:
        state.load_design(None)
    captured, reason = recording.capture_import(_SYNTH_PDB, "ABA", False, "old-session", state.revision())
    assert reason is None
    prepared = recording.prepare_import(captured)
    with state._lock:
        reopened = state._DesignSession(design=captured.source, revision=captured.revision)
        state._sessions[get_current_doc()] = reopened
    before = signature()
    assert reopened is not captured.session
    with pytest.raises(HTTPException) as error:
        recording.publish_import(captured, prepared)
    assert error.value.status_code == 409
    unchanged(before)


def test_closed_document_stale_publication_does_not_recreate_a_session(client):
    from backend.api.doc_context import get_current_doc

    captured, reason = recording.capture_import(_SYNTH_PDB, "closed", False, "closed-session", state.revision())
    assert reason is None
    prepared = recording.prepare_import(captured)
    library = dict(state._protein_library)
    identity = get_current_doc()
    with state._lock:
        state._sessions.pop(identity)
    with pytest.raises(HTTPException) as error:
        recording.publish_import(captured, prepared)
    assert error.value.status_code == 409
    assert identity not in state._sessions and state._protein_library == library
