#!/usr/bin/env python3
"""Measure staged immutable capture/publication through the actual strict HTTP app.

Use the repository validation guard. No application lifespan, workspace files,
simulation, input-budget change or refused-operation retry is involved. Native
fixtures are privately sealed and installed before timing; durable creation and
restore are separate qualification. Public production gates remain unchanged.
"""

import argparse
from contextlib import nullcontext
import json
import resource
from threading import Event
from time import perf_counter
import tracemalloc
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs, state
from backend.api import part_immutable_evaluation as immutable, part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.part_history_proof import AUTHORING_FIELDS, digest
from scripts import benchmark_registered_batch_jobs as baseline
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 31))
    parser.add_argument("--diagnostics", action="store_true", help="Correlate parent GC without changing its policy")
    parser.add_argument("--memory", action="store_true", help="Separate allocation diagnostic; timings are not comparable")
    args = parser.parse_args()
    if args.memory and tracemalloc.is_tracing():
        raise RuntimeError("Memory measurement needs an independently owned tracing session")
    doc = f"__immutable_benchmark_{uuid4()}"
    prior_policy = policy.current_configuration()
    original = {"lock": state._lock, "capture": state.capture_design_for_evaluation,
        "commit": jobs.commit, "run": jobs._run, "decode": immutable.materialize_revision,
        "seal": immutable.prepare_revision, "gate": part_batch_evaluation.REGISTERED_BATCH_ENABLED,
        "revision_path": baseline.REVISION_PATH}
    existing_jobs = set(jobs._jobs)
    probe, completion, decode_times, seal_times = LockProbe(original["lock"]), {}, [], []
    cases, failure, cleanup_errors = [], None, []

    def measured_request(client, callback):
        interval = []

        def timed():
            interval.append(perf_counter())
            try:
                return callback()
            finally:
                interval.append(perf_counter())

        runtime = RuntimeProbe(phase=lambda: _PHASE.get()) if args.diagnostics else None
        if args.memory:
            tracemalloc.start()
        try:
            with runtime if runtime is not None else nullcontext():
                response, metrics = baseline.concurrent_request(client, {"X-NADOC-Doc": doc}, timed, probe)
            if response.is_error:
                metrics["refusal"] = response.json()
            if args.memory:
                current, peak = tracemalloc.get_traced_memory()
                metrics["parent_python_allocation"] = {"retained_bytes": current, "peak_bytes": peak}
            if runtime is not None:
                events = runtime.intervals(*interval)
                metrics["gc"] = {"overlap_ms": overlap_ms(events, *interval),
                    "events": len(events), "dropped_events": runtime.dropped_events,
                    "generations": {str(g): sum(e["generation"] == g for e in events) for g in range(3)}}
            return response, metrics
        finally:
            if args.memory:
                tracemalloc.stop()

    def measured(function, values):
        def call(*a, **kw):
            begin = perf_counter()
            try:
                return function(*a, **kw)
            finally:
                values.append((perf_counter() - begin) * 1000)
        return call

    def run(job, *a):
        done = completion.setdefault(id(job), Event())
        try:
            return original["run"](job, *a)
        finally:
            done.set()

    def await_job(client, identity):
        with jobs._lock:
            job = jobs._jobs[identity]
        done = completion.setdefault(id(job), Event())
        if not done.wait(jobs.TIME_BUDGET + 5):
            client.delete(f"{baseline.JOBS_PATH}/{identity}")
            if not done.wait(5):
                raise RuntimeError("Benchmark worker did not stop after cancellation")
            raise RuntimeError("Benchmark worker exceeded its existing deadline")
        response = client.get(f"{baseline.JOBS_PATH}/{identity}")
        response.raise_for_status()
        return response.json()["result"]

    def cleanup_jobs():
        with jobs._lock:
            owned = [(key, job) for key, job in jobs._jobs.items() if key not in existing_jobs]
            for _key, job in owned:
                completion.setdefault(id(job), Event())
                job.cancelled.set()
        stopped = True
        for _key, job in owned:
            if not completion[id(job)].wait(5):
                cleanup_errors.append("Benchmark cleanup could not confirm supervisor completion")
                stopped = False
        if stopped:
            with jobs._lock:
                for key, job in owned:
                    jobs._jobs.pop(key, None)
                    completion.pop(id(job), None)
        return stopped

    try:
        fixtures = baseline.public_envelope_fixtures()
        state._lock = probe
        state.capture_design_for_evaluation = phase_wrapper(original["capture"], "capture")
        jobs.commit = phase_wrapper(original["commit"], "publication")
        jobs._run = run
        immutable.materialize_revision = measured(original["decode"], decode_times)
        immutable.prepare_revision = measured(original["seal"], seal_times)
        part_batch_evaluation.REGISTERED_BATCH_ENABLED = True
        baseline.REVISION_PATH = "/api/design/revision"
        host.configure(policy.HostPolicyConfiguration(default_mode=prior_policy.default_mode,
            document_modes={**prior_policy.document_modes, doc: "registered_only"}))
        dispatch = StrictPartDispatch(FastAPI())

        async def observed(scope, receive, send):
            token = _PHASE.set("light_request") if scope.get("path") == baseline.REVISION_PATH else None
            try:
                await dispatch(scope, receive, send)
            finally:
                if token is not None:
                    _PHASE.reset(token)

        with TestClient(observed, headers={"X-NADOC-Doc": doc}) as client:
            for fixture in fixtures:
                report = {"name": fixture["name"], "completed": False, "samples": [], "errors": []}
                cases.append(report)
                phase = "source_preparation"
                start_decodes, start_seals = len(decode_times), len(seal_times)
                try:
                    started = perf_counter()
                    source = revisions.prepare_revision(fixture["design"])
                    source_payload = source.payload
                    report["source_sealing_ms"] = (perf_counter() - started) * 1000
                    metadata = revisions.revision_metadata(source)
                    report.update(source_bytes=metadata.payload_bytes, source_rows=metadata.history_rows,
                                  source_recovery_bytes=metadata.recovery_bytes)
                    expected_candidate = baseline.candidate(fixture)
                    expected = digest(expected_candidate.model_dump(mode="json", include=AUTHORING_FIELDS))
                    expected_rows = len(expected_candidate.feature_log) + sum(
                        len(row.children) for row in expected_candidate.feature_log
                        if row.feature_type == "routing-cluster")
                    report["expected_candidate_rows"] = expected_rows
                    del expected_candidate
                    for iteration in range(args.repeats):
                        with state._lock:
                            state._sessions[doc] = state._DesignSession(design=source, revision=1)
                        phase = "http_capture"
                        response, capture = measured_request(client,
                            lambda: client.post(baseline.JOBS_PATH,
                                json=baseline.request(fixture["design"], fixture["commands"], 1)))
                        sample = {"iteration": iteration, "capture": capture}
                        report["samples"].append(sample)
                        report["errors"].extend({"phase": phase, "detail": error} for error in capture["errors"])
                        sample["capture_status"] = response.status_code
                        response.raise_for_status()
                        identity = response.json()["job_id"]
                        phase = "worker_evaluation"
                        result = await_job(client, identity)
                        if result["status"] != "ready":
                            raise RuntimeError(f"Evaluation refused: {result.get('issues')}")
                        phase = "http_publication"
                        response, publication = measured_request(client,
                            lambda: client.post(f"{baseline.JOBS_PATH}/{identity}/commit"))
                        sample.update(publication=publication, publication_status=response.status_code)
                        report["errors"].extend({"phase": phase, "detail": error} for error in publication["errors"])
                        response.raise_for_status()
                        with state._lock:
                            session = state._sessions[doc]
                            published = session.design
                            valid = (revisions.is_prepared_revision(published) and session.revision == 2
                                and list(session.history) == [source] and not session.redo)
                        after = revisions.revision_metadata(published)
                        sample["publication_checks"] = {
                            "immutable_revision_and_undo": valid,
                            "authoring_sha256_equal": after.authoring_sha256 == expected,
                            "history_rows_equal": after.history_rows == expected_rows,
                            "source_payload_identity_preserved": source.payload is source_payload,
                        }
                        valid = all(sample["publication_checks"].values())
                        if not valid or source.payload is not source_payload:
                            raise RuntimeError("Publication did not retain exact immutable content/undo")
                        report["candidate_bytes"] = after.payload_bytes
                        report["candidate_rows"] = after.history_rows
                        sample["exact_immutable_publication"] = True
                        if iteration == 0:
                            phase = "independent_cold_verification"
                            verify = client.post(baseline.JOBS_PATH, json={"operation": "verify", "expected_revision": 2})
                            verify.raise_for_status()
                            checked = await_job(client, verify.json()["job_id"])
                            report["cold_verification"] = {key: checked.get(key) for key in ("status", "native_editable", "issues")}
                            if checked["status"] != "verified":
                                raise RuntimeError(f"Cold verification refused: {checked.get('issues')}")
                        if not cleanup_jobs():
                            raise RuntimeError("Benchmark job cleanup failed")
                    report["completed"] = not report["errors"]
                except Exception as error:
                    report["errors"].append({"phase": phase, "exception": type(error).__name__, "detail": str(error)})
                finally:
                    for stage in ("capture", "publication"):
                        rows = [sample[stage] for sample in report["samples"] if stage in sample]
                        report[stage] = baseline.summarize(rows)
                        report[stage].pop("samples", None)
                        if args.diagnostics:
                            report[stage]["gc_overlap"] = stats([row["gc"]["overlap_ms"] for row in rows])
                            report[stage]["dropped_gc_events"] = sum(row["gc"]["dropped_events"] for row in rows)
                        if args.memory:
                            report[stage]["parent_python_peak_bytes"] = [row["parent_python_allocation"]["peak_bytes"] for row in rows]
                    report["private_materialization"] = stats(decode_times[start_decodes:])
                    report["private_sealing"] = stats(seal_times[start_seals:])
                    samples = report["samples"]
                    keep = {i for i, sample in enumerate(samples) if not sample.get("exact_immutable_publication")
                            or any(sample.get(stage, {}).get("gc", {}).get("generations", {}).get("2", 0)
                                   for stage in ("capture", "publication"))}
                    for stage in ("capture", "publication"):
                        candidates = [(i, sample[stage]) for i, sample in enumerate(samples) if stage in sample]
                        for metric in (lambda row: row["http_ms"],
                                       lambda row: max(row[f"{stage}_lock_hold_ms"], default=0),
                                       lambda row: max(row["revision_http_ms"], default=0)):
                            if candidates:
                                keep.add(max(candidates, key=lambda item: metric(item[1]))[0])
                    report["sample_count"] = len(samples)
                    report["successful_publications"] = sum(sample.get("exact_immutable_publication", False) for sample in samples)
                    report["samples"] = [sample for i, sample in enumerate(samples) if i in keep]
                if not cleanup_jobs():
                    break  # Never start another case while a prior supervisor is unaccounted for.
    except Exception as error:
        failure = {"exception": type(error).__name__, "detail": str(error)}
    finally:
        cleanup_jobs()
        state.drop_doc(doc)
        host.configure(prior_policy)
        state._lock, state.capture_design_for_evaluation = original["lock"], original["capture"]
        jobs.commit, jobs._run = original["commit"], original["run"]
        immutable.materialize_revision, immutable.prepare_revision = original["decode"], original["seal"]
        part_batch_evaluation.REGISTERED_BATCH_ENABLED = original["gate"]
        baseline.REVISION_PATH = original["revision_path"]
    clean = doc not in state.revision_map() and not cleanup_errors
    passed = failure is None and clean and bool(cases) and all(case["completed"] for case in cases)
    print(json.dumps({"scope": "Staged immutable actual strict HTTP batch/verify/commit; persistence excluded",
        "repeats": args.repeats, "completed": passed, "failure": failure,
        "diagnostics": args.diagnostics, "allocation_tracing": args.memory,
        "latency_qualified": False,
        "memory_scope": "Traced parent Python allocations exclude native/worker allocations. Linux RSS high-water includes fixture creation and all prior cases; not an incremental or hard memory bound.",
        "rss_high_water_kib": {"parent": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "children": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss},
        "sample_retention": "All aggregate metrics plus refusals, incomplete publications, gen-2 GC samples and phase HTTP/lock/light maxima; other successful per-request arrays are omitted.",
        "session_cleanup_verified": clean, "cleanup_errors": cleanup_errors, "cases": cases}, indent=2))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
