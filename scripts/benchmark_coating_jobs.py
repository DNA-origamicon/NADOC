#!/usr/bin/env python3
"""Actual evaluation capture/publication and concurrent HTTP responsiveness.

Run serially under the repository validation guard. No production application
lifespan, workspace, session-cache writer or output file is opened. JSON stdout
is the only artifact. The fixed capture policy is never retried or enlarged.

Repeated capture/commit samples deliberately separate worker computation: start
uses its real capture then an intercepted submission; commit uses one separately
evaluated native candidate. Representative spawned jobs measure the complete
path and process startup independently. Intercepted submission is not evidence
of native cancellation; separate real-worker cancellation/race cases provide it.
"""

import argparse
from contextlib import contextmanager
from importlib import import_module
import json
from threading import Barrier, Event, Thread
from time import perf_counter, monotonic
from uuid import uuid4
from weakref import ref

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_evaluation_jobs as jobs, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_evaluation import evaluate
from backend.api.part_evaluation_capture import COATING_APPEND_ENABLED, COATING_PROFILE
from backend.api.part_history_verification import _slot
from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES
from backend.api.routes_feature_log import router
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_streptavidin_contract import contract_defaults
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_coating_contract import append, source_inputs


JOBS_PATH = "/api/design/features/evaluation/jobs"
REVISION_PATH = "/__benchmark__/revision"


@contextmanager
def document(identity):
    token = set_current_doc(identity)
    try:
        yield
    finally:
        reset_current_doc(token)


def fixture(mode, count, table, sources, *, removed=False):
    name = f"{mode}:{count}" + (":retained-sources-after-removal" if removed else "")
    design = create_empty_part(name, "HONEYCOMB").copy_with(input_sources=dict(table))
    design, _ = append(design, "nanoparticle-create", {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "gold", "diameter_nm": 20.0}, name + ":gold")
    base = {"_proof_version": 1, "coating_version": 1, "nanoparticle_id": "gold"}
    design, _ = append(design, "nanoparticle-patch", {**base, **contract_defaults(), **sources,
        "action": "set", "mode": mode, "footprint_nm2": 40.0,
        "spacer_nm": 0.3 if mode == "adsorption" else 4.0, "seed": 1,
        "coverage_reference": "gold_2007", "count_override": count}, name + ":set")
    actual_sites = len(design.nanoparticles[0].coating.poses)
    design, _ = append(design, "nanoparticle-patch", {**base, "action": "move", "gizmo_move": {
        "pivot": [0.0, 0.0, 0.0], "translation": [1.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0]}}, name + ":move")
    request = {"operation": "edit", "index": 2, "params": {"gizmo_move": {
        "pivot": [0.0, 0.0, 0.0], "translation": [2.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]}}}
    if removed:
        design, _ = append(design, "nanoparticle-patch", {**base, "action": "remove"}, name + ":remove")
        design, _ = append(design, "nanoparticle-delete", {"_proof_version": 1,
            "nanoparticle_version": 1, "nanoparticle_id": "gold"}, name + ":delete")
        request = {"operation": "edit", "index": 1, "params": {"seed": 2}}
    begin = perf_counter()
    prepared = evaluate(design, {"request": request, "header": {}})
    if prepared["status"] != "ready":
        raise RuntimeError(f"Native fixture candidate failed: {prepared}")
    return {"name": name, "mode": mode, "requested_sites": count, "actual_sites_before_removal": actual_sites,
        "removed": removed, "design": design, "request": request, "prepared": prepared,
        "separate_native_candidate_evaluation_ms": (perf_counter() - begin) * 1000}


