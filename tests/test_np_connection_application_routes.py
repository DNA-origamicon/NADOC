"""Ordinary NP application records editable inputs without changing native geometry.

Use the actual router, serializer and recorder on a six-cell native part. The
gate-false controls establish the legacy behavior independently of the new host
adapter; no lifespan, disk model, numerical solver or geometry stub is used.
"""

from contextlib import contextmanager
from copy import copy, deepcopy
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, routes_nanoparticles as routes, state
from backend.api.part_proof_commands import dependencies
from backend.api.part_verification_worker import VerificationWorker
from backend.core.feature_identity import identity_factory
from backend.core.models import ClusterRigidTransform, Design, DesignLoadout
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import capture
from tests.test_part_np_application_commands import application_params, version
from tests.test_part_pending_np_connections import (
    CREATE, PATCH, DELETE, append, authored, creation, native_prefix as native_prefix, owner_inputs, seed,
)


URL = "/api/design/nanoparticles/gold/connection-versions"


@contextmanager
def opened_document(source):
    # Install cleanup before any fallible initialization: failed setup must not
    # leak a document ContextVar into unrelated HTTP tests.
    doc = f"__np_application_route_{uuid4()}"
    prior_revision = doc_context.current_request_revision()
    prior_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(doc)
    client = None
    try:
        state.load_design(source.model_copy(deep=True))
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        app.add_middleware(doc_context.DocContextMiddleware)
        client = TestClient(app, headers={"X-NADOC-Doc": doc})
        yield client
    finally:
        if client is not None:
            client.close()
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior_revision)
        doc_context.set_request_feature_log_entry_id(prior_entry)


@pytest.fixture
def document(native_prefix):
    with opened_document(native_prefix) as client:
        yield client


def create_body(source, **changes):
    selected = owner_inputs(source)
    return {"strand_id": selected["strand_id"], "overhang_id": selected["overhang_id"],
            "name": "Candidate A", "applied": True, **changes}


def request(client, method, *, identity=None, body=None):
    url = URL if identity is None else f"{URL}/{identity}"
    if method == "delete":
        return client.delete(url, params={"expected_revision": state.revision()})
    return getattr(client, method)(url, json={**(body or {}), "expected_revision": state.revision()})


def native_step(client, method, kind, *, identity=None, body=None, application=True):
    source = state.get_or_404()
    original = source.model_dump_json()
    revision, depth, count = state.revision(), state.undo_depth(), len(source.feature_log)
    response = request(client, method, identity=identity, body=body)
    assert response.status_code == (201 if method == "post" else 200), response.text
    result = state.get_or_404()
    assert (state.revision(), state.undo_depth(), len(result.feature_log)) == (revision + 1, depth + 1, count + 1)
    assert response.json()["revision"] == revision + 1
    row = result.feature_log[-1]
    assert row.op_kind == kind and dependencies(kind, row.params).known
    if application:
        assert row.params["nanoparticle_application_version"] == 1
        assert row.params["nanoparticle_connection_version"] == 1
        assert row.params["_proof_version"] == 1
        assert row.params["handle_overhang_id"]
        assert row.params["history_seed"]
    visible = response.json()["design"]["feature_log"][-1]
    assert visible["params"] == row.params
    assert visible["design_snapshot_gz_b64"] and visible["post_state_gz_b64"]
    assert source.model_dump_json() == original, "Publication mutated the retained source or its feature list"
    return result, row, response


