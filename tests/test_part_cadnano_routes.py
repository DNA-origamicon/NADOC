"""Explicit caDNAno replacement streams bounded inputs and publishes once."""

import asyncio
from copy import deepcopy
import json
from threading import Event, Thread, get_ident

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import Headers

from backend.api import routes_part_cadnano_import as routes, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Annotation, CameraPose, Design, DesignLoadout, Nanoparticle, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedResolver, InputSource, describe, embed
from backend.core.part_verification_capture import capture
from tests.test_part_cadnano_commands import source


PATH = "/api/design/features/import/cadnano"


@pytest.fixture
def client():
    token = set_current_doc("explicit-pinned-cadnano-route")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    state.load_design(create_empty_part("Initial empty", "HONEYCOMB"))
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def query(**changes):
    return {"expected_design_id": state.get_or_404().id, "expected_revision": state.revision(), **changes}


def post(client, *, raw=None, params=None, headers=None):
    return client.post(PATH, params=query() if params is None else params,
        content=json.dumps(source(), separators=(",", ":")).encode() if raw is None else raw,
        headers={"content-type": "application/json", **(headers or {})})


def unchanged(before, revision, depth):
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth


def test_openapi_documents_raw_source_and_required_replacement_guards(client):
    operation = client.get("/openapi.json").json()["paths"][PATH]["post"]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["expected_design_id"]["required"]
    assert parameters["expected_revision"]["required"]
    assert not parameters["name_override"]["required"]
    assert operation["requestBody"]["required"]
    assert set(operation["requestBody"]["content"]) == {"application/json"}
    assert "complete replacement" in operation["description"]


@pytest.mark.parametrize("square", [False, True])
def test_replacement_pins_exact_bytes_new_root_full_history_and_one_undo_redo(client, square):
    if square:
        state.load_design(create_empty_part("Initial empty", "SQUARE"))
    before = deepcopy(state.get_or_404())
    revision, depth = state.revision(), state.undo_depth()
    raw = json.dumps(source(), indent=1).encode()
    response = post(client, raw=raw, params=query(name_override="Explicit name"))
    assert response.status_code == 201, response.text
    design = state.get_or_404()
    assert design.id != before.id and design.recipe_root.kind == "empty"
    assert design.metadata.name == "Explicit name" and not design.metadata.tags
    assert not design.nanoparticles and len(design.feature_log) == len(design.input_sources) == 1
    entry = design.feature_log[0]
    assert entry.op_kind == "cadnano-import" and entry.params["name_override"] == "Explicit name"
    assert "expected_revision" not in entry.params and "expected_design_id" not in entry.params
    descriptor = InputSource.model_validate(entry.params["source"])
    assert EmbeddedResolver(design.input_sources)(descriptor) == raw
    initial = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    assert initial.recipe_root == design.recipe_root
    assert not initial.helices and not initial.nanoparticles and not initial.feature_log
    expected = execute(entry.op_kind, initial, entry.params)
    assert expected.model_dump(include=AUTHORING_FIELDS) == design.model_dump(include=AUTHORING_FIELDS)
    result = response.json()
    assert result["revision"] == revision + 1 == state.revision()
    assert result["design"]["feature_log"][0]["post_state_gz_b64"] == entry.post_state_gz_b64
    assert state.undo_depth() == depth + 1
    state.undo()
    assert state.get_or_404() == before
    state.redo()
    assert state.get_or_404() == design


def test_import_is_reproduced_in_fresh_worker_after_reload_with_poisoned_outputs(client):
    response = post(client)
    assert response.status_code == 201, response.text
    design = Design.from_json(state.get_or_404().to_json())
    design.feature_log[0].design_snapshot_gz_b64 = "poisoned"
    design.feature_log[0].post_state_gz_b64 = "poisoned"
    result = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert result["status"] == "reproduced_import", result
    worker = VerificationWorker(capture(design))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()["status"] == "reproduced_import"
    finally:
        worker.close()


@pytest.mark.parametrize("change", [
    lambda value: value.pop("expected_revision"), lambda value: value.pop("expected_design_id"),
    lambda value: value.update(expected_revision="true"), lambda value: value.update(expected_revision="1.0"),
    lambda value: value.update(expected_revision="-1"), lambda value: value.update(expected_revision="9" * 30),
    lambda value: value.update(expected_design_id=""), lambda value: value.update(name_override="x" * 1025),
    lambda value: value.update(history_seed="caller-seed"),
])
def test_invalid_query_is_rejected_before_source_stream_or_model_work(client, monkeypatch, change):
    params = query()
    change(params)
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    async def do_not_read(_request):
        pytest.fail("Invalid query read source")

    monkeypatch.setattr(routes, "_read_source", do_not_read)
    response = post(client, params=params)
    assert response.status_code == 422, response.text
    unchanged(before, revision, depth)


