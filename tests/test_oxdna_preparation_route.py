"""Tests first for the private owned-DNA preparation route integration.

The real route and capture boundary run against an eight-base source. Geometry,
lineage, storage, packaging and engine execution are replaced at their public
boundaries. No files, solver, application lifespan or background jobs run here.
"""

import asyncio
from importlib import import_module
from threading import Event, get_ident
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool as real_threadpool
import pytest

from backend.api import doc_context, state
from backend.core import models as m
from backend.core.oxdna_job import OxdnaJob, OxdnaStageStatus, OxdnaStatus
from backend.core.part_capture_graph import CaptureShapeError
from backend.core.part_command_errors import CommandContractError
from tests.test_oxdna_preparation_capture import _document_context, host, options


def forbidden(*_args, **_kwargs):
    pytest.fail("Preparation reached unexpected storage, execution or live fallback")


@pytest.fixture
def route_case(monkeypatch):
    routes = import_module("backend.api.routes_oxdna")
    revisions = import_module("backend.core.project_revisions")
    staleness = import_module("backend.core.oxdna_staleness")
    coating = import_module("backend.core.streptavidin")
    mobile = import_module("backend.physics.oxdna_mobile_gold")
    protein = import_module("backend.physics.oxdna_protein")
    peg = import_module("backend.physics.oxdna_peg")
    with _document_context() as (identity, session, original):
        case = SimpleNamespace(routes=routes, identity=identity, session=session,
            original=original, consumers=[], effects=[], saves=[], legacy_reads=[],
            before_lineage=lambda: None, writer=lambda *_args, **_kwargs: {},
            workspace=object(), geometry=object(), jobs=[])

        def consume(name, design, result=None):
            case.consumers.append((name, design))
            return result

        def legacy():
            case.legacy_reads.append(original)
            return original

        def new_job(**kwargs):
            case.before_lineage()
            job = OxdnaJob(job_id="isolated-preparation", created_at=0.,
                status=OxdnaStatus.queued, **kwargs)
            case.jobs.append(job)
            return job

        def lineage(workspace, design, kind, job_id):
            assert workspace is case.workspace and kind == "oxdna"
            assert job_id == "isolated-preparation"
            case.effects.append("lineage")
            consume("lineage", design)
            return SimpleNamespace(project_id="private-project", revision_id="private-revision")

        def save(job, workspace):
            assert workspace is case.workspace
            case.effects.append("save")
            case.saves.append(job.status)

        def writer(design, geometry, job, workspace, specs, **kwargs):
            assert geometry is case.geometry and workspace is case.workspace
            assert specs == [case.spec]
            case.effects.append("writer")
            consume("writer", design)
            return case.writer(design, geometry, job, workspace, specs, **kwargs)

        def start(job, workspace, specs):
            assert workspace is case.workspace and specs == [case.spec]
            case.effects.append("start")

        async def direct(function, *args, **kwargs):
            return function(*args, **kwargs)

        case.spec = SimpleNamespace(interaction="DNA2", to_status=lambda:
            OxdnaStageStatus(name="fake_mc", kind="mc", steps=100))
        monkeypatch.setattr(routes, "OWNED_DNA_PREPARATION_ENABLED", True, raising=False)
        monkeypatch.setattr(routes, "_workspace", lambda: case.workspace)
        monkeypatch.setattr(routes, "find_oxdna", lambda: "/unexecuted/oxDNA")
        for name in ("oxdna_supports_cuda", "oxdna_supports_dnanm",
                     "oxdna_supports_rigid_bussi", "oxdna_supports_matched_bussi_rng",
                     "oxdna_supports_physics_v3"):
            monkeypatch.setattr(routes, name, lambda *_args: True)
        monkeypatch.setattr(routes, "oxdna_build_flavor", lambda *_args: "upstream")
        monkeypatch.setattr(routes.design_state, "get_or_404", legacy)
        monkeypatch.setattr(coating, "require_coating_simulation_support",
            lambda design, *_args: consume("coating", design))
        monkeypatch.setattr(mobile, "has_mobile_gold", lambda design: consume("mobile", design, False))
        monkeypatch.setattr(protein, "has_proteins", lambda design: consume("protein", design, False))
        monkeypatch.setattr(peg, "is_peg", lambda *_args: False)
        monkeypatch.setattr(peg, "find_peg_oxdna", forbidden)
        monkeypatch.setattr(routes, "count_undefined_bases",
            lambda design, **_kwargs: consume("sequence", design, (0, 9)))
        monkeypatch.setattr(routes, "designed_pair_complementarity",
            lambda design: consume("complementarity", design, (4, 4)))
        monkeypatch.setattr(routes, "build_relaxation_stages", lambda **_kwargs: [case.spec])
        monkeypatch.setattr(routes, "apply_stage_overrides", lambda stages, _overrides: stages)
        monkeypatch.setattr(routes, "assign_stage_seeds", lambda stages, _seed: stages)
        monkeypatch.setattr(routes, "constrain_fixed_core_stages", forbidden)
        monkeypatch.setattr(routes, "new_oxdna_job", new_job)
        monkeypatch.setattr(revisions, "record_simulation_revision", lineage)
        monkeypatch.setattr(OxdnaJob, "save", save)
        monkeypatch.setattr(OxdnaJob, "job_dir", forbidden)
        monkeypatch.setattr(OxdnaJob, "list_jobs", forbidden)
        monkeypatch.setattr(routes, "_seed_geometry",
            lambda design: consume("geometry", design, case.geometry))
        monkeypatch.setattr(routes, "_strand_nucleotide_order",
            lambda design: consume("order", design, list(range(9))))
        monkeypatch.setattr(staleness, "oxdna_design_fingerprint",
            lambda design: consume("fingerprint", design, "fake-input-fingerprint"))
        monkeypatch.setattr(staleness, "effective_feature_log_position",
            lambda design: consume("log-position", design, 0))
        monkeypatch.setattr(routes, "prepare_oxdna_job", writer)
        monkeypatch.setattr(routes, "start_job", start)
        monkeypatch.setattr(routes, "run_in_threadpool", direct)
        yield case