def longest_history_fixture(table, sources):
    """Grow actual input rows until ordinary append/edit recovery refuses.

    Every prefix is independently proved by the existing evaluator, and every
    retained snapshot is its real encoded output. This preparation happens
    outside the measured lock samples. No recovery budget or public gate is
    changed; direct evaluation exercises the native append compiler.
    """
    case = fixture("adsorption", 64, table, sources)
    case["name"] += ":longest-editable-history"
    attempts = []
    boundary = {"flat_row_limit": 32, "cumulative_recovery_limit_bytes": MAX_RECOVERY_BYTES,
                "last_admitted_append_rows": len(case["design"].feature_log), "attempts": attempts}
    for row_count in range(len(case["design"].feature_log) + 1, 34):
        design = case["design"]
        before = design.model_dump_json()
        request = {"operation": "append", "kind": "streptavidin-coating", "expected_revision": 0,
            "params": {"action": "move", "nanoparticle_id": "gold", "gizmo_move": {
                "pivot": [0.0, 0.0, 0.0], "translation": [1.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0, 1.0]}}}
        begin = perf_counter()
        result = evaluate(design, {"request": request, "header": {
            "identity": str(uuid4()), "timestamp": "2026-10-15T12:00:00Z",
            "source_revision": 0, "source_design_id": design.id}})
        attempt = {"proposed_rows": row_count, "append_ms": (perf_counter() - begin) * 1000,
                   "append_status": result["status"], "append_issues": result.get("issues", []),
                   "source_unchanged": design.model_dump_json() == before}
        attempts.append(attempt)
        if result["status"] != "ready":
            boundary["first_refusal"] = {"operation": "append", "proposed_rows": row_count,
                "status": result["status"], "issues": result.get("issues", []),
                "candidate_returned": "candidate" in result, "source_unchanged": attempt["source_unchanged"]}
            break
        candidate = Design.model_validate(result["candidate"])
        boundary["last_admitted_append_rows"] = len(candidate.feature_log)
        attempt["retained_recovery_encoded_bytes"] = sum(
            len(row.design_snapshot_gz_b64) + len(row.post_state_gz_b64 or "") for row in candidate.feature_log)
        # Qualify an edit of the final move as well as append admission. Prefix
        # replay and rewritten suffix share the production RecoveryBudget.
        edit = {"operation": "edit", "index": len(candidate.feature_log) - 1,
            "params": {"gizmo_move": {"pivot": [0.0, 0.0, 0.0], "translation": [2.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0, 1.0]}}}
        candidate_before = candidate.model_dump_json()
        begin = perf_counter()
        prepared = evaluate(candidate, {"request": edit, "header": {}})
        elapsed = (perf_counter() - begin) * 1000
        attempt.update(edit_status=prepared["status"], edit_issues=prepared.get("issues", []),
                       edit_ms=elapsed, edit_source_unchanged=candidate.model_dump_json() == candidate_before)
        if prepared["status"] != "ready":
            boundary["first_refusal"] = {"operation": "edit-after-append", "proposed_rows": row_count,
                "status": prepared["status"], "issues": prepared.get("issues", []),
                "candidate_returned": "candidate" in prepared,
                "source_unchanged": attempt["edit_source_unchanged"]}
            break
        case = {**case, "design": candidate, "request": edit, "prepared": prepared,
                "separate_native_candidate_evaluation_ms": elapsed}
    boundary["longest_editable_rows"] = len(case["design"].feature_log)
    refusal = boundary.get("first_refusal", {})
    boundary["expected_atomic_refusal"] = (refusal.get("status") == "unverified"
        and not refusal.get("candidate_returned", True) and refusal.get("source_unchanged", False)
        and any(issue.get("code") == "command_limit" for issue in refusal.get("issues", [])))
    return case, boundary


def retained_draft_fixture(case, shape):
    """Load-admitted stale metadata must remain cheap and proof-independent.

    This is a portable proposal schema boundary, not evidence that its proposed
    input values are a valid coating edit. Native command admission is separate.
    """
    from backend.core.part_repair_draft import RepairDraft

    def proposal(size):
        value = list(range(size)) if shape == "nodes" else "x" * size
        return RepairDraft.model_validate({"version": 1, "draft_id": "retained-proposal",
            "generation": 0, "base_design_id": case["design"].id,
            "base": {"version": 1, "root_sha256": "0" * 64,
                     "commands_sha256": "0" * 64, "sources_sha256": "0" * 64},
            "repair_version": 1, "actions": [{"action": "set_input",
                "feature_id": f"unresolved-{index}", "parameter_path": ["diameter_nm"],
                "expected_old": value, "value": value} for index in range(64)]})

    lower, upper = 0, 1000
    while lower < upper:
        middle = (lower + upper + 1) // 2
        try:
            proposal(middle)
        except ValueError:
            upper = middle - 1
        else:
            lower = middle
    draft = proposal(lower)
    return {**case, "name": case["name"] + f":retained-draft-{shape}",
            "design": case["design"].copy_with(repair_draft=draft)}


