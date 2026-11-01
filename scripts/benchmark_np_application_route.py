"""Memory-only ordinary NP HTTP/geometry comparison under unchanged budgets.

Run serially. Both arms use this checkout's existing molecular kernel. Only
the route gate differs; explicit identities and times match between arms.
No app lifespan, user file, solver or forced GC is used. stdout is the report.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import gc
import json
import traceback
from threading import Barrier, Event, Thread
from time import perf_counter
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import crud, doc_context, routes_nanoparticles as routes, state
from backend.api import part_nanoparticle_connection_commands as pending
from backend.api import part_np_application_commands as application
from backend.api import part_np_application_recording as recording
from backend.api import part_np_pending_context_commands as context
from backend.api.part_proof_commands import dependencies
from backend.api.part_recipe_edit import regenerate
from backend.api.part_revision_status import revision_status
from backend.api.part_verification_worker import VerificationWorker
from backend.core import nanoparticle_connections as kernel
from backend.core.models import Design
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, stats
from scripts.benchmark_finite_connection_apply_route import (
    EncodingTimings, RequestPhase, digest, differing_paths, scalar_mismatches,
)
from scripts.benchmark_pending_overhang_connections import Timings, append
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms
from tests.test_part_pending_np_connections import creation, native_prefix, owner_inputs


PATH = "/api/design/nanoparticles/gold/connection-versions"
LIGHT = "/__benchmark__/revision"
GEOMETRY = "/api/design/geometry"
CASES = ((6, 1, 0), (6, 16, 0), (16, 1, 16), (16, 16, 16))


def fixture(cells, handles, retained):
    original = native_prefix.__wrapped__()
    rows = list(original.feature_log)
    if cells == 16:
        rows[0] = rows[0].model_copy(update={"params": {**rows[0].params,
            "cells": [[row, col] for row in range(5) for col in range(1, 4)] + [[5, 1]]}})
    rows[-1] = rows[-1].model_copy(update={"params": {**rows[-1].params, "count": handles}})
    design = regenerate(original, rows, lambda: None)
    design = append(design, "nanoparticle-connection-version-create", creation(design), "candidate-create")
    design = append(design, "nanoparticle-connection-version-create",
                    creation(design, version_id="candidate-alternative", name="Alternative"), "alternative-create")
    for index in range(retained):
        design = append(design, "nanoparticle-connection-version-patch",
            {**owner_inputs(design), "name": f"Retained name {index}"}, f"retained-name-{index}")
    return design


def app():
    api = FastAPI()
    api.include_router(routes.router, prefix="/api")
    api.include_router(crud.router, prefix="/api")
    api.add_middleware(doc_context.DocContextMiddleware)
    api.add_middleware(RequestPhase)
    api.get(LIGHT)(revision_status)
    return api


def comparable_response(payload):
    value = deepcopy(payload)
    # Native command inputs, labels and recovery payloads are intentional
    # history differences. Compare every other response field verbatim.
    value["design"].pop("feature_log")
    value.pop("feature_log_entry_id", None)
    return value


def measured(client, doc, method, identity, body, locks, timers, runtime):
    headers = {"X-NADOC-Doc": doc}
    barrier, finished = Barrier(2), Event()
    light, errors = [], []

    def sample():
        try:
            barrier.wait(timeout=5)
            for _ in range(256):
                if finished.is_set():
                    break
                started = perf_counter()
                response = client.get(LIGHT, headers=headers)
                light.append({"ms": (perf_counter() - started) * 1000, "status": response.status_code})
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")

    locks.records.clear()
    timers.events.clear()
    sampler = Thread(target=sample, name="np-application-revision")
    sampler.start()
    started = perf_counter()
    try:
        barrier.wait(timeout=5)
        url = PATH + (f"/{identity}" if identity is not None else "")
        revision = state._sessions[doc].revision
        response = client.request(method, url, headers=headers,
            **({"params": {"expected_revision": revision}} if method == "DELETE" else
               {"json": {**body, "expected_revision": revision}}))
        mutated = perf_counter()
        assert response.status_code == (201 if method == "POST" else 200), response.text
        geometry = client.get(GEOMETRY, headers=headers)
        ended = perf_counter()
        assert geometry.status_code == 200, geometry.text
    finally:
        finished.set()
        sampler.join(timeout=5)
    if sampler.is_alive() or errors:
        raise RuntimeError(f"Light-request cleanup failed: {errors}")
    assert all(row["status"] == 200 for row in light), light
    held = [row for row in locks.records if row["nesting"] == 0 and row["phase"] != "light"]
    events = runtime.intervals(started, ended)
    stages = {name: {"calls": sum(event["label"] == name for event in timers.events),
        "total_ms": sum((event["end"] - event["start"]) * 1000
                        for event in timers.events if event["label"] == name)}
        for name in {event["label"] for event in timers.events}}
    return response.json(), geometry.json(), {
        "mutation_ms": (mutated - started) * 1000, "geometry_ms": (ended - mutated) * 1000,
        "combined_ms": (ended - started) * 1000, "mutation_bytes": len(response.content),
        "geometry_bytes": len(geometry.content), "lock_hold_sum_ms": sum(row["hold_ms"] for row in held),
        "lock_hold_max_ms": max((row["hold_ms"] for row in held), default=0),
        "lock_wait_sum_ms": sum(row["wait_ms"] for row in held),
        "light": stats([row["ms"] for row in light]), "light_capacity": 256,
        "light_capacity_reached": len(light) == 256, "gc_count": len(events),
        "gc_overlap_ms": overlap_ms(events, started, ended), "stages": stages}


def cold_proof(design):
    restored = Design.from_json(design.to_json())
    for row in restored.feature_log:
        row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(restored))
    started = perf_counter()
    try:
        worker.start()
        assert worker.wait(5), "Existing cold-worker allowance exceeded"
        result = worker.result()
        assert result["status"] == "verified", result
        return {"status": result["status"], "checked_commands": result["checked_commands"],
                "ms": (perf_counter() - started) * 1000}
    finally:
        worker.close()
        assert not worker.is_alive()


def cycle(client, source, mode, locks, timers, runtime, *, prove=False):
    doc = f"__e2e__np-application-benchmark-{uuid4()}"
    session = state._DesignSession(design=source.model_copy(deep=True), revision=7)
    state._sessions[doc] = session
    result = {"samples": [], "outputs": [], "cold_proof": None}
    selected = owner_inputs(source)
    actions = [("apply", "PATCH", "candidate", {"applied": True}),
        ("active-rename", "PATCH", "candidate", {"name": "Active chosen"}),
        ("pending-create", "POST", None, {"strand_id": selected["strand_id"],
            "overhang_id": selected["overhang_id"], "name": "Pending beside active"}),
        ("pending-rename", "PATCH", "context-candidate", {"name": "Pending chosen"}),
        ("pending-delete", "DELETE", "context-candidate", {}),
        ("reapply", "PATCH", "candidate", {"applied": True}),
        ("switch-conflict", "PATCH", "candidate-alternative", {"applied": True}),
        ("applied-delete", "DELETE", "candidate-alternative", {}),
        ("create-and-apply", "POST", None, {"strand_id": selected["strand_id"],
            "overhang_id": selected["overhang_id"], "name": "Together", "applied": True}),
        ("unapply", "PATCH", "created-candidate", {"applied": False})]
    original_version, original_duplex, original_relocate = (
        routes.NanoparticleConnectionVersion, kernel.Duplex, kernel.relocate_duplex)
    try:
        for number, (action, method, identity, body) in enumerate(actions):
            history_seed = str(UUID(int=9500 + number))
            duplex_id = f"application-duplex-{number}"
            created_id = "context-candidate" if action == "pending-create" else "created-candidate"
            outputs = [history_seed] + (["created-candidate", duplex_id] if method == "POST"
                                       else [duplex_id] if body.get("applied") else [])
            times = [120.0, 150.0] if method == "POST" else [150.0]
            before, revision, depth = session.design, session.revision, len(session.history)
            row_count = len(before.feature_log)
            before_digest = digest(before.model_dump(mode="json"))
            before_authoring = digest(before.model_dump(mode="json", include=AUTHORING_FIELDS))
            with ExitStack() as stack:
                stack.enter_context(patch.object(routes, "OWNED_NP_APPLICATION_ENABLED", mode == "native"))
                stack.enter_context(patch.object(recording, "uuid4", side_effect=outputs))
                stack.enter_context(patch.object(recording, "time", side_effect=times))
                stack.enter_context(patch.object(context, "uuid4", return_value=created_id))
                stack.enter_context(patch.object(context, "time", return_value=120.0))
                stack.enter_context(patch.object(routes, "NanoparticleConnectionVersion", lambda **kw:
                    original_version(**{**kw, "id": created_id, "created_at": 120.0})))
                stack.enter_context(patch.object(kernel, "Duplex", lambda **kw:
                    original_duplex(**{**kw, "id": duplex_id, "created_at": 150.0})))
                stack.enter_context(patch.object(kernel, "relocate_duplex", lambda design, duplex, **kw:
                    original_relocate(design, duplex, **{**kw, "identity_seed": history_seed})))
                response, geometry, sample = measured(client, doc, method, identity, body, locks, timers, runtime)
            current = session.design
            assert session.revision == revision + 1 and len(session.history) == depth + 1, (mode, action, "publication")
            assert len(current.feature_log) == row_count + 1, (mode, action, "history count")
            assert digest(before.model_dump(mode="json", include=AUTHORING_FIELDS)) == before_authoring, (mode, action, "source authoring mutated")
            sample["source_document_unchanged"] = digest(before.model_dump(mode="json")) == before_digest
            if mode == "native":
                assert sample["source_document_unchanged"], (mode, action, "native source history mutated")
                row = current.feature_log[-1]
                marker = "nanoparticle_pending_context_version" if action.startswith("pending-") else "nanoparticle_application_version"
                assert row.params[marker] == 1, (mode, action, "missing native inputs")
                assert dependencies(row.op_kind, row.params).known, (mode, action, "unknown native inputs")
            result["samples"].append({"action": action, **sample})
            comparison = comparable_response(response)
            result["outputs"].append({"authoring": digest(current.model_dump(mode="json", include=AUTHORING_FIELDS)),
                "response": digest(comparison), "geometry": digest(geometry),
                "response_fields": {key: digest(value) for key, value in comparison.items() if key != "design"},
                "design_fields": {key: digest(value) for key, value in comparison["design"].items()}})
            if prove and action == "create-and-apply":
                result["cold_proof"] = cold_proof(current)
        return result
    finally:
        state.drop_doc(doc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 32), default=1)
    args = parser.parse_args()
    initial_sessions, initial_callbacks = set(state._sessions), list(gc.callbacks)
    locks, timers, runtime = LockProbe(state._lock), Timings(), RuntimeProbe(phase=_PHASE.get, max_events=100_000)
    cases, failure = [], None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(state, "_lock", locks))
            stack.enter_context(runtime)
            for owner, name, label in [(pending, "_prepare_source", "source_index"),
                (application, "_select_inputs", "selection"), (application, "_restoration", "restoration_admission"),
                (application, "set_version_applied", "private_restoration"),
                (application, "_materialize", "native_materialization"),
                (state, "_snapshot_copy", "snapshot_copy"), (state, "encode_design_snapshot", "snapshot_encode"),
                (routes, "_design_response", "response_construction")]:
                timers.wrap(owner, name, label)
            stack.callback(timers.close)
            stack.enter_context(EncodingTimings(timers))
            with TestClient(app()) as client:
                for cells, handles, retained in CASES:
                    source = fixture(cells, handles, retained)
                    report = {"cells": cells, "handles": handles, "retained_rename_rows": retained,
                              "pairs": [], "completed": False}
                    cases.append(report)
                    for iteration in range(args.repeats):
                        arms = {}
                        for mode in (("native", "legacy") if iteration % 2 == 0 else ("legacy", "native")):
                            arms[mode] = cycle(client, source, mode, locks, timers, runtime,
                                               prove=mode == "native" and iteration == 0)
                        for old, new in zip(arms["legacy"]["outputs"], arms["native"]["outputs"], strict=True):
                            if old != new:
                                paths = differing_paths(old, new)
                                report["mismatch"] = scalar_mismatches(old, new, paths)
                                raise AssertionError(f"Full HTTP/geometry parity differs: {paths}")
                        report["pairs"].append({"iteration": iteration, "parity": True,
                            "digests": [digest(value) for value in arms["native"]["outputs"]],
                            **{mode: {key: value for key, value in arm.items() if key != "outputs"}
                               for mode, arm in arms.items()}})
                    report["completed"] = True
    except Exception as error:
        failure = {"type": type(error).__name__, "detail": str(error), "traceback": traceback.format_exc(limit=8)}
    cleanup = set(state._sessions) == initial_sessions and gc.callbacks == initial_callbacks
    print(json.dumps({"scope": "Ordinary NP mutation plus real geometry HTTP; no browser latency claim",
        "repeats": args.repeats, "completed": failure is None and cleanup, "failure": failure,
        "cleanup_verified": cleanup, "gc_event_capacity": runtime.max_events,
        "gc_events": len(runtime.events), "dropped_gc_events": runtime.dropped_events,
        "parity_exclusions": ["design.feature_log", "feature_log_entry_id"],
        "limits": "In-process clients and full-precision comparisons allocate; natural GC is observed, not subtracted.",
        "cases": cases}, indent=2))
    return int(failure is not None or not cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
