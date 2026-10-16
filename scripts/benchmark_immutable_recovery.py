#!/usr/bin/env python3
"""Memory-only near-cap cold recovery diagnostic; no durable publication.

Run serially under the repository validation guard. Only the persistence read is
substituted: real strict HTTP admission, preparation, worker proof, qualification,
two-result retention and cancellation run unchanged. No cache files, lifespan,
simulations, retries, raised limits or GC policy changes. stdout is compact JSON.
"""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from threading import Event
from time import perf_counter
from uuid import uuid4
from weakref import ref

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_evaluation_jobs as jobs, session_cache, state
from backend.api import part_immutable_recovery as recovery, part_immutable_revision as revisions
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_cache import CacheManifest, StoredRevision
from backend.api.part_immutable_persistence import StrictPersistence
from backend.api.part_immutable_storage import MAX_RETAINED_REVISION_BYTES
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.part_verification_worker import VerificationWorker
from backend.core.part_history_contract import create_empty_part
from scripts import benchmark_registered_batch_jobs as baseline
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_immutable_part_jobs import retention_stress_fixture
from scripts.benchmark_process_rss import ProcessRSSSampler
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms


RECOVERY_PATH = "/api/design/recovery/jobs"
TARGET_BYTES = 15_900_000


def fixtures():
    seed = baseline.candidate(baseline.prepare("recovery-memory-seed",
        create_empty_part("Recovery memory diagnostic", "HONEYCOMB"), baseline.gold_commands("recovery", 1)))
    padded = seed.model_copy(deep=True)
    row = padded.feature_log[0]
    row.design_snapshot_gz_b64 = row.post_state_gz_b64 = ""
    base = len(revisions.prepare_revision(padded).payload)
    # Corrupt saved recovery remains opaque: each ASCII control costs one
    # recovery byte but six canonical JSON bytes. It never becomes proof input.
    count = (TARGET_BYTES - base) // 6
    row.design_snapshot_gz_b64 = "\x01" * count
    sealed = revisions.prepare_revision(padded)
    metadata = revisions.revision_metadata(sealed)
    if not TARGET_BYTES - 6 < len(sealed.payload) <= TARGET_BYTES:
        raise RuntimeError("Escaped recovery fixture missed its declared full-byte target")
    retained = retention_stress_fixture({"design": seed})["design"]
    handles = [revisions.prepare_revision(retained) for _ in range(4)]
    total = sum(len(item.payload) for item in handles)
    if not MAX_RETAINED_REVISION_BYTES * .99 < total <= MAX_RETAINED_REVISION_BYTES:
        raise RuntimeError("Background retention no longer approaches the unchanged allowance")
    if len({id(item.payload) for item in handles}) != 4:
        raise RuntimeError("Background handles unexpectedly share their payload allocation")
    return sealed.payload, handles, {"payload_bytes": len(sealed.payload),
        "payload_sha256": sha256(sealed.payload).hexdigest(), "recovery_bytes": metadata.recovery_bytes,
        "control_characters": count, "history_rows": metadata.history_rows,
        "authoring_sha256": metadata.authoring_sha256, "retained_source_undo_bytes": total}