def concurrent_request(client, headers, callback, probe):
    """One actual HTTP operation plus bounded concurrent revision requests."""
    baseline_start = perf_counter()
    client.get(REVISION_PATH, headers=headers).raise_for_status()
    baseline_ms = (perf_counter() - baseline_start) * 1000
    first_record = len(probe.records)
    gate, finished = Barrier(2), Event()
    requests, errors = [], []

    def sample():
        gate.wait(timeout=5)
        for _ in range(256):
            if finished.is_set():
                break
            begin = perf_counter()
            try:
                client.get(REVISION_PATH, headers=headers).raise_for_status()
            except Exception as error:
                errors.append(str(error))
                break
            requests.append({"start": begin, "end": perf_counter()})

    sampler = Thread(target=sample, name="coating-job-revision-probe")
    sampler.start()
    try:
        gate.wait(timeout=5)
        begin = perf_counter()
        response = callback()
        elapsed = (perf_counter() - begin) * 1000
    finally:
        finished.set()
        sampler.join(5)
    if sampler.is_alive():
        raise RuntimeError("Revision probe did not stop")
    records = probe.records[first_record:]
    locking = [row for row in records if row["phase"] in {"capture", "publication"} and row["nesting"] == 0]
    return response, {"http_ms": elapsed, "baseline_revision_http_ms": baseline_ms,
        "revision_http_ms": [(row["end"] - row["start"]) * 1000 for row in requests],
        "revision_requests_overlapping_capture_or_publication": sum(any(
            request["start"] <= lock["ended"] and lock["entered"] <= request["end"] for lock in locking)
            for request in requests),
        "capture_lock_hold_ms": [row["hold_ms"] for row in records if row["phase"] == "capture"],
        "capture_lock_wait_ms": [row["wait_ms"] for row in records if row["phase"] == "capture"],
        "publication_lock_hold_ms": [row["hold_ms"] for row in records if row["phase"] == "publication"],
        "publication_lock_wait_ms": [row["wait_ms"] for row in records if row["phase"] == "publication"],
        "revision_lock_wait_ms": [row["wait_ms"] for row in records if row["phase"] == "light_request"],
        "revision_lock_hold_ms": [row["hold_ms"] for row in records if row["phase"] == "light_request"],
        "errors": errors}


def reset_source(doc, design):
    with document(doc):
        state.load_design(design)
        return state.revision()


def remove_job(identity):
    if identity:
        with jobs._lock:
            jobs._jobs.pop(identity, None)


