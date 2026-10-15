"""Coating append uses the existing single-candidate job and native replay path."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import part_coating_append as compiler
from backend.api import part_evaluation_capture as policy
from backend.api import part_evaluation_jobs as jobs
from backend.api import part_evaluation_worker as workers
from backend.api import part_streptavidin_commands as coating
from backend.api import state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate
from backend.api.part_proof_commands import dependencies, execute_long
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedResolver
from backend.core.part_verification_capture import capture
from tests.test_part_coating_append import PIN
from tests.test_part_streptavidin_commands import sources as sources


def body(action="create", *, revision=7, identity=None, **choices):
    return {"operation": "append", "kind": "streptavidin-coating", "expected_revision": revision,
        "params": {"action": action, **({"nanoparticle_id": identity} if identity is not None else {}), **choices}}


def operation(design, request):
    return {"request": request, "header": {"identity": str(uuid4()), "timestamp": "2026-10-15T12:00:00Z",
        "source_revision": request["expected_revision"], "source_design_id": design.id}}


def empty():
    return create_empty_part("Coating append", "HONEYCOMB")


@pytest.fixture
def fake_executor(monkeypatch):
    """Fast lifecycle failures only; these tiny assets are not numerical proof."""
    from backend.core import streptavidin

    monkeypatch.setattr(compiler, "contract_defaults", lambda: deepcopy(PIN))
    monkeypatch.setattr(streptavidin, "streptavidin_asset_from_text",
        lambda *_a, **_k: pytest.fail("Fault-path fixture parsed molecular atoms"))
    calls = []

    def execute(kind, design, params):
        calls.append((kind, params))
        if "coating_version" not in params:
            return compiler.gold.build(kind, design, params)
        prepared = coating.validate_inputs(kind, design, params, resolver=EmbeddedResolver(design.input_sources))
        command = prepared.command
        if not isinstance(command, coating.SetRequest):
            return coating.build(kind, design, params)
        if command.engine.model_dump() != PIN["engine"]:
            raise CommandContractError("Injected old-engine failure", code="engine_mismatch")
        current = prepared.particle
        settings = {field: getattr(command, field) for field in (
            "mode", "footprint_nm2", "spacer_nm", "seed", "coverage_reference", "count_override")}
        material = m.StreptavidinCoating(**settings, target_count=command.count_override or 1,
            poses=[m.Mat4x4()], protein=m.ProteinAsset(id=f"streptavidin-1stp-assembly1-{command.mode}",
                metadata={"source_sha256": coating.PDB_SHA256}))
        particle = current.model_copy(update={"coating": material, "diameter_nm": prepared.diameter_nm})
        return design.copy_with(nanoparticles=[particle])

    execute.calls = calls
    return execute


def fake_create(fake_executor):
    source = empty()
    result = evaluate(source, operation(source, body(diameter_nm=20.0, coating={"count_override": 1})),
                      executor=fake_executor)
    assert result["status"] == "ready", result
    return m.Design.model_validate(result["candidate"])


@pytest.fixture
def job_document(monkeypatch, fake_executor):
    identity = f"__coating_append__{uuid4()}"
    token = set_current_doc(identity)
    state.load_design(empty())
    monkeypatch.setattr(policy, "COATING_APPEND_ENABLED", True)  # Qualification fixture, never production policy.

    class Worker:
        def __init__(self, design, request):
            self.design, self.request = design, request
        def start(self):
            pass
        def wait(self, _timeout):
            return True
        def is_alive(self):
            return False
        def result(self):
            return evaluate(self.design, self.request, executor=fake_executor)
        def close(self):
            pass

    monkeypatch.setattr(jobs, "EvaluationWorker", Worker)
    monkeypatch.setattr(jobs, "_submit", jobs._run)
    previous = set(jobs._jobs)
    try:
        yield
    finally:
        with jobs._lock:
            for job_id in set(jobs._jobs) - previous:
                jobs._jobs.pop(job_id)
        with state._lock:
            state._sessions.pop(identity, None)
        reset_current_doc(token)


def test_public_enable_gate_stays_closed_before_copy_or_work(job_document, monkeypatch):
    monkeypatch.setattr(policy, "COATING_APPEND_ENABLED", False)
    monkeypatch.setattr(policy, "capture", lambda *_a, **_k: pytest.fail("Disabled append copied the source"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body(revision=state.revision(), diameter_nm=20.0))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "coating_append_unavailable"


@pytest.mark.parametrize("fault", ["missing_revision", "client_pin", "client_source", "client_id", "mixed_action"])
def test_public_envelope_rejects_unsafe_inputs_before_capture(job_document, monkeypatch, fault):
    request = body(revision=state.revision(), diameter_nm=20.0)
    if fault == "missing_revision":
        request.pop("expected_revision")
    else:
        field, value = {"client_pin": ("engine", PIN["engine"]), "client_source": ("pdb_source", {}),
                        "client_id": ("nanoparticle_id", "client-id"), "mixed_action": ("pose", [0] * 16)}[fault]
        request["params"][field] = value
    monkeypatch.setattr(policy, "capture", lambda *_a, **_k: pytest.fail("Invalid DTO reached capture"))
    with pytest.raises(ValidationError):
        jobs.start(request)


def test_new_append_uses_fixed_profile_on_empty_source_with_no_file_reads(job_document, monkeypatch):
    observed = []

    def capturing(design, **limits):
        observed.append(limits)
        return design.model_copy(deep=True)

    monkeypatch.setattr(policy, "capture", capturing)
    monkeypatch.setattr(compiler, "prepare_sources", lambda *_a: pytest.fail("Capture read installed sources"))
    request = body(revision=state.revision(), diameter_nm=20.0)
    original, copied, revision = state.capture_design_for_evaluation(request)
    assert copied is not original and revision == request["expected_revision"]
    assert observed == [{"preserve_entry_types": True, **policy.COATING_PROFILE}]


def test_combined_create_and_delete_each_publish_once_and_undo_as_one(job_document, fake_executor):
    source, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    job = jobs.start(body(revision=revision, diameter_nm=20.0, coating={"count_override": 1}))["job_id"]
    inspected = jobs.inspect(job)["result"]
    assert inspected["status"] == "ready" and "candidate" not in inspected
    assert set(inspected["append"]) == {"kind", "action", "feature_ids", "nanoparticle_id"}
    assert len(inspected["append"]["feature_ids"]) == 2
    assert state.get_design_with_revision() == (source, revision)
    assert [kind for kind, _ in fake_executor.calls] == ["nanoparticle-create", "nanoparticle-patch"]
    first = jobs.commit(job)
    created = state.get_or_404()
    assert len(created.feature_log) == 2 and len(created.nanoparticles) == 1
    assert state.undo_depth() == depth + 1 and first["revision"] == revision + 1
    assert jobs.commit(job)["revision"] == first["revision"] and state.undo_depth() == depth + 1
    state.undo()
    assert not state.get_or_404().nanoparticles and not state.get_or_404().input_sources
    state.redo()
    identity = state.get_or_404().nanoparticles[0].id
    fake_executor.calls.clear()
    job = jobs.start(body("delete", revision=state.revision(), identity=identity))["job_id"]
    assert jobs.inspect(job)["result"]["status"] == "ready"
    assert [kind for kind, _ in fake_executor.calls] == [
        "nanoparticle-create", "nanoparticle-patch", "nanoparticle-patch", "nanoparticle-delete"]
    before_delete = state.undo_depth()
    jobs.commit(job)
    assert not state.get_or_404().nanoparticles and len(state.get_or_404().feature_log) == 4
    assert state.undo_depth() == before_delete + 1
    state.undo()
    assert state.get_or_404().nanoparticles == created.nanoparticles


def test_delete_then_recreate_retains_sources_and_old_recipe_with_new_particle_identity(job_document):
    def commit(request):
        source, revision = state.get_design_with_revision()
        depth = state.undo_depth()
        job = jobs.start({**request, "expected_revision": revision})["job_id"]
        assert jobs.inspect(job)["result"]["status"] == "ready"
        assert state.get_design_with_revision() == (source, revision)
        jobs.commit(job)
        assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
        return state.get_or_404()

    created = commit(body(diameter_nm=20.0, coating={"count_override": 1, "coverage_reference": "gold_2007"}))
    original_identity = created.nanoparticles[0].id
    original_sources = dict(created.input_sources)
    deleted = commit(body("delete", identity=original_identity))
    assert not deleted.nanoparticles and deleted.input_sources == original_sources
    definition_fields = {"id", "op_kind", "params", "label", "timestamp"}
    old_rows = [row.model_dump(include=definition_fields) for row in deleted.feature_log]
    recreated = commit(body(diameter_nm=12.0, coating={
        "count_override": 2, "coverage_reference": "gold_2007", "seed": 9}))
    assert recreated.nanoparticles[0].id != original_identity
    assert recreated.nanoparticles[0].diameter_nm == 12.0
    assert recreated.nanoparticles[0].coating.seed == 9
    assert recreated.nanoparticles[0].coating.target_count == 2
    assert recreated.input_sources == original_sources and len(recreated.input_sources) == 2
    assert len(recreated.feature_log) == 6
    assert [row.model_dump(include=definition_fields) for row in recreated.feature_log[:4]] == old_rows
    state.undo()
    assert not state.get_or_404().nanoparticles
    assert state.get_or_404().input_sources == original_sources
    state.redo()
    assert state.get_or_404().nanoparticles == recreated.nanoparticles


def test_uncoated_delete_uses_the_single_remaining_thirty_second_row(job_document):
    from backend.api.part_recipe_edit import regenerate

    # Actual native rows and recovery, not a padded list of invalid receipts.
    source = empty()
    base = {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "bare-gold"}
    rows = [m.SnapshotLogEntry(id=str(uuid4()), op_kind="nanoparticle-create", label="Create bare gold",
        params={**base, "diameter_nm": 10.0})]
    rows.extend(m.SnapshotLogEntry(id=str(uuid4()), op_kind="nanoparticle-patch", label="Resize bare gold",
        params={**base, "diameter_nm": 10.0 + index / 10.0}) for index in range(1, 31))
    source = regenerate(source, rows, lambda: None)
    assert len(source.feature_log) == 31 and source.nanoparticles[0].coating is None
    state.load_design(source)
    revision, depth = state.revision(), state.undo_depth()
    job = jobs.start(body("delete", revision=revision, identity="bare-gold"))["job_id"]
    result = jobs.inspect(job)["result"]
    assert result["status"] == "ready", result
    assert len(result["append"]["feature_ids"]) == 1
    jobs.commit(job)
    candidate = state.get_or_404()
    assert len(candidate.feature_log) == 32 and not candidate.nanoparticles
    assert candidate.feature_log[-1].op_kind == "nanoparticle-delete"
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    proof = assess_part_history(candidate, execute=execute_long, dependencies=dependencies)
    assert proof["status"] == "verified", proof


@pytest.mark.parametrize("fault", ["cancel", "stale"])
def test_ready_candidate_cancel_or_stale_cannot_publish(job_document, fault):
    job = jobs.start(body(revision=state.revision(), diameter_nm=20.0, coating={"count_override": 1}))["job_id"]
    if fault == "cancel":
        jobs.inspect(job, cancel=True)
    else:
        state.mutate_and_validate(lambda design: setattr(design.metadata, "name", "Intervening edit"))
    source, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException) as error:
        jobs.commit(job)
    assert error.value.status_code == 409
    assert state.get_design_with_revision() == (source, revision) and state.undo_depth() == depth


def test_stale_submission_fails_before_capture(job_document, monkeypatch):
    monkeypatch.setattr(policy, "capture", lambda *_a, **_k: pytest.fail("Stale append copied"))
    with pytest.raises(HTTPException) as error:
        jobs.start(body(revision=state.revision() - 1, diameter_nm=20.0))
    assert error.value.status_code == 409 and error.value.detail["code"] == "source_changed"


@pytest.mark.parametrize("fault", ["second_step", "recovery_budget"])
def test_combined_failure_returns_no_partial_candidate_or_mutation(fake_executor, monkeypatch, fault):
    source = empty()
    before = source.model_dump_json()
    if fault == "recovery_budget":
        from backend.api import part_recovery_budget
        monkeypatch.setattr(part_recovery_budget, "MAX_RECOVERY_BYTES", 0)

    def failing(kind, design, params):
        if fault == "second_step" and "coating_version" in params:
            raise ValueError("Injected second-step failure")
        return fake_executor(kind, design, params)

    result = evaluate(source, operation(source, body(diameter_nm=20.0, coating={"count_override": 1})),
                      executor=failing)
    assert result["status"] in {"failed", "unverified"} and "candidate" not in result
    assert source.model_dump_json() == before
    assert fake_executor.calls[0][0] == "nanoparticle-create"


@pytest.mark.parametrize("fault", ["missing_source", "old_engine", "materialized_mismatch"])
def test_old_recipe_must_pass_before_new_source_preparation(fake_executor, monkeypatch, fault):
    source = fake_create(fake_executor)
    if fault == "missing_source":
        source.input_sources.clear()
    elif fault == "old_engine":
        source.feature_log[1].params["engine"]["runtime_sha256"] = "f" * 64
    else:
        source.nanoparticles[0].diameter_nm = 30.0
    for row in source.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned snapshots cannot restore sources"
    before = source.model_dump_json()
    monkeypatch.setattr(compiler, "prepare_sources", lambda *_a: pytest.fail("Old failed proof reached new sources"))
    result = evaluate(source, operation(source, body("set", identity=source.nanoparticles[0].id,
        coating={"count_override": 1})), executor=fake_executor)
    assert result["status"] in {"unverified", "mismatch"} and "candidate" not in result
    assert source.model_dump_json() == before
    if fault != "materialized_mismatch":
        assert result["issues"][0]["code"] == ("source_unavailable" if fault == "missing_source" else "engine_mismatch")


@pytest.mark.parametrize("action", ["create", "delete"])
def test_two_rows_reserved_before_prefix_execution_or_asset_preparation(fake_executor, monkeypatch, action):
    source = empty() if action == "create" else fake_create(fake_executor)
    row = m.SnapshotLogEntry(op_kind="nanoparticle-create", params={}, label="Entry limit")
    source.feature_log = [row.model_copy(update={"id": str(index)}) for index in range(31)]
    fake_executor.calls.clear()
    monkeypatch.setattr(compiler, "prepare_sources", lambda *_a: pytest.fail("Over-limit append read sources"))
    request = body(diameter_nm=20.0) if action == "create" else body("delete", identity=source.nanoparticles[0].id)
    result = evaluate(source, operation(source, request), executor=fake_executor)
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "command_limit"
    assert not fake_executor.calls


@pytest.mark.parametrize("fault", ["missing", "wrong_design", "stale_revision"])
def test_worker_requires_host_capture_context_independently(fake_executor, fault):
    source = empty()
    op = operation(source, body(diameter_nm=20.0))
    if fault == "missing":
        op["header"].pop("source_revision")
    elif fault == "wrong_design":
        op["header"]["source_design_id"] = "other"
    else:
        op["header"]["source_revision"] += 1
    result = evaluate(source, op, executor=fake_executor)
    assert result["status"] == "unverified" and not fake_executor.calls
    assert result["issues"][0]["code"] == ("source_changed" if fault == "stale_revision" else "invalid_capture_context")


def test_real_native_lifecycle_defaults_sources_and_input_replay(sources):
    design = empty()
    original = design
    before = design.model_dump_json()

    def append(request):
        nonlocal design
        result = evaluate(design, operation(design, request))
        assert result["status"] == "ready", result
        candidate = m.Design.model_validate(result["candidate"])
        assert result["append"]["feature_ids"] == [row.id for row in candidate.feature_log[len(design.feature_log):]]
        design = candidate

    append(body(diameter_nm=20.0, coating={"count_override": 1}))
    identity = design.nanoparticles[0].id
    assert design.feature_log[1].params["spacer_nm"] == 0.3
    append(body("set", identity=identity, coating={
        "mode": "biotin_tether", "count_override": 1, "coverage_reference": "gold_2007", "seed": 3}))
    recorded = deepcopy(design.feature_log[-1].params)
    append(body("repack", identity=identity, diameter_nm=22.0))
    assert design.nanoparticles[0].diameter_nm == 22.0
    assert design.feature_log[-1].params == {**recorded, "diameter_nm": 22.0}
    original_coating = design.nanoparticles[0].coating
    pose = [1, 0, 0, 3, 0, 1, 0, -2, 0, 0, 1, 4, 0, 0, 0, 1]
    append(body("move", identity=identity, pose=pose))
    assert design.nanoparticles[0].coating == original_coating
    assert design.nanoparticles[0].pose.values == pose
    coated_prefix = design
    append(body("remove", identity=identity))
    assert design.nanoparticles[0].coating is None
    append(body("delete", identity=identity))
    assert not design.nanoparticles
    report = assess_part_history(design, execute=execute_long, dependencies=dependencies)
    assert report["status"] == "reproduced_import", report
    assert len(report["imported_sources"]) == len(design.input_sources) == 2
    # A separate branch proves coated delete composes remove + delete.
    result = evaluate(coated_prefix, operation(coated_prefix, body("delete", identity=identity)))
    assert result["status"] == "ready" and len(result["append"]["feature_ids"]) == 2
    assert not m.Design.model_validate(result["candidate"]).nanoparticles
    assert original.model_dump_json() == before


def test_publication_driven_resize_recomputes_count_from_retained_pin_without_override(sources, monkeypatch):
    design = empty()
    created = evaluate(design, operation(design, body(diameter_nm=5.0, coating={
        "coverage_reference": "gurtovenko_2019", "footprint_nm2": 100.0})))
    assert created["status"] == "ready", created
    design = m.Design.model_validate(created["candidate"])
    original_sources = dict(design.input_sources)
    recorded = deepcopy(design.feature_log[-1].params)
    assert recorded["count_override"] is None
    assert design.nanoparticles[0].coating.target_count == 1
    # The retained publication's 50 nm² area determines 6 sites at 10 nm;
    # using the authored 100 nm² fallback footprint would incorrectly give 3.
    monkeypatch.setattr(compiler, "_DATA", Path("/__nadoc_test_no_repack_assets__"))
    result = evaluate(design, operation(design, body("repack", identity=design.nanoparticles[0].id,
        diameter_nm=10.0)))
    assert result["status"] == "ready", result
    candidate = m.Design.model_validate(result["candidate"])
    assert candidate.nanoparticles[0].diameter_nm == 10.0
    assert candidate.nanoparticles[0].coating.target_count == 6
    assert candidate.nanoparticles[0].coating.count_override is None
    assert 1 <= len(candidate.nanoparticles[0].coating.poses) <= 6
    assert candidate.feature_log[-1].params == {**recorded, "diameter_nm": 10.0}
    assert candidate.input_sources == original_sources and len(original_sources) == 2
    proof = assess_part_history(candidate, execute=execute_long, dependencies=dependencies)
    assert proof["status"] == "reproduced_import", proof


def _evaluate_without_bundles(input_name, input_size, output_name):
    """Spawn target: installed assets are unavailable; replay must use pins."""
    from backend.api import part_coating_append
    from backend.api.part_evaluation_worker import _evaluate
    from backend.core import streptavidin
    absent = Path("/__nadoc_test_no_coating_bundle__")
    part_coating_append._DATA = absent
    streptavidin.PDB_PATH = absent / "1STP-assembly1.pdb"
    _evaluate(input_name, input_size, output_name)


def cold(design, request):
    # Keep nodes/bytes identical; this test-only clock avoids conflating replay
    # correctness with the separate production 100 ms capture qualification.
    isolated = capture(design, max_nodes=100_000, max_bytes=4_000_000, seconds=1.0,
                       preserve_entry_types=True)
    worker = workers.EvaluationWorker(isolated, operation(design, request))
    try:
        worker.start()
        assert worker.wait(30)
        return worker.result()
    finally:
        worker.close()


def test_real_spawned_creation_then_cold_repack_uses_only_pinned_sources(monkeypatch):
    design = empty()
    result = cold(design, body(diameter_nm=20.0, coating={
        "count_override": 1, "coverage_reference": "gold_2017"}))
    assert result["status"] == "ready", result
    design = m.Design.model_validate_json(m.Design.model_validate(result["candidate"]).model_dump_json())
    for row in design.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned saved output"
    original_sources = dict(design.input_sources)
    monkeypatch.setattr(workers, "_evaluate", _evaluate_without_bundles)
    result = cold(design, body("repack", identity=design.nanoparticles[0].id, diameter_nm=22.0))
    assert result["status"] == "ready", result
    candidate = m.Design.model_validate(result["candidate"])
    assert candidate.nanoparticles[0].diameter_nm == 22.0
    assert candidate.input_sources == original_sources and len(candidate.feature_log) == 3
    # The compiled recipe and its dual-source closure survive another cold read.
    result = cold(candidate, {"operation": "verify", "expected_revision": 7})
    assert result["status"] == "reproduced_import" and len(result["imported_sources"]) == 2