def request(case, **changes):
    return case.routes.CreateOxdnaJobRequest(backend="CPU", seed=13,
        autostart=False, **changes)


def invoke(case, **changes):
    return asyncio.run(case.routes.create_oxdna_job(request(case, **changes)))


def assert_no_side_effects(case):
    assert case.effects == []
    assert case.saves == []


def test_owned_preparation_route_is_disabled_by_default():
    # No route_case fixture here: it deliberately enables the private branch.
    routes = import_module("backend.api.routes_oxdna")
    assert routes.OWNED_DNA_PREPARATION_ENABLED is False


@pytest.mark.parametrize("backend", ["CPU", "CUDA"])
def test_supported_route_uses_one_owned_model_for_every_consumer(route_case, backend):
    case = route_case
    expected = case.original.without_reference_geometry().model_dump(mode="json")
    body = request(case).model_copy(update={"backend": backend, "autostart": True})
    result = asyncio.run(case.routes.create_oxdna_job(body))
    assert result["status"] == "queued" and result["n_nucleotides"] == 9
    assert case.legacy_reads == []
    assert {name for name, _ in case.consumers} == {
        "coating", "mobile", "protein", "sequence", "complementarity",
        "lineage", "geometry", "order", "fingerprint", "log-position", "writer"}
    owned = case.consumers[0][1]
    assert owned is not case.original
    assert all(design is owned for _, design in case.consumers)
    assert owned.model_dump(mode="json") == expected
    assert case.effects == ["lineage", "save", "writer", "save", "start"]
    assert case.saves == [OxdnaStatus.preparing, OxdnaStatus.queued]
    assert case.session.design is case.original and case.session.revision == 7


def test_every_consumer_receives_filtered_owned_geometry_and_retained_archive(route_case):
    case = route_case
    case.original.helices.append(m.Helix(id="reference", axis_start=m.Vec3(x=3, y=0, z=0),
        axis_end=m.Vec3(x=3, y=0, z=2.38), length_bp=8))
    case.original.strands.append(m.Strand(id="backdrop", is_reference=True, sequence="ACGTACGT",
        domains=[m.Domain(helix_id="reference", start_bp=0, end_bp=7, direction=m.Direction.FORWARD)]))
    original = case.original.model_dump(mode="json")
    expected = case.original.without_reference_geometry().model_dump(mode="json")

    assert invoke(case)["status"] == "queued"
    assert case.legacy_reads == []
    owned = case.consumers[0][1]
    assert all(design is owned for _, design in case.consumers)
    assert [helix.id for helix in owned.helices] == ["h_XY_0_0"]
    assert [strand.id for strand in owned.strands] == ["dna"]
    assert owned.model_dump(mode="json") == expected
    assert owned.feature_log == case.original.feature_log
    assert owned.feature_log[0] is not case.original.feature_log[0]
    assert owned.annotations == case.original.annotations
    assert owned.annotations[0].refs is not case.original.annotations[0].refs
    assert owned.visibility_state == case.original.visibility_state
    assert owned.visibility_state is not case.original.visibility_state
    assert case.original.model_dump(mode="json") == original