def repeated_case(client, doc, case, repeats, probe, snapshots):
    headers, capture_rows, commit_rows = {"X-NADOC-Doc": doc}, [], []
    design = case["design"]
    original_submit = jobs._submit
    held = []

    def capture_only(job, _captured, _operation):
        # Admission/capture/HTTP are real; deliberately no process is launched.
        held.append(job)

    jobs._submit = capture_only
    try:
        for _ in range(repeats):
            revision = reset_source(doc, design)
            identity = None
            try:
                response, measured = concurrent_request(client, headers, lambda: client.post(JOBS_PATH,
                    headers=headers, json={**case["request"], "expected_revision": revision}), probe)
                measured.update(http_status=response.status_code, response=response.json())
                if response.status_code == 202:
                    identity = response.json()["job_id"]
                    # Exercise cancellation of the intercepted registry entry;
                    # this says nothing about native process reaping.
                    cancelled = client.delete(f"{JOBS_PATH}/{identity}", headers=headers)
                    measured["intercepted_cancel_status"] = cancelled.status_code
                elif response.status_code != 413:
                    measured["errors"].append(f"Unexpected capture response {response.status_code}: {response.text}")
                capture_rows.append(measured)
            finally:
                if held:
                    held.pop()
                    _slot.release()  # There is intentionally no supervisor in this phase.
                remove_job(identity)

            # Independently measure the real commit endpoint against the same
            # separately evaluated candidate, regardless of capture refusals.
            # This is a publication cost sample, not an admitted end-to-end job.
            revision = reset_source(doc, design)
            identity = str(uuid4())
            with jobs._lock:
                jobs._jobs[identity] = jobs.EvaluationJob(doc, ref(design), revision,
                    created=monotonic(), status="complete", admitted_operation="edit",
                    result=dict(case["prepared"]))
            first_snapshot = len(snapshots)
            try:
                response, measured = concurrent_request(client, headers,
                    lambda: client.post(f"{JOBS_PATH}/{identity}/commit", headers=headers), probe)
                measured.update(http_status=response.status_code, response=response.json(),
                                snapshot_ms=snapshots[first_snapshot:])
                with document(doc):
                    current = state.get_or_404()
                    with state._lock:
                        undo = state._session().history[-1] if state._session().history else None
                    measured["correct_publication"] = (response.status_code == 200
                        and state.revision() == revision + 1 and state.undo_depth() == 1 and state.redo_depth() == 0
                        and undo is not design and undo is not None and undo.model_dump_json() == design.model_dump_json()
                        and current.input_sources == design.input_sources
                        and current.repair_draft is design.repair_draft
                        and [row.id for row in current.feature_log] == [row.id for row in design.feature_log])
                if response.status_code != 200:
                    measured["errors"].append(f"Commit rejected: {response.text}")
                commit_rows.append(measured)
            finally:
                remove_job(identity)
    finally:
        jobs._submit = original_submit

    def summarize(rows):
        fields = ("revision_http_ms", "capture_lock_hold_ms", "capture_lock_wait_ms",
                  "publication_lock_hold_ms", "publication_lock_wait_ms", "revision_lock_wait_ms", "revision_lock_hold_ms")
        return {"http": stats([row["http_ms"] for row in rows]),
            "baseline_revision_http": stats([row["baseline_revision_http_ms"] for row in rows]),
            **{key.removesuffix("_ms"): stats([value for row in rows for value in row[key]]) for key in fields},
            "overlapping_revision_requests": sum(row["revision_requests_overlapping_capture_or_publication"] for row in rows),
            "samples": rows}

    return {key: case[key] for key in ("name", "mode", "requested_sites", "actual_sites_before_removal", "removed",
        "separate_native_candidate_evaluation_ms")} | {
        "repeats": repeats, "source_json_bytes": len(design.model_dump_json().encode()),
        "candidate_json_bytes": len(json.dumps(case["prepared"]["candidate"]).encode()),
        "retained_sources": len(design.input_sources), "history_rows": len(design.feature_log),
        "retained_draft_json_bytes": (len(design.repair_draft.model_dump_json().encode())
                                      if design.repair_draft is not None else 0),
        "retained_recovery_encoded_bytes": sum(len(row.design_snapshot_gz_b64) + len(row.post_state_gz_b64 or "")
                                              for row in design.feature_log),
        "capture_refusals": sum(row["http_status"] == 413 for row in capture_rows),
        "correct_publications": sum(row["correct_publication"] for row in commit_rows),
        "publication_snapshot": stats([value for row in commit_rows for value in row["snapshot_ms"]]),
        "capture_without_worker": summarize(capture_rows), "commit_prepared_candidate": summarize(commit_rows)}