def test_repeated_query_guards_are_rejected(client):
    params = [*query().items(), ("expected_revision", state.revision())]
    assert post(client, params=params).status_code == 422


@pytest.mark.parametrize("mismatch", ["revision", "identity", "no_document"])
def test_stale_target_or_missing_part_is_rejected_before_reading(client, monkeypatch, mismatch):
    params = query()
    if mismatch == "revision":
        params["expected_revision"] -= 1
    elif mismatch == "identity":
        params["expected_design_id"] = "another-part"
    else:
        state.load_design(None)

    async def do_not_read(_request):
        pytest.fail("Unbound request read source")

    monkeypatch.setattr(routes, "_read_source", do_not_read)
    before = state.get_design()
    revision, depth = state.revision(), state.undo_depth()
    response = post(client, params=params)
    assert response.status_code == (404 if mismatch == "no_document" else 409)
    assert state.get_design() is before
    assert state.revision() == revision and state.undo_depth() == depth


@pytest.mark.parametrize("retained", ["rootless", "particle", "history", "source", "loadout",
                                     "annotation", "camera", "visibility", "name"])
def test_nonempty_or_retained_state_requires_new_empty_tab_before_reading(client, monkeypatch, retained):
    design = state.get_or_404()
    if retained == "rootless":
        design.recipe_root = None
    elif retained == "particle":
        design.nanoparticles = [Nanoparticle(id="existing", diameter_nm=12)]
    elif retained == "history":
        design.feature_log = [SnapshotLogEntry(op_kind="cadnano-import", label="Old import")]
    elif retained == "source":
        descriptor = describe(b"retained bytes", format="blob", media_type="application/octet-stream")
        design.input_sources = {descriptor.sha256: embed(descriptor, b"retained bytes")}
    elif retained == "loadout":
        design.loadouts = [DesignLoadout(name="Retained recovery", design_snapshot_gz_b64="opaque recovery")]
    elif retained == "annotation":
        design.annotations = [Annotation(text="Retain this")]
    elif retained == "camera":
        design.camera_poses = [CameraPose()]
    elif retained == "visibility":
        design.visibility_state.hidden_cluster_ids = ["retained"]
    else:
        state.load_design(create_empty_part("x" * 1025, "HONEYCOMB"))
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    async def do_not_read(_request):
        pytest.fail("Retained state was admitted before body upload")

    monkeypatch.setattr(routes, "_read_source", do_not_read)
    response = post(client)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "fresh_empty_part_required"
    assert "fresh empty part or tab" in response.json()["detail"]["detail"]
    unchanged(before, revision, depth)


@pytest.mark.parametrize("headers,status", [
    ({"content-type": "text/plain"}, 415), ({"content-encoding": "gzip"}, 415),
    ({"content-length": str(routes.MAX_SOURCE_BYTES + 1)}, 413),
    ({"content-length": "invalid"}, 400), ({"content-length": "-1"}, 400),
])
def test_transport_headers_fail_before_native_build(client, monkeypatch, headers, status):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    monkeypatch.setattr(routes, "_prepare", lambda *_a: pytest.fail("Rejected transport entered builder"))
    response = post(client, headers=headers)
    assert response.status_code == status, response.text
    unchanged(before, revision, depth)


class StreamRequest:
    def __init__(self, chunks, headers=None):
        self.headers = Headers({"content-type": "application/json", **(headers or {})})
        self.chunks = chunks
        self.read_count = 0

    async def stream(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk


@pytest.mark.parametrize("headers", [{}, {"content-length": "1"}])
def test_chunked_and_lying_length_streams_stop_at_the_actual_limit(headers):
    request = StreamRequest([b"a" * (routes.MAX_SOURCE_BYTES - 1), b"bc", b"never read"], headers)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes._read_source(request))
    assert error.value.status_code == 413 and request.read_count == 2


def test_exact_source_limit_is_retained_without_dropping_bytes():
    request = StreamRequest([b"a", b"b" * (routes.MAX_SOURCE_BYTES - 1)])
    assert asyncio.run(routes._read_source(request)) == b"a" + b"b" * (routes.MAX_SOURCE_BYTES - 1)
    request = StreamRequest([b"unread"], {"content-length": str(routes.MAX_SOURCE_BYTES + 1)})
    with pytest.raises(HTTPException):
        asyncio.run(routes._read_source(request))
    assert request.read_count == 0