def test_gate_false_real_http_create_and_apply_is_a_valid_legacy_control(document, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", False, raising=False)
    before = state.revision(), state.undo_depth(), len(state.get_or_404().feature_log)
    response = request(document, "post", body=create_body(state.get_or_404()))
    assert response.status_code == 201, response.text
    current = state.get_or_404()
    selected = version(current, response.json()["version_id"])
    assert selected.applied and selected.duplex_id == current.duplexes[0].id
    assert (state.revision(), state.undo_depth(), len(current.feature_log)) == tuple(value + 1 for value in before)
    assert current.feature_log[-1].params == {"nanoparticle_id": "gold", "version_id": selected.id, "_proof_version": 1}
    assert not dependencies(CREATE, current.feature_log[-1].params).known
    listed = document.get(URL)
    assert listed.status_code == 200
    measurement = listed.json()["versions"][0]["duplex_measurement"]
    assert measurement["paired_base_count"] == 12 and measurement["native_position_match"]


@pytest.mark.parametrize("body", [{"name": "  Renamed  "}, {"name": "  ", "applied": None}])
def test_gate_false_active_name_patch_keeps_real_postprocessing(native_prefix, monkeypatch, body):
    from backend.core import cluster_reconcile, lattice

    applied = append(native_prefix, CREATE, application_params(native_prefix), "applied-control")
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", False, raising=False)
    counts = {"reconcile": 0, "retry": 0}
    reconcile, retry = state.reconcile_cluster_membership, state._retry_pending_ligations

    def counted_reconcile(*args, **kwargs):
        counts["reconcile"] += 1
        return reconcile(*args, **kwargs)

    def counted_retry(*args, **kwargs):
        counts["retry"] += 1
        return retry(*args, **kwargs)

    monkeypatch.setattr(state, "reconcile_cluster_membership", counted_reconcile)
    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", counted_reconcile)
    monkeypatch.setattr(state, "_retry_pending_ligations", counted_retry)
    monkeypatch.setattr(lattice, "retry_pending_ligations", counted_retry)
    monkeypatch.setattr(routes, "_set_np_version_applied",
        lambda *_a, **_kw: pytest.fail("Name-only patch applied or restored geometry"))
    with opened_document(applied) as client:
        counts.update(reconcile=0, retry=0)
        response = request(client, "patch", identity="candidate", body=body)
        assert response.status_code == 200, response.text
        current = state.get_or_404()
        assert version(current).name == (body["name"].strip() or version(applied).name)
        assert current.duplexes == applied.duplexes
        assert current.nanoparticle_conjugations == applied.nanoparticle_conjugations
        assert counts == {"reconcile": 1, "retry": 1}


def test_native_http_combined_create_apply_is_one_editable_atomic_row(document, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    current, row, response = native_step(document, "post", CREATE, body=create_body(state.get_or_404(), name="  Combined  "))
    selected = version(current, response.json()["version_id"])
    assert row.params["version_id"] == selected.id
    assert row.params["duplex_id"] == selected.duplex_id == current.duplexes[0].id
    assert row.params["duplex_created_at"] == current.duplexes[0].created_at
    assert row.params["created_at"] == selected.created_at
    assert row.params["name"] == selected.name == current.duplexes[0].name == "Combined"
    assert row.params["prior_duplex_id"] is None and row.params["conflict_version_ids"] == []
    state.undo()
    assert not state.get_or_404().nanoparticle_connection_versions and not state.get_or_404().duplexes
    state.redo()
    assert authored(state.get_or_404()) == authored(current)


def test_native_http_lifecycle_cold_replays_while_applied_then_deletes_atomically(document, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    pending, _, response = native_step(document, "post", CREATE,
        body=create_body(state.get_or_404(), applied=False), application=False)
    identity = response.json()["version_id"]
    assert not version(pending, identity).applied
    active, first, _ = native_step(document, "patch", PATCH, identity=identity, body={"applied": True})
    first_duplex = version(active, identity).duplex_id
    renamed, rename, _ = native_step(document, "patch", PATCH, identity=identity, body={"name": "  Chosen  "})
    assert "applied" not in rename.params and "duplex_id" not in rename.params
    assert rename.params["prior_duplex_id"] == first_duplex
    assert version(renamed, identity).name == "Chosen" and renamed.duplexes[0].name == active.duplexes[0].name
    idle, unapply, _ = native_step(document, "patch", PATCH, identity=identity, body={"applied": False})
    assert unapply.params["prior_duplex_id"] == first_duplex
    assert not idle.duplexes and not version(idle, identity).applied
    assert version(idle, identity).constraint_root_nm is None
    active, reapply, _ = native_step(document, "patch", PATCH, identity=identity, body={"applied": True})
    assert reapply.params["duplex_id"] != first.params["duplex_id"]
    assert active.duplexes[0].name == "Chosen"
    # Poison every recovery body, then cross the JSON/process boundary. The
    # expected output still contains actual applied/restoration geometry.
    transported = active.model_copy(deep=True)
    for row in transported.feature_log:
        row.design_snapshot_gz_b64 = "poisoned recovery"
        row.post_state_gz_b64 = "poisoned recovery"
    transported = Design.model_validate_json(transported.model_dump_json())
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["native_editable"] and result["checked_commands"] == len(active.feature_log)
    finally:
        worker.close()
    deleted, row, _ = native_step(document, "delete", DELETE, identity=identity)
    assert row.params["prior_duplex_id"] == version(active, identity).duplex_id
    assert not deleted.nanoparticle_connection_versions and not deleted.duplexes
    state.undo()
    assert authored(state.get_or_404()) == authored(active)
    state.redo()
    assert authored(state.get_or_404()) == authored(deleted)


def initial_state(source, state_name):
    if state_name == "empty":
        return source.model_copy(deep=True)
    values = creation(source) if state_name == "pending" else application_params(source)
    return append(source, CREATE, values, "initial-candidate")


@pytest.mark.parametrize("state_name,method,body", [
    ("empty", "post", {"name": "  Together  ", "applied": True}),
    ("pending", "patch", {"name": "  Apply chosen  ", "applied": True}),
    ("pending", "patch", {"applied": False}),
    ("active", "patch", {"applied": True}),
    ("active", "patch", {"applied": False}),
    ("active", "patch", {"name": "  Label only  "}),
    ("active", "delete", None),
])
def test_native_route_has_exact_full_authoring_parity_with_legacy_http(
        native_prefix, monkeypatch, state_name, method, body):
    from backend.core import nanoparticle_connections as kernel

    source = initial_state(native_prefix, state_name)
    identity = None if method == "post" else "candidate"
    kind = {"post": CREATE, "patch": PATCH, "delete": DELETE}[method]
    body = create_body(source, **body) if method == "post" else body
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    with opened_document(source) as client:
        current, row, _ = native_step(client, method, kind, identity=identity, body=body)
        expected, values = authored(current), deepcopy(row.params)
        if state_name == "active" and body and body.get("applied") is True:
            assert version(current).duplex_id != version(source).duplex_id
        if body and body.get("name") and body.get("applied") is True:
            assert current.duplexes[0].name == body["name"].strip()

    # The independent reference runs the actual old HTTP route and its common
    # recorder. Inject identities/time only, never computed output geometry.
    original_version = routes.NanoparticleConnectionVersion
    original_duplex, original_relocate = kernel.Duplex, kernel.relocate_duplex
    with monkeypatch.context() as reference:
        reference.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", False)
        if method == "post":
            reference.setattr(routes, "NanoparticleConnectionVersion", lambda **kw: original_version(
                **{**kw, "id": values["version_id"], "created_at": values["created_at"]}))
        if values.get("applied"):
            reference.setattr(kernel, "Duplex", lambda **kw: original_duplex(
                **{**kw, "id": values["duplex_id"], "created_at": values["duplex_created_at"]}))
            reference.setattr(kernel, "relocate_duplex", lambda design, duplex, **kw: original_relocate(
                design, duplex, **{**kw, "identity_seed": values["history_seed"]}))
        with opened_document(source) as client:
            response = request(client, method, identity=identity, body=body)
            assert response.status_code == (201 if method == "post" else 200), response.text
            assert authored(state.get_or_404()) == expected


@pytest.mark.parametrize("body", [{}, {"applied": None}, {"name": None}, {"name": "  ", "applied": None}])
def test_native_active_null_or_omitted_toggle_is_name_only(native_prefix, monkeypatch, body):
    from backend.api import part_np_application_commands as application
    from backend.core import cluster_reconcile, lattice

    source = initial_state(native_prefix, "active")
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    forbidden = lambda *_a, **_kw: pytest.fail("Name-only PATCH applied or restored topology")
    monkeypatch.setattr(application, "set_version_applied", forbidden)
    monkeypatch.setattr(routes, "_set_np_version_applied", forbidden)
    counts = {"reconcile": 0, "retry": 0}
    reconcile, retry = state.reconcile_cluster_membership, state._retry_pending_ligations

    def counted_reconcile(*args, **kwargs):
        counts["reconcile"] += 1
        return reconcile(*args, **kwargs)

    def counted_retry(*args, **kwargs):
        counts["retry"] += 1
        return retry(*args, **kwargs)

    monkeypatch.setattr(state, "reconcile_cluster_membership", counted_reconcile)
    monkeypatch.setattr(cluster_reconcile, "reconcile_cluster_membership", counted_reconcile)
    monkeypatch.setattr(state, "_retry_pending_ligations", counted_retry)
    monkeypatch.setattr(lattice, "retry_pending_ligations", counted_retry)
    with opened_document(source) as client:
        counts.update(reconcile=0, retry=0)
        current, row, _ = native_step(client, "patch", PATCH, identity="candidate", body=body)
        assert "applied" not in row.params and "duplex_id" not in row.params
        assert row.params["name"] == version(source).name
        assert authored(current) == authored(source)
        assert counts == {"reconcile": 1, "retry": 1}


def state_signature():
    session = state._sessions[doc_context.get_current_doc()]
    return (session.design.model_dump_json(), session.revision,
            [item.model_dump_json() for item in session.history],
            [item.model_dump_json() for item in session.redo],
            doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())


@pytest.mark.parametrize("guard", ["stale", "protected"])
def test_native_refuses_before_inventory_defaults_or_snapshot(document, monkeypatch, guard):
    from backend.api import part_np_application_commands as application
    from backend.api import part_np_application_recording as recording

    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    if guard == "protected":
        source = state.get_or_404().copy_with(
            loadouts=[DesignLoadout(id="protected", name="Simulation", protected=True)],
            active_loadout_id="protected")
        state.load_design(source)
    before = state_signature()
    body = create_body(state.get_or_404())

    def forbidden(*_args, **_kwargs):
        pytest.fail("Refused request reached native inventory/defaults/snapshot")

    for module, names in ((application, ("_prepare_source", "_materialize")),
                          (recording, ("uuid4", "time")), (state, ("encode_design_snapshot",)),
                          (routes, ("NanoparticleConnectionVersion",))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    revision = state.revision() - (guard == "stale")
    response = document.post(URL, json={**body, "expected_revision": revision})
    assert response.status_code == 409, response.text
    if guard == "protected":
        assert response.json()["detail"]["code"] == "protected_simulation_loadout"
    assert state_signature() == before


def test_native_inventory_once_and_defaults_frozen_under_one_lock(document, monkeypatch):
    from backend.api import part_nanoparticle_connection_commands as pending
    from backend.api import part_np_application_commands as application
    from backend.api import part_np_application_recording as recording

    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    source = state.get_or_404()
    original_prepare, original_materialize = pending._prepare_source, application._materialize
    original_uuid, original_time = recording.uuid4, recording.time
    counts = {"source_inventory": 0, "materialize": 0, "uuid": 0, "time": 0}

    class GuardedLock:
        held = False
        def __enter__(self):
            assert not self.held, "Application adapter reacquired the non-reentrant state lock"
            self.held = True
            return self
        def __exit__(self, *_args):
            self.held = False

    lock = GuardedLock()

    def prepare(design):
        assert lock.held
        if design is source:
            counts["source_inventory"] += 1
        return original_prepare(design)

    def materialize(design, bound):
        assert lock.held and design is source
        counts["materialize"] += 1
        return original_materialize(design, bound)

    def make_id():
        assert lock.held and counts["source_inventory"] == 1 and not counts["materialize"]
        counts["uuid"] += 1
        return original_uuid()

    def now():
        assert lock.held and counts["source_inventory"] == 1 and not counts["materialize"]
        counts["time"] += 1
        return original_time()

    monkeypatch.setattr(state, "_lock", lock)
    monkeypatch.setattr(pending, "_prepare_source", prepare)
    monkeypatch.setattr(application, "_materialize", materialize)
    monkeypatch.setattr(recording, "uuid4", make_id)
    monkeypatch.setattr(recording, "time", now)
    current, row, _ = native_step(document, "post", CREATE, body=create_body(source))
    assert counts == {"source_inventory": 1, "materialize": 1, "uuid": 3, "time": 2}
    assert row.params["version_id"] == current.nanoparticle_connection_versions[0].id
    assert row.params["duplex_id"] == current.duplexes[0].id
    assert row.params["created_at"] == current.nanoparticle_connection_versions[0].created_at
    assert row.params["duplex_created_at"] == current.duplexes[0].created_at


@pytest.mark.parametrize("missing", ["particle", "version", "target"])
def test_native_missing_selection_is_typed_and_never_falls_back(document, monkeypatch, missing):
    from backend.api import part_np_application_commands as application

    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    before = state_signature()
    forbidden = lambda *_a, **_kw: pytest.fail("Missing selection reached native materialization or legacy fallback")
    monkeypatch.setattr(application, "_materialize", forbidden)
    monkeypatch.setattr(routes, "_set_np_version_applied", forbidden)
    monkeypatch.setattr(routes, "NanoparticleConnectionVersion", forbidden)
    if missing == "version":
        response = request(document, "patch", identity="missing", body={"applied": True})
        resource, path = "nanoparticle_connection_version", "version_id"
    else:
        body = create_body(state.get_or_404())
        url = URL.replace("/gold/", "/missing/") if missing == "particle" else URL
        if missing == "target":
            body["overhang_id"] = "missing"
        response = document.post(url, json={**body, "expected_revision": state.revision()})
        resource, path = ("nanoparticle", "nanoparticle_id") if missing == "particle" else ("overhang", "overhang_id")
    assert response.status_code == 404, response.text
    issue = response.json()["detail"]
    assert issue["code"] == "missing_reference"
    assert {"kind": resource, "identity": "missing", "parameter_path": [path]} in issue["references"]
    assert state_signature() == before


@pytest.mark.parametrize("failure", ["unsupported", "not_implemented"])
def test_native_failure_after_materialization_begins_never_uses_legacy_path(document, monkeypatch, failure):
    from backend.api import part_np_application_commands as application

    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    before = state_signature()
    calls = []

    def fail(_design, _bound):
        calls.append("native")
        if failure == "unsupported":
            raise CommandContractError("Injected late unsupported source", code="unsupported_thiol_source")
        raise NotImplementedError("Injected late native refusal")

    monkeypatch.setattr(application, "_materialize", fail)
    monkeypatch.setattr(routes, "_set_np_version_applied",
        lambda *_a, **_kw: pytest.fail("Native failure fell back into the old route"))
    if failure == "not_implemented":
        with pytest.raises(NotImplementedError, match="Injected late native refusal"):
            request(document, "post", body=create_body(state.get_or_404()))
    else:
        response = request(document, "post", body=create_body(state.get_or_404()))
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "unsupported_thiol_source"
    assert calls == ["native"] and state_signature() == before


@pytest.mark.parametrize("replacement", ["source", "session"])
def test_recorder_callback_rejects_source_or_session_identity_change(document, monkeypatch, replacement):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    doc = doc_context.get_current_doc()
    session = state._sessions[doc]
    source, before = session.design, state_signature()
    encode, calls = state.encode_design_snapshot, []
    substituted = copy(session) if replacement == "session" else None

    def substitute_after_pre_snapshot(design):
        result = encode(design)
        calls.append(True)
        if len(calls) == 1:
            if substituted is not None:
                state._sessions[doc] = substituted
            else:
                session.design = source.model_copy(deep=True)
        return result

    monkeypatch.setattr(state, "encode_design_snapshot", substitute_after_pre_snapshot)
    try:
        response = request(document, "post", body=create_body(source))
        assert response.status_code == 409, response.text
        assert len(calls) == 1
        if substituted is not None:
            assert substituted.design is source
    finally:
        state._sessions[doc] = session
    assert state_signature() == before


@pytest.mark.parametrize("stage", ["post-encode", "publish", "cancel"])
def test_native_recording_failure_restores_history_revision_and_request_markers(document, monkeypatch, stage):
    from backend.api import part_np_application_commands as application

    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    before = state_signature()
    encode, materialize = state.encode_design_snapshot, application._materialize
    calls = {"encode": 0, "native": 0}

    def native(design, bound):
        calls["native"] += 1
        return materialize(design, bound)

    def encode_or_fail(design):
        calls["encode"] += 1
        if calls["encode"] == 2:
            if stage == "cancel":
                raise KeyboardInterrupt("Injected native recording cancellation")
            raise RuntimeError("Injected native post-encode failure")
        return encode(design)

    monkeypatch.setattr(application, "_materialize", native)
    if stage == "publish":
        bump = state._bump_revision
        def publish_or_fail(session):
            bump(session)
            raise RuntimeError("Injected native publication failure")
        monkeypatch.setattr(state, "_bump_revision", publish_or_fail)
    else:
        monkeypatch.setattr(state, "encode_design_snapshot", encode_or_fail)
    # Direct call keeps BaseException cancellation out of the ASGI threadpool;
    # successful behavior is independently exercised through actual HTTP above.
    with pytest.raises(KeyboardInterrupt if stage == "cancel" else RuntimeError):
        routes.create_np_connection_version("gold", routes.NanoparticleConnectionVersionCreate(
            **create_body(state.get_or_404()), expected_revision=state.revision()))
    assert calls["native"] == 1 and state_signature() == before


def test_seventeen_handle_scope_keeps_legacy_before_native_work_or_defaults(native_prefix, monkeypatch):
    from backend.api import part_np_application_commands as application
    from backend.api import part_np_application_recording as recording
    from backend.api.part_recipe_edit import regenerate

    graft = native_prefix.feature_log[-1]
    source = regenerate(native_prefix, [*native_prefix.feature_log[:-1], graft.model_copy(
        update={"params": {**graft.params, "count": 17}})], lambda: None)
    assert len(source.nanoparticle_conjugations[0].surface_strands) == 17
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    forbidden = lambda *_a, **_kw: pytest.fail("Unsupported scope reached native output allocation or materialization")
    monkeypatch.setattr(application, "_materialize", forbidden)
    monkeypatch.setattr(recording, "uuid4", forbidden)
    monkeypatch.setattr(recording, "time", forbidden)
    original_legacy, calls = routes._set_np_version_applied, []

    def legacy(*args, **kwargs):
        calls.append(True)
        return original_legacy(*args, **kwargs)

    monkeypatch.setattr(routes, "_set_np_version_applied", legacy)
    with opened_document(source) as client:
        revision, depth = state.revision(), state.undo_depth()
        response = request(client, "post", body=create_body(source))
        assert response.status_code == 201, response.text
        current = state.get_or_404()
        selected = version(current, response.json()["version_id"])
        assert selected.applied and selected.duplex_id == current.duplexes[0].id
        assert calls == [True]
        assert (state.revision(), state.undo_depth()) == (revision + 1, depth + 1)
        assert current.feature_log[-1].params == {
            "nanoparticle_id": "gold", "version_id": selected.id, "_proof_version": 1}
        assert not dependencies(CREATE, current.feature_log[-1].params).known


def test_two_pending_alternatives_switch_real_ownership_and_cold_replay(document, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    original = state.get_or_404()
    handles = deepcopy(original.nanoparticle_conjugations[0].surface_strands)
    ids = []
    for name, handle in zip(("First", "Second"), handles, strict=True):
        _, _, response = native_step(document, "post", CREATE, application=False,
            body=create_body(original, name=name, strand_id=handle.strand_id, applied=False))
        ids.append(response.json()["version_id"])
    first, row_a, _ = native_step(document, "patch", PATCH, identity=ids[0], body={"applied": True})
    assert row_a.params["conflict_version_ids"] == [ids[1]]
    old_duplex = version(first, ids[0]).duplex_id
    current, row_b, _ = native_step(document, "patch", PATCH, identity=ids[1], body={"applied": True})
    assert row_b.params["conflict_version_ids"] == [ids[0]]
    assert row_b.params["prior_duplex_id"] is None
    old, selected = version(current, ids[0]), version(current, ids[1])
    assert not old.applied and old.duplex_id is None
    assert old.constraint_root_nm is None and old.constraint_radius_nm is None
    assert selected.applied and selected.duplex_id == row_b.params["duplex_id"] != old_duplex
    assert [item.id for item in current.duplexes] == [selected.duplex_id]
    restored, bound = current.nanoparticle_conjugations[0].surface_strands
    assert restored.strand_id == handles[0].strand_id and restored.helix_id == handles[0].helix_id
    assert restored.bound_overhang_id is None and bound.bound_overhang_id == selected.overhang_id
    assert current.find_strand(restored.strand_id).domains[0].helix_id == restored.helix_id
    listed = document.get(URL)
    assert listed.status_code == 200
    rows = {item["id"]: item for item in listed.json()["versions"]}
    assert rows[ids[0]]["duplex_measurement"] is None
    assert rows[ids[1]]["duplex_measurement"]["paired_base_count"] == 12
    assert rows[ids[1]]["duplex_measurement"]["native_position_match"]
    transported = current.model_copy(deep=True)
    for row in transported.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(Design.model_validate_json(transported.model_dump_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["native_editable"] and result["checked_commands"] == 9
    finally:
        worker.close()


@pytest.mark.parametrize("collision", ["version", "duplex", "cluster"])
def test_generated_output_collision_is_typed_before_snapshot_without_fallback(native_prefix, monkeypatch, collision):
    from backend.api import part_np_application_commands as application
    from backend.api import part_np_application_recording as recording

    source = initial_state(native_prefix, "active" if collision == "duplex" else "pending")
    namespace, version_id, duplex_id = seed(9801), "fresh-version", "fresh-duplex"
    if collision == "version":
        version_id = "candidate"
        resource, identity, path = "nanoparticle_connection_version", version_id, "version_id"
    elif collision == "duplex":
        duplex_id = version(source).duplex_id
        resource, identity, path = "duplex", duplex_id, "duplex_id"
    else:
        identity = identity_factory(namespace)("duplex-cluster", [duplex_id])
        # A legitimate empty named group already owns the prospective child ID.
        source = source.copy_with(cluster_transforms=[*source.cluster_transforms,
            ClusterRigidTransform(id=identity, name="Existing group")])
        resource, path = "cluster", "history_seed"
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True, raising=False)
    outputs = iter((namespace, version_id, duplex_id))
    monkeypatch.setattr(recording, "uuid4", lambda: next(outputs))
    forbidden = lambda *_a, **_kw: pytest.fail("Output collision reached snapshot/native work or legacy fallback")
    monkeypatch.setattr(application, "_materialize", forbidden)
    monkeypatch.setattr(routes, "_set_np_version_applied", forbidden)
    with opened_document(source) as client:
        before = state_signature()
        # Baseline loading is outside this transaction tripwire.
        monkeypatch.setattr(state, "encode_design_snapshot", forbidden)
        response = request(client, "post", body=create_body(source))
        assert response.status_code == 422, response.text
        issue = response.json()["detail"]
        assert issue["code"] == "invalid_selection"
        assert {"kind": resource, "identity": identity, "parameter_path": [path]} in issue["references"]
        assert state_signature() == before