def actual_job(client, doc, case, mode="complete"):
    """Real spawned lifecycle, including reaping, observed separately from repeats."""
    headers = {"X-NADOC-Doc": doc}
    revision = reset_source(doc, case["design"])
    original_submit, original_worker = jobs._submit, jobs.EvaluationWorker
    started, done = Event(), Event()
    threads, timings = [], {}
    identity = None

    class ObservedWorker(original_worker):
        def __init__(self, *args, **kwargs):
            begin = perf_counter()
            super().__init__(*args, **kwargs)
            timings["parent_worker_constructor_ms"] = (perf_counter() - begin) * 1000

        def start(self):
            begin = perf_counter()
            super().start()
            timings["process_start_call_ms"] = (perf_counter() - begin) * 1000
            started.set()

        def result(self):
            begin = perf_counter()
            result = super().result()
            timings["parent_result_decode_ms"] = (perf_counter() - begin) * 1000
            return result

    def submit(*args):
        def run():
            try:
                jobs._run(*args)
            finally:
                done.set()
        thread = Thread(target=run, name="coating-live-benchmark-supervisor", daemon=False)
        threads.append(thread)
        thread.start()

    jobs._submit, jobs.EvaluationWorker = submit, ObservedWorker
    begin = perf_counter()
    try:
        response = client.post(JOBS_PATH, headers=headers, json={**case["request"], "expected_revision": revision})
        timings["start_http_ms"] = (perf_counter() - begin) * 1000
        if response.status_code != 202:
            return {"mode": mode, "start_http_status": response.status_code, "response": response.json(), **timings}
        identity = response.json()["job_id"]
        path = f"{JOBS_PATH}/{identity}"
        if mode != "complete":
            # Wait for an actual spawned child, not an intercepted submission.
            if not started.wait(10):
                raise RuntimeError("Representative worker did not reach process start")
            stop_start = perf_counter()
            if mode == "cancel":
                client.delete(path, headers=headers).raise_for_status()
            else:
                with document(doc):
                    source, current_revision = state.get_design_with_revision()
                    state.set_design(source.model_copy(deep=True), expected_revision=current_revision, expected_source=source)
            if not done.wait(10):
                raise RuntimeError("Cancelled/stale worker was not reaped promptly")
            timings["stop_to_supervisor_reaped_ms"] = (perf_counter() - stop_start) * 1000
        elif not done.wait(jobs.TIME_BUDGET + 10):
            raise RuntimeError("Representative worker exceeded its existing deadline")
        timings["start_to_supervisor_reaped_ms"] = (perf_counter() - begin) * 1000
        polled = client.get(path, headers=headers)
        polled.raise_for_status()
        result = polled.json()
        commit_start = perf_counter()
        committed = client.post(path + "/commit", headers=headers)
        timings["commit_http_ms"] = (perf_counter() - commit_start) * 1000
        with document(doc):
            final_revision, undo = state.revision(), state.undo_depth()
            current = state.get_or_404()
            if mode == "complete" and case["request"]["operation"] == "verify":
                source_guard_correct = (final_revision == revision and undo == 0
                    and current.model_dump_json() == case["design"].model_dump_json())
            elif mode == "complete":
                source_guard_correct = (final_revision == revision + 1 and undo == 1
                    and current.input_sources == case["design"].input_sources
                    and [row.id for row in current.feature_log] == [row.id for row in case["design"].feature_log])
            else:
                source_guard_correct = (final_revision == revision + (mode == "source_changed")
                    and undo == int(mode == "source_changed")
                    and current.model_dump_json() == case["design"].model_dump_json())
        free = _slot.acquire(blocking=False)
        if free:
            _slot.release()
        return {"mode": mode, "start_http_status": 202, "poll": result,
            "commit_http_status": committed.status_code, "commit": committed.json(),
            "initial_revision": revision, "final_revision": final_revision, "undo_depth": undo,
            "source_guard_correct": source_guard_correct,
            "shared_admission_released_after_reaping": free, **timings}
    finally:
        if identity is not None:
            with jobs._lock:
                job = jobs._jobs.get(identity)
                if job is not None:
                    job.cancelled.set()
        for thread in threads:
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError("Benchmark supervisor remains alive")
        remove_job(identity)
        jobs._submit, jobs.EvaluationWorker = original_submit, original_worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--long-history-only", action="store_true",
                        help="Qualify only the additional real history/recovery boundary")
    parser.add_argument("--pending-drafts", action="store_true",
                        help="Include node/byte-bound portable draft metadata at the retained-history boundary")
    args = parser.parse_args()
    if not 30 <= args.repeats <= 60:
        parser.error("Use 30..60 samples per fixed boundary; smaller runs are not qualification")
    for module in ("numpy", "scipy.linalg", "scipy.optimize", "scipy.spatial.transform",
                   "scipy.spatial.distance", "scipy.interpolate"):
        import_module(module)
    from threadpoolctl import threadpool_limits

    table, sources, sizes = source_inputs()
    doc = f"__benchmark_coating_jobs_{uuid4()}__"
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(router, prefix="/api")

    @app.get(REVISION_PATH)
    def revision():
        token = _PHASE.set("light_request")
        try:
            return {"revision": state.revision()}
        finally:
            _PHASE.reset(token)

    original_lock, original_capture, original_publish, original_snapshot = (
        state._lock, state.capture_design_for_evaluation, state.set_design, state._snapshot_copy)
    probe, snapshots = LockProbe(original_lock), []

    def snapshot(design):
        begin = perf_counter()
        try:
            return original_snapshot(design)
        finally:
            snapshots.append((perf_counter() - begin) * 1000)

    state._lock = probe
    state.capture_design_for_evaluation = phase_wrapper(original_capture, "capture")
    state.set_design = phase_wrapper(original_publish, "publication")
    state._snapshot_copy = snapshot
    try:
        with threadpool_limits(limits=1):
            fixtures = [] if args.long_history_only else [fixture(mode, count, table, sources)
                for mode in ("adsorption", "biotin_tether") for count in (1, 64)]
            if not args.long_history_only:
                fixtures.append(fixture("adsorption", 1, table, sources, removed=True))
            longest, history_boundary = longest_history_fixture(table, sources)
            fixtures.append(longest)
            if args.pending_drafts:
                fixtures.extend(retained_draft_fixture(longest, shape) for shape in ("nodes", "bytes"))
            with TestClient(app) as client:
                startup = actual_job(client, doc, {"design": create_empty_part("Empty worker startup", "HONEYCOMB"),
                                                   "request": {"operation": "verify"}})
                cases = [repeated_case(client, doc, case, args.repeats, probe, snapshots) for case in fixtures]
                live = [{"case": case["name"], **actual_job(client, doc, case)} for case in fixtures]
                races = [actual_job(client, doc, fixtures[0], mode) for mode in ("cancel", "source_changed")]
    finally:
        try:
            state.drop_doc(doc)
        finally:
            state._lock = original_lock
            state.capture_design_for_evaluation = original_capture
            state.set_design = original_publish
            state._snapshot_copy = original_snapshot
    leaked = doc in state.revision_map()
    print(json.dumps({"scope": "Actual HTTP evaluation capture and prepared-candidate publication with lock/snapshot probes; separate real spawned lifecycle/cancellation/race observations",
        "repeats_per_boundary": args.repeats, "fixed_coating_profile": dict(COATING_PROFILE),
        "ordinary_verification_and_edit_limits_unchanged": True, "session_cleanup_verified": not leaked,
        "public_append_enabled": COATING_APPEND_ENABLED, "source_files": sizes,
        "long_history_boundary": history_boundary,
        "measurement_notes": [
            "Repeated start samples intercept submission after real capture; they exclude process startup, replay and solver work.",
            "Repeated commit samples use one separately natively evaluated candidate and measure decode, independent transport digests, source snapshot and publication.",
            "Commit samples are independent of capture refusals; they must not be reported as successful end-to-end jobs.",
            "Representative live jobs use real spawned workers and unchanged admission/deadline/transport policies.",
            "The long-history fixture is grown through actual native append and edit evaluation until the first unchanged-budget refusal; no output geometry or recovery bytes are fabricated.",
            "Optional retained-draft cases approach the portable proposal schema's node/byte bounds. Stale unresolved proposals remain metadata, not proof inputs or valid command edits.",
            "The empty-root worker baseline includes child imports and trivial proof, with no native molecular build. Parent constructor/start-call timings are also reported separately.",
            "Lock probes add Python overhead; no forced sleeps create contention. HTTP includes ASGI scheduling.",
            "Zero observed overlap is not evidence of zero contention. A 100 ms cooperative allowance is not a wall-time ceiling.",
            "Capture refusals remain evidence; no fallback, retry or claim of public latency qualification is made."],
        "empty_root_worker_startup_baseline": startup,
        "cases": cases, "real_spawned_jobs": live, "real_worker_races": races}, indent=2))
    bad_samples = any(case["correct_publications"] != args.repeats or any(row["errors"]
        for stage in ("capture_without_worker", "commit_prepared_candidate") for row in case[stage]["samples"]) for case in cases)
    bad_live = any(row["start_http_status"] not in {202, 413} or (row["start_http_status"] == 202 and (
        row["commit_http_status"] != 200 or not row["shared_admission_released_after_reaping"]
        or not row["source_guard_correct"])) for row in live)
    bad_races = any(row["start_http_status"] not in {202, 413} or (row["start_http_status"] == 202 and (
        row["commit_http_status"] != 409 or not row["shared_admission_released_after_reaping"]
        or not row["source_guard_correct"])) for row in races)
    bad_startup = (startup["start_http_status"] != 202 or startup["commit_http_status"] != 409
        or startup["poll"]["result"]["status"] != "verified" or not startup["source_guard_correct"])
    return int(leaked or bad_samples or bad_live or bad_races or bad_startup
               or not history_boundary["expected_atomic_refusal"]
               or any(not row["source_unchanged"] or not row.get("edit_source_unchanged", True)
                      for row in history_boundary["attempts"]))


if __name__ == "__main__":
    raise SystemExit(main())