@pytest.mark.parametrize("raw,code,status", [
    pytest.param(b"invalid JSON", "unsupported_source", 422, id="invalid-json"),
    pytest.param(b'{"vstrands":[],"photoproduct_junctions":[]}', "unsupported_source", 422, id="unknown-field"),
    pytest.param(b"x" * (routes.MAX_SOURCE_BYTES + 1), "source_limit", 413, id="source-over-budget"),
])
def test_invalid_source_is_atomic_with_no_legacy_fallback(client, monkeypatch, raw, code, status):
    from backend.api import crud

    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    monkeypatch.setattr(crud, "import_cadnano_design", lambda *_a: pytest.fail("Native import fell back"))
    response = post(client, raw=raw)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    unchanged(before, revision, depth)


@pytest.mark.parametrize("stage", ["pre_encode", "post_encode", "validate", "response", "undo_snapshot"])
def test_prepublication_failures_do_not_change_design_revision_or_history(client, monkeypatch, stage):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    if stage in {"pre_encode", "post_encode"}:
        original, calls = state.encode_design_snapshot, 0

        def fail_encoding(design):
            nonlocal calls
            calls += 1
            if calls == (1 if stage == "pre_encode" else 2):
                raise RuntimeError("injected encoding failure")
            return original(design)

        monkeypatch.setattr(state, "encode_design_snapshot", fail_encoding)
    else:
        def fail(*_args, **_kwargs):
            raise RuntimeError("injected preparation failure")

        target, name = (state, "_snapshot_copy") if stage == "undo_snapshot" else (
            routes, "validate_design" if stage == "validate" else "_design_response")
        monkeypatch.setattr(target, name, fail)
    with pytest.raises(RuntimeError, match="injected"):
        post(client)
    unchanged(before, revision, depth)


@pytest.mark.parametrize("change", ["revision", "identity"])
def test_changes_during_private_preparation_cannot_be_overwritten(client, monkeypatch, change):
    original = routes._prepare
    changed = {}

    def concurrent_edit(*args):
        candidate, response = original(*args)
        current = state.get_or_404()
        if change == "identity":
            state.load_design(Design(metadata={"name": "Concurrently opened"}))
        else:
            state.set_design(current.copy_with(metadata=current.metadata.model_copy(update={"name": "Concurrent edit"})))
        changed.update(before=state.get_or_404().model_dump_json(), revision=state.revision(), depth=state.undo_depth())
        return candidate, response

    monkeypatch.setattr(routes, "_prepare", concurrent_edit)
    response = post(client)
    assert response.status_code == 409, response.text
    unchanged(**changed)


def test_disconnected_import_is_cancelled_before_publication(client, monkeypatch):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    async def disconnected(_request):
        return True

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    response = post(client)
    assert response.status_code == 499
    unchanged(before, revision, depth)


def test_http_document_context_and_threadpool_are_isolated():
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")
    documents = {}
    for doc in ("pinned-import-a", "pinned-import-b"):
        token = set_current_doc(doc)
        try:
            state.load_design(create_empty_part(doc, "HONEYCOMB"))
            documents[doc] = state.get_or_404(), state.revision()
        finally:
            reset_current_doc(token)
    try:
        with TestClient(app) as api:
            target, revision = documents["pinned-import-a"]
            response = post(api, params={"expected_design_id": target.id, "expected_revision": revision},
                            headers={"X-NADOC-Doc": "pinned-import-a"})
            assert response.status_code == 201, response.text
        assert state.peek_design("pinned-import-a").id != target.id
        assert state.peek_design("pinned-import-b") is documents["pinned-import-b"][0]
        token = set_current_doc("pinned-import-b")
        try:
            assert state.revision() == documents["pinned-import-b"][1] and state.undo_depth() == 0
        finally:
            reset_current_doc(token)
    finally:
        for doc in documents:
            token = set_current_doc(doc)
            try:
                state.close_session()
            finally:
                reset_current_doc(token)


def test_preparation_runs_without_state_lock_or_event_loop_blocking(client, monkeypatch):
    original = routes._prepare
    prepared = Event()
    checks = []

    def observe_from_another_thread():
        token = set_current_doc("explicit-pinned-cadnano-route")
        try:
            checks.append(state.get_design_with_revision())
            prepared.set()
        finally:
            reset_current_doc(token)

    async def track_pool(function, *args, **kwargs):
        if function is routes._prepare:
            event_loop_thread = get_ident()

            def private(*inner_args):
                assert get_ident() != event_loop_thread
                observer = Thread(target=observe_from_another_thread)
                try:
                    observer.start()
                    assert prepared.wait(2), "Private preparation held the state lock"
                    return original(*inner_args)
                finally:
                    observer.join(2)

            return await actual_pool(private, *args, **kwargs)
        return await actual_pool(function, *args, **kwargs)

    actual_pool = routes.run_in_threadpool
    monkeypatch.setattr(routes, "run_in_threadpool", track_pool)
    response = post(client)
    assert response.status_code == 201, response.text
    assert checks and checks[0][0] is not None