def test_real_threadpool_writer_keeps_nested_archive_after_live_alias_mutation(route_case, monkeypatch):
    case = route_case
    expected = case.original.model_dump(mode="json")
    release = Event()
    finished = Event()
    monkeypatch.setattr(case.routes, "run_in_threadpool", real_threadpool)

    async def scenario():
        loop = asyncio.get_running_loop()
        entered = loop.create_future()
        owner_thread = get_ident()

        def writer(design, *_args, **_kwargs):
            try:
                assert get_ident() != owner_thread
                loop.call_soon_threadsafe(entered.set_result, design)
                assert release.wait(5), "Test did not release the isolated writer"
                assert design.model_dump(mode="json") == expected
                return {}
            finally:
                finished.set()

        case.writer = writer
        task = asyncio.create_task(case.routes.create_oxdna_job(request(case)))
        try:
            owned = await asyncio.wait_for(asyncio.shield(entered), 5)
            with state._lock:
                case.original.helices[0].axis_start.x = 123.
                case.original.helices[0].loop_skips[0].delta = -1
                case.original.strands[0].domains[0].end_bp = 3
                case.original.annotations[0].refs[0]["notes"].append("late")
                case.original.feature_log[0].params["legacy"]["values"].append(3)
                case.original.metadata.tags.append("late")
            release.set()
            result = await asyncio.wait_for(asyncio.shield(task), 5)
            assert owned is not case.original and result["status"] == "queued"
            assert owned.model_dump(mode="json") == expected
        finally:
            release.set()
            await asyncio.wait_for(asyncio.shield(task), 5)
        assert finished.is_set()

    asyncio.run(scenario())
    # Rogue deep mutation is deliberately not described as a revision conflict.
    assert case.session.revision == 7


@pytest.mark.parametrize("change", ["revision", "source", "session_aba", "document", "gate_and_revision"])
def test_retained_capture_refuses_changed_origin_before_any_side_effect(route_case, monkeypatch, change):
    case = route_case

    def change_origin():
        with state._lock:
            if change in {"revision", "gate_and_revision"}:
                case.session.revision += 1
            elif change == "source":
                case.session.design = case.original.model_copy(deep=True)
            elif change == "session_aba":
                state._sessions[case.identity] = state._DesignSession(design=case.original, revision=7)
            else:
                doc_context.set_current_doc("__unopened_preparation_context__")
        if change == "gate_and_revision":
            monkeypatch.setattr(case.routes, "OWNED_DNA_PREPARATION_ENABLED", False)

    case.before_lineage = change_origin
    with pytest.raises(HTTPException) as caught:
        invoke(case)
    assert caught.value.status_code == 409
    assert_no_side_effects(case)
    assert case.legacy_reads == []
    assert "__unopened_preparation_context__" not in state._sessions


def test_gate_flip_alone_preserves_the_already_owned_request(route_case, monkeypatch):
    case = route_case
    case.before_lineage = lambda: monkeypatch.setattr(case.routes, "OWNED_DNA_PREPARATION_ENABLED", False)
    assert invoke(case)["status"] == "queued"
    assert case.legacy_reads == []
    assert all(design is not case.original for _, design in case.consumers)


@pytest.mark.parametrize("failure,status", [("limit", 413), ("identity", 422)])
def test_capture_refusal_never_falls_back_or_records_lineage(route_case, monkeypatch, failure, status):
    case = route_case
    if failure == "limit":
        inputs = import_module("backend.core.oxdna_preparation_inputs")
        monkeypatch.setattr(inputs, "MAX_NODES", 1)
    else:
        case.original.id = ""
    with pytest.raises(HTTPException) as caught:
        invoke(case)
    assert caught.value.status_code == status
    assert_no_side_effects(case)
    assert case.legacy_reads == []