def summarize_metrics(rows):
    if not rows:
        return {"count": 0}
    value = baseline.summarize(rows)
    value.pop("samples")
    value.update(errors=[error for row in rows for error in row["errors"]],
        light_sample_caps=sum(row["light_sample_cap_reached"] for row in rows),
        gc_overlap=stats([row["gc_overlap_ms"] for row in rows]))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 31))
    args = parser.parse_args()
    suffix = uuid4().hex
    docs = [f"__recovery_memory_{suffix}_{i}" for i in range(2)]
    background = f"__recovery_memory_{suffix}_background"
    previous_policy = policy.current_configuration()
    original = {"lock": state._lock, "owner": session_cache._strict_persistence,
        "run": recovery._run, "start": recovery.start, "prepare": recovery.prepare_stored,
        "worker_start": VerificationWorker.start, "revision_path": baseline.REVISION_PATH}
    probe = LockProbe(original["lock"])
    completion, worker_records, preparation_times = {}, [], []
    samples, cleanup_errors, failure, fixture = [], [], None, None
    active_rss = None
    configured = False
    admitted_idle = False
    ready_refs = []
    prior_jobs = dict(jobs._jobs)

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("Memory diagnostic attempted disk access or durable publication")

    def prepare(*args, **kwargs):
        begin = perf_counter()
        try:
            return original["prepare"](*args, **kwargs)
        finally:
            preparation_times.append((perf_counter() - begin) * 1000)

    def run(job):
        done = completion.setdefault(id(job), Event())
        try:
            return phase_wrapper(original["run"], "preparation")(job)
        finally:
            done.set()

    def worker_start(worker):
        worker_records.append((worker, [part.name for part in worker._buffers]))
        original["worker_start"](worker)
        if active_rss is not None:
            active_rss.register_child(worker._process.pid)

    def wait_ready(client, doc, identity):
        with jobs._lock:
            job = jobs._jobs[identity]
        if not completion.setdefault(id(job), Event()).wait(recovery.TIME_BUDGET + 5):
            job.cancelled.set()
            raise RuntimeError("Recovery supervisor did not finish within its unchanged deadline plus cleanup")
        response = client.get(f"{baseline.JOBS_PATH}/{identity}", headers={"X-NADOC-Doc": doc})
        response.raise_for_status()
        if response.json().get("result", {}).get("status") != "ready":
            raise RuntimeError(f"Recovery refused: {response.json()}")
        return response

    def check_candidate(identity, payload, expected_authoring):
        with jobs._lock:
            candidate = jobs._jobs[identity].candidate
            ready_refs.append(ref(candidate))
        metadata = revisions.revision_metadata(candidate)
        if (candidate.payload != payload or candidate.payload is payload
                or metadata.authoring_sha256 != expected_authoring):
            raise RuntimeError("Recovered candidate did not preserve independently proved exact bytes")
        return len(candidate.payload)

    def measure(client, doc, callback, runtime):
        begin = perf_counter()
        response, metrics = baseline.concurrent_request(client, {"X-NADOC-Doc": doc}, callback, probe)
        end = perf_counter()
        events = runtime.intervals(begin, end)
        metrics.update(gc_overlap_ms=overlap_ms(events, begin, end),
            gc_generations={str(g): sum(e["generation"] == g for e in events) for g in range(3)},
            light_sample_cap_reached=len(metrics["revision_http_ms"]) == 256,
            status_code=response.status_code)
        if response.is_error:
            metrics["refusal"] = response.json()
        if metrics["errors"]:
            raise RuntimeError(f"Concurrent revision read failed: {metrics['errors']}")
        return response, metrics

    @contextmanager
    def measured_rss(sample):
        sampler = ProcessRSSSampler()
        try:
            with sampler:
                yield sampler
        finally:
            # Keep memory evidence even when a genuine capture/proof refuses.
            sample["rss"] = sampler.report()

    def cleanup_jobs():
        with jobs._lock:
            owned = [(key, job) for key, job in jobs._jobs.items() if key not in prior_jobs]
            for _key, job in owned:
                job.cancelled.set()
        stopped = True
        for _key, job in owned:
            if not completion.setdefault(id(job), Event()).wait(recovery.TIME_BUDGET + 5):
                cleanup_errors.append("Owned recovery supervisor did not stop")
                stopped = False
        if stopped:
            with jobs._lock:
                for key, job in owned:
                    jobs._discard_candidate(job)
                    jobs._jobs.pop(key, None)
                    completion.pop(id(job), None)
        return stopped

    try:
        if prior_jobs or not _slot.acquire(blocking=False):
            raise RuntimeError("Diagnostic requires an otherwise idle evaluation catalog and worker slot")
        _slot.release()
        admitted_idle = True
        began = perf_counter()
        payload, handles, fixture = fixtures()
        fixture["preparation_ms"] = (perf_counter() - began) * 1000
        # Constructor only resolves an existing directory. Every disk entry is
        # tripwired; no fake lease is minted and commit is intentionally absent.
        owner = StrictPersistence(Path.cwd())
        owner.cache._directory = forbidden
        owner.bind_for_publication = forbidden

        def read_pending(doc):
            if doc not in docs:
                raise RuntimeError("Substituted read received an unowned document")
            return StoredRevision(CacheManifest(doc, len(payload), fixture["payload_sha256"]), payload, None)

        owner.read_pending = read_pending
        session_cache._strict_persistence = owner
        state._lock = probe
        recovery.start = phase_wrapper(original["start"], "capture")
        recovery._run, recovery.prepare_stored = run, prepare
        VerificationWorker.start = worker_start
        baseline.REVISION_PATH = "/api/design/revision"
        host.configure(policy.HostPolicyConfiguration(default_mode=previous_policy.default_mode,
            document_modes={**previous_policy.document_modes,
                **dict.fromkeys([*docs, background], "registered_only")}))
        configured = True
        with state._lock:
            state._sessions[background] = state._DesignSession(design=handles[-1], revision=1)
            state._sessions[background].history.extend(handles[:-1])
        dispatch = StrictPartDispatch(FastAPI())

        async def observed(scope, receive, send):
            token = _PHASE.set("light_request") if scope.get("path") == baseline.REVISION_PATH else None
            try:
                await dispatch(scope, receive, send)
            finally:
                if token is not None:
                    _PHASE.reset(token)

        with TestClient(observed) as client:
            for iteration in range(args.repeats):
                sample = {"iteration": iteration, "completed": False, "jobs": [], "releases": []}
                samples.append(sample)
                first_lock, first_prepare = len(probe.records), len(preparation_times)
                begin = perf_counter()
                with measured_rss(sample) as rss, RuntimeProbe(phase=lambda: _PHASE.get()) as runtime:
                    active_rss = rss
                    try:
                        identities = []
                        for doc in docs:
                            rss.set_phase("start")
                            started = perf_counter()
                            response, timing = measure(client, doc, lambda: client.post(RECOVERY_PATH,
                                json={"expected_revision": 0}, headers={"X-NADOC-Doc": doc}), runtime)
                            item = {"start": timing}
                            sample["jobs"].append(item)
                            response.raise_for_status()
                            identity = response.json()["job_id"]
                            identities.append((doc, identity))
                            rss.set_phase("worker")
                            try:
                                _response, waiting = measure(client, doc,
                                    lambda: wait_ready(client, doc, identity), runtime)
                                item["completion_wait"] = waiting
                            finally:
                                item["complete_ms"] = (perf_counter() - started) * 1000
                            item["retained_candidate_bytes"] = check_candidate(
                                identity, payload, fixture["authoring_sha256"])
                        rss.set_phase("ready")
                        with jobs._lock:
                            current = list(jobs._jobs.values())
                            sample["ready_count"] = sum(job.candidate is not None for job in current)
                            sample["distinct_ready_payloads"] = len({id(job.candidate.payload) for job in current})
                        del current
                        if sample["ready_count"] != jobs.MAX_RESULTS or sample["distinct_ready_payloads"] != 2:
                            raise RuntimeError("Actual two-slot catalog did not retain two independent near-cap candidates")
                        for doc, identity in identities:
                            response, timing = measure(client, doc, lambda: client.delete(
                                f"{baseline.JOBS_PATH}/{identity}", headers={"X-NADOC-Doc": doc}), runtime)
                            sample["releases"].append(timing)
                            response.raise_for_status()
                        if any(value() is not None for value in ready_refs):
                            raise RuntimeError("Cancellation retained an owned candidate")
                        with state._lock:
                            if any(state._sessions[doc].design is not None or state._sessions[doc].revision != 0
                                   or state._sessions[doc].history for doc in docs):
                                raise RuntimeError("Memory-only recovery unexpectedly published a document")
                            held = state._sessions[background]
                            if held.design is not handles[-1] or list(held.history) != handles[:-1]:
                                raise RuntimeError("Background retained source/undo changed")
                        sample["completed"] = True
                    finally:
                        end = perf_counter()
                        events = runtime.intervals(begin, end)
                        sample.update(elapsed_ms=(end - begin) * 1000, gc_events=len(events),
                            gc_overlap_ms=overlap_ms(events, begin, end), gc_dropped=runtime.dropped_events,
                            preparation_ms=preparation_times[first_prepare:],
                            state_lock_hold=stats([v["hold_ms"] for v in probe.records[first_lock:]]))
                        active_rss = None
                if not cleanup_jobs():
                    raise RuntimeError("Result catalog cleanup failed")
                for doc in docs:
                    state.drop_doc(doc)
    except Exception as error:
        failure = {"exception": type(error).__name__, "detail": str(error)[:4096]}
    finally:
        cleanup_jobs()
        for worker, names in worker_records:
            if not worker._closed or not worker._process_closed:
                cleanup_errors.append("Owned worker was not closed and reaped")
            for name in names:
                try:
                    leaked = SharedMemory(name=name)
                except FileNotFoundError:
                    continue
                else:
                    leaked.close()
                    cleanup_errors.append("Owned shared-memory buffer remains linked")
        for doc in [*docs, background]:
            state.drop_doc(doc)
        if configured:
            host.configure(previous_policy)
        state._lock, session_cache._strict_persistence = original["lock"], original["owner"]
        recovery._run, recovery.start = original["run"], original["start"]
        recovery.prepare_stored, VerificationWorker.start = original["prepare"], original["worker_start"]
        baseline.REVISION_PATH = original["revision_path"]
        if jobs._jobs != prior_jobs or any(value() is not None for value in ready_refs):
            cleanup_errors.append("Catalog or candidate ownership did not return to its initial state")
        if admitted_idle:
            if _slot.acquire(blocking=False):
                _slot.release()
            else:
                cleanup_errors.append("Native worker slot was not released")
    passed = failure is None and not cleanup_errors and len(samples) == args.repeats and all(s["completed"] for s in samples)
    summary = []
    for ordinal in range(2):
        items = [sample["jobs"][ordinal] for sample in samples if len(sample["jobs"]) > ordinal]
        summary.append({"ordinal": ordinal + 1,
            "start": summarize_metrics([item["start"] for item in items]),
            "preparation_and_worker_wait": summarize_metrics([item["completion_wait"] for item in items
                                                             if "completion_wait" in item]),
            "job_complete": stats([item["complete_ms"] for item in items if "complete_ms" in item])})
    release_summary = summarize_metrics([row for sample in samples for row in sample["releases"]])
    for sample in samples:
        for row in [*[item[key] for item in sample["jobs"] for key in ("start", "completion_wait") if key in item],
                    *sample["releases"]]:
            # Keep every request's totals/refusal/GC and distribution; do not
            # print hundreds of successful scalar-read samples per operation.
            for key in list(row):
                if key.endswith("_ms") and isinstance(row[key], list):
                    row[key.removesuffix("_ms") + "_stats"] = stats(row.pop(key))
    print(json.dumps({"scope": "In-memory substituted read; actual recovery preparation, worker proof, two-slot retention and cancellation",
        "repeats": args.repeats, "completed": passed, "failure": failure, "fixture": fixture,
        "durable_commit_qualified": False, "public_availability_qualified": False,
        "memory_scope": "Scoped parent plus explicitly owned child RSS; baseline includes four near-8MB background handles and one shared near-16MB in-memory input. Gaps may miss peaks; shared pages double-count. No heap guarantee.",
        "storage_seam": "read_pending returns actual bounded StoredRevision bytes with no lease; disk access and publication tripwired; no cache files",
        "targets": {"recovery_deadline_seconds_unchanged": recovery.TIME_BUDGET,
            "measured_cycles_for_qualification": 30, "state_lock_p95_ms": 1, "state_lock_max_ms": 5,
            "start_p95_ms": 10, "start_max_ms": 100, "concurrent_start_p95_ms": 10,
            "concurrent_start_max_ms": 100, "rss_increment_bytes": 256 * 1024 * 1024},
        "cleanup": not cleanup_errors, "cleanup_errors": cleanup_errors,
        "summary_by_recovery_ordinal": summary, "completed_result_release": release_summary,
        "samples": samples}, separators=(",", ":")))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