@pytest.mark.parametrize("profile", ["disabled", "surface", "nested_unreviewed"])
def test_disabled_or_explicitly_unsupported_scope_keeps_legacy_route(route_case, monkeypatch, profile):
    case = route_case
    changes = {}
    if profile == "disabled":
        monkeypatch.setattr(case.routes, "OWNED_DNA_PREPARATION_ENABLED", False)
        monkeypatch.setattr(host(), "capture_current", forbidden)
    elif profile == "surface":
        changes["surface"] = {"stiff": 0}
    else:
        # Existing core policy treats this as an unreviewed profile, not malformed
        # origin metadata. Keep that distinction when adapting the route.
        case.original.helices[0].axis_start.x = float("nan")
    assert invoke(case, **changes)["status"] == "queued"
    assert case.legacy_reads == [case.original]
    assert case.effects == ["lineage", "save", "writer", "save"]


def test_adapter_receives_exact_nine_raw_options_without_normalizing(route_case, monkeypatch):
    body = request(route_case, surface={"stiff": 0}, stage_overrides={"mc": {"steps": 100}})
    received = []
    receipt = SimpleNamespace(supported=True)

    def capture(value):
        received.append(value)
        return receipt

    monkeypatch.setattr(host(), "capture_current", capture)
    assert host().capture_for_request(body) is receipt
    assert len(received) == 1 and received[0] == options(
        surface={"stiff": 0}, stage_overrides={"mc": {"steps": 100}})
    assert received[0]["surface"] is body.surface
    assert received[0]["stage_overrides"] is body.stage_overrides
    receipt.supported = False
    assert host().capture_for_request(body) is None


@pytest.mark.parametrize("error,status", [
    (CaptureShapeError("unreviewed origin header"), 422),
    (CommandContractError("bounded input", code="oxdna_input_capture_limit"), 413),
    (CommandContractError("unexpected command issue", code="unexpected_contract"), None),
])
def test_adapter_translates_only_declared_refusals(route_case, monkeypatch, error, status):
    def reject(_options):
        raise error

    monkeypatch.setattr(host(), "capture_current", reject)
    with pytest.raises(HTTPException if status else CommandContractError) as caught:
        host().capture_for_request(request(route_case))
    if status:
        assert caught.value.status_code == status
    else:
        assert caught.value is error
    assert_no_side_effects(route_case)


@pytest.mark.parametrize("failure", ["undefined", "complementarity", "binary", "cuda", "physics"])
def test_existing_preparation_failures_remain_400_before_side_effects(route_case, monkeypatch, failure):
    case = route_case
    body = request(case)
    if failure == "undefined":
        monkeypatch.setattr(case.routes, "count_undefined_bases", lambda *_args, **_kwargs: (1, 9))
    elif failure == "complementarity":
        monkeypatch.setattr(case.routes, "designed_pair_complementarity", lambda *_args: (0, 4))
    elif failure == "binary":
        monkeypatch.setattr(case.routes, "find_oxdna", lambda: None)
    elif failure == "cuda":
        body.backend = "CUDA"
        monkeypatch.setattr(case.routes, "oxdna_supports_cuda", lambda *_args: False)
    else:
        monkeypatch.setattr(case.routes, "oxdna_supports_physics_v3", lambda *_args: False)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(case.routes.create_oxdna_job(body))
    assert caught.value.status_code == 400
    assert_no_side_effects(case)


def test_writer_failure_keeps_failed_job_and_never_queues_or_starts(route_case):
    case = route_case

    def fail(*_args, **_kwargs):
        raise OSError("isolated writer failed")

    case.writer = fail
    body = request(case).model_copy(update={"autostart": True})
    result = asyncio.run(case.routes.create_oxdna_job(body))
    assert result["status"] == "failed"
    assert "isolated writer failed" in result["error"]
    assert case.effects == ["lineage", "save", "writer", "save"]
    assert case.saves == [OxdnaStatus.preparing, OxdnaStatus.failed]


@pytest.mark.parametrize("phase", ["capture", "writer"])
def test_cancellation_propagates_without_queueing_or_autostart(route_case, monkeypatch, phase):
    case = route_case
    cancellation = asyncio.CancelledError("preparation cancelled")
    if phase == "capture":
        def cancelled(_options):
            raise cancellation
        monkeypatch.setattr(host(), "capture_current", cancelled)
    else:
        async def cancelled(*_args, **_kwargs):
            raise cancellation
        monkeypatch.setattr(case.routes, "run_in_threadpool", cancelled)
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(case.routes.create_oxdna_job(request(case).model_copy(update={"autostart": True})))
    assert caught.value is cancellation
    if phase == "capture":
        assert_no_side_effects(case)
    else:
        # Cancellation does not promise worker termination or undo lineage that
        # was already recorded. It must not publish a queued/successful result.
        assert case.effects == ["lineage", "save"]
        assert case.saves == [OxdnaStatus.preparing]
