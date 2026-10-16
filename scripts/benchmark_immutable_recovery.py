#!/usr/bin/env python3
"""Memory-only near-cap cold recovery diagnostic; no durable publication.

Run serially under the repository validation guard. Only the persistence read is
substituted: real strict HTTP admission, preparation, worker proof, qualification,
two-result retention and cancellation run unchanged. No cache files, lifespan,
simulations, retries, raised limits or GC policy changes. stdout is compact JSON.
"""

import argparse
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from threading import Event, current_thread, get_ident
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4
from weakref import ref

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_evaluation_jobs as jobs, session_cache, state
from backend.api import part_immutable_recovery as recovery, part_immutable_revision as revisions
from backend.api import part_immutable_recovery_inputs as recovery_inputs
from backend.api import part_immutable_recovery_worker as recovery_worker
from backend.api import part_publication_host as host, part_publication_policy as policy
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_cache import CacheManifest, StoredRevision
from backend.api.part_immutable_persistence import StrictPersistence
from backend.api.part_immutable_storage import MAX_RETAINED_REVISION_BYTES
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.part_history_contract import create_empty_part
from backend.core.models import Design
from scripts import benchmark_registered_batch_jobs as baseline
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_immutable_part_jobs import retention_stress_fixture
from scripts.benchmark_process_rss import ProcessRSSSampler
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms


RECOVERY_PATH = "/api/design/recovery/jobs"
TARGET_BYTES = 15_900_000
PHASE_CAPACITY = 256
READ_CAPACITY = 6 * 256  # Two starts, two completion waits and two result releases.
REPORTED_READS = 32


class PreparationPhases:
    """Benchmark-only nested intervals; retain no model, bytes or arguments."""

    def __init__(self, docs):
        self.documents = {doc: ordinal + 1 for ordinal, doc in enumerate(docs)}
        self.stack = ContextVar("recovery_benchmark_phase_stack", default=())
        self.active = False
        self.reset()

    def reset(self):
        self.events, self.reads = [], []
        self.started = self.dropped = self.read_started = self.read_dropped = 0

    def wrap(self, function, phase):
        def measured(*args, **kwargs):
            if not self.active:
                return function(*args, **kwargs)
            if self.started >= PHASE_CAPACITY:
                self.dropped += 1
                return function(*args, **kwargs)
            self.started += 1
            parents = self.stack.get()
            frame = {"id": self.started, "children_seconds": 0.}
            token = self.stack.set((*parents, frame))
            phase_token = _PHASE.set(phase)
            started, error = perf_counter(), None
            try:
                return function(*args, **kwargs)
            except BaseException as caught:
                error = type(caught).__name__
                raise
            finally:
                ended = perf_counter()
                elapsed = ended - started
                if parents:
                    parents[-1]["children_seconds"] += elapsed
                self.events.append({"id": frame["id"], "parent": parents[-1]["id"] if parents else None,
                    "phase": phase, "thread": get_ident(), "start": started, "end": ended,
                    "inclusive_ms": elapsed * 1000,
                    "exclusive_ms": max(0., elapsed - frame["children_seconds"]) * 1000,
                    "error": error})
                _PHASE.reset(phase_token)
                self.stack.reset(token)
        return measured

    def observe_get(self, function):
        def measured(client, url, *args, **kwargs):
            if (not self.active or current_thread().name != "batch-light-http-probe"
                    or url != baseline.REVISION_PATH):
                return function(client, url, *args, **kwargs)
            if self.read_started >= READ_CAPACITY:
                self.read_dropped += 1
                return function(client, url, *args, **kwargs)
            self.read_started += 1
            started, status, error = perf_counter(), None, None
            try:
                response = function(client, url, *args, **kwargs)
                status = response.status_code
                return response
            except BaseException as caught:
                error = type(caught).__name__
                raise
            finally:
                ended = perf_counter()
                self.reads.append({"start": started, "end": ended, "ms": (ended - started) * 1000,
                    "document": self.documents.get(kwargs.get("headers", {}).get("X-NADOC-Doc")),
                    "status_code": status, "error": error})
        return measured

    def report(self, runtime):
        events = sorted(self.events, key=lambda row: row["start"])
        reads = list(self.reads)
        enriched = []
        for event in events:
            overlaps = [row for row in reads if row["start"] <= event["end"] and row["end"] >= event["start"]]
            enriched.append({**event, "gc_overlap_ms": overlap_ms(runtime.events, event["start"], event["end"]),
                "overlapping_reads": len(overlaps),
                "max_overlapping_read_ms": max((row["ms"] for row in overlaps), default=None)})
        slowest = sorted(sorted(reads, key=lambda row: row["ms"], reverse=True)[:REPORTED_READS],
                         key=lambda row: row["start"])
        return {"clock": "time.perf_counter monotonic seconds, shared by all parent threads",
            "phase_capacity": PHASE_CAPACITY, "phase_started": self.started,
            "phase_completed": len(events), "phase_dropped": self.dropped,
            "read_capacity": READ_CAPACITY, "read_started": self.read_started,
            "read_completed": len(reads), "read_dropped": self.read_dropped,
            "read_report_limit": REPORTED_READS, "read_report_omitted": max(0, len(reads) - REPORTED_READS),
            "phases": enriched,
            "slowest_reads": [{**row, "overlapping_phase_ids": [event["id"] for event in events
                if row["start"] <= event["end"] and row["end"] >= event["start"]]} for row in slowest]}


def instrument_parent(stack, phases):
    """Trace parent boundaries only; the fresh child keeps original preparation."""
    for owner, name, phase in (
        (recovery, "reserve_input", "raw_reservation"),
        (recovery_worker, "encode_input", "frame_admission"),
        (recovery, "supervise", "worker_supervision"),
        (recovery_worker.RecoveryWorker, "result", "parent_result_validation"),
        (recovery_worker.RecoveryWorker, "take_revision", "parent_revision_handoff"),
    ):
        stack.enter_context(patch.object(owner, name, phases.wrap(getattr(owner, name), phase)))

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("Recovery unexpectedly decoded or re-prepared a Design in the parent")

    for owner, name in ((recovery_inputs, "prepare_stored"), (revisions, "prepare_revision"),
            (revisions, "_decoded_exact"), (revisions, "_canonical_payload"), (revisions, "digest"),
            (Design, "model_validate"), (Design, "model_validate_json")):
        stack.enter_context(patch.object(owner, name, forbidden))
    stack.enter_context(patch.object(TestClient, "get", phases.observe_get(TestClient.get)))


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
        "run": recovery._run, "start": recovery.start,
        "worker_start": recovery_worker.RecoveryWorker.start,
        "worker_wait": recovery_worker.RecoveryWorker.wait,
        "worker_close": recovery_worker.RecoveryWorker.close,
        "revision_path": baseline.REVISION_PATH}
    probe = LockProbe(original["lock"])
    completion, worker_records, worker_index, read_ids = {}, [], {}, {}
    samples, cleanup_errors, failure, fixture = [], [], None, None
    active_rss = None
    configured = False
    admitted_idle = False
    ready_refs = []
    prior_jobs = dict(jobs._jobs)
    phases, phase_patches = PreparationPhases(docs), ExitStack()
    traced_run = phases.wrap(original["run"], "recovery_supervisor")
    traced_worker_start = phases.wrap(original["worker_start"], "worker_start")
    traced_worker_close = phases.wrap(original["worker_close"], "worker_cleanup")

    def forbidden(*_args, **_kwargs):
        raise RuntimeError("Memory diagnostic attempted disk access or durable publication")

    def run(job):
        done = completion.setdefault(id(job), Event())
        try:
            return traced_run(job)
        finally:
            done.set()

    def record_worker(worker):
        record = worker_index.get(id(worker))
        if record is None or record["owner"]() is not worker:
            # Never retain a worker or bound method: each owns a near-16MB ticket.
            record = {"owner": ref(worker), "buffers": [part.name for part in worker._buffers],
                "started": False, "exitcode": None, "observed_reaped": False,
                "closed": False, "process_closed": False, "close_error": None}
            worker_records.append(record)
            worker_index[id(worker)] = record
        return record

    def construct(ticket):
        worker = recovery_worker.RecoveryWorker(ticket)
        record_worker(worker)
        return worker

    def worker_start(worker):
        record = record_worker(worker)
        traced_worker_start(worker)
        record["started"] = True
        if active_rss is not None:
            active_rss.register_child(worker._process.pid)

    def worker_wait(worker, seconds):
        finished = original["worker_wait"](worker, seconds)
        if finished:
            record = record_worker(worker)
            record["exitcode"] = worker._process.exitcode
            record["observed_reaped"] = not worker._process.is_alive() and record["exitcode"] is not None
        return finished

    def worker_close(worker):
        record = record_worker(worker)
        try:
            return traced_worker_close(worker)
        except BaseException as error:
            record["close_error"] = type(error).__name__
            raise
        finally:
            record["closed"] = worker._closed
            record["process_closed"] = worker._process_closed

    def worker_cleanup(records):
        evidence = []
        for record in records:
            unlinked = True
            for name in record["buffers"]:
                try:
                    leaked = SharedMemory(name=name)
                except FileNotFoundError:
                    continue
                else:
                    leaked.close()
                    unlinked = False
            evidence.append({key: record[key] for key in ("started", "exitcode", "observed_reaped",
                "closed", "process_closed", "close_error")}
                | {"buffers_unlinked": unlinked, "worker_released": record["owner"]() is None})
        return evidence

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

    def check_candidate(doc, identity, payload, expected_authoring):
        with jobs._lock:
            candidate = jobs._jobs[identity].candidate
            ready_refs.append(ref(candidate))
        metadata = revisions.revision_metadata(candidate)
        if (candidate.payload != payload or candidate.payload is payload or id(candidate.payload) != read_ids.get(doc)
                or metadata.authoring_sha256 != expected_authoring):
            raise RuntimeError("Recovered candidate did not retain its exact independently allocated read bytes")
        return len(candidate.payload)

    def measure(client, doc, callback, runtime):
        begin = perf_counter()
        operation = {}

        def timed_callback():
            operation["start"] = perf_counter()
            try:
                return callback()
            finally:
                operation["end"] = perf_counter()

        response, metrics = baseline.concurrent_request(client, {"X-NADOC-Doc": doc}, timed_callback, probe)
        end = perf_counter()
        events = runtime.intervals(begin, end)
        metrics.update(gc_overlap_ms=overlap_ms(events, begin, end),
            gc_generations={str(g): sum(e["generation"] == g for e in events) for g in range(3)},
            light_sample_cap_reached=len(metrics["revision_http_ms"]) == 256,
            status_code=response.status_code, operation_interval=operation)
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
        instrument_parent(phase_patches, phases)
        phase_patches.enter_context(patch.object(recovery, "RecoveryWorker",
            phases.wrap(construct, "worker_construction")))
        phase_patches.enter_context(patch.object(recovery_worker.RecoveryWorker, "start", worker_start))
        phase_patches.enter_context(patch.object(recovery_worker.RecoveryWorker, "wait", worker_wait))
        phase_patches.enter_context(patch.object(recovery_worker.RecoveryWorker, "close", worker_close))
        # Constructor only resolves an existing directory. Every disk entry is
        # tripwired; no fake lease is minted and commit is intentionally absent.
        owner = StrictPersistence(Path.cwd())
        owner.cache._directory = forbidden
        owner.bind_for_publication = forbidden

        def read_pending(doc):
            if doc not in docs:
                raise RuntimeError("Substituted read received an unowned document")
            independent = memoryview(payload).tobytes()
            if independent is payload or doc in read_ids:
                raise RuntimeError("Recovery read reused its fixture or repeated a document read")
            read_ids[doc] = id(independent)
            return StoredRevision(CacheManifest(doc, len(independent), fixture["payload_sha256"]), independent, None)

        owner.read_pending = phases.wrap(read_pending, "read_allocation")
        session_cache._strict_persistence = owner
        state._lock = probe
        recovery.start = phase_wrapper(original["start"], "capture")
        recovery._run = run
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
                phases.reset()
                phases.active = True
                read_ids.clear()
                sample = {"iteration": iteration, "completed": False, "jobs": [], "releases": []}
                samples.append(sample)
                first_lock, first_worker = len(probe.records), len(worker_records)
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
                                doc, identity, payload, fixture["authoring_sha256"])
                            item["retains_exact_read_allocation"] = True
                        rss.set_phase("ready")
                        with jobs._lock:
                            current = list(jobs._jobs.values())
                            sample["ready_count"] = sum(job.candidate is not None for job in current)
                            sample["distinct_ready_payloads"] = len({id(job.candidate.payload) for job in current})
                            sample["distinct_read_allocations"] = len(set(read_ids.values()))
                        del current
                        if (sample["ready_count"] != jobs.MAX_RESULTS or sample["distinct_ready_payloads"] != 2
                                or sample["distinct_read_allocations"] != 2):
                            raise RuntimeError("Actual two-slot catalog did not retain two independent near-cap candidates")
                        for doc, identity in identities:
                            response, timing = measure(client, doc, lambda: client.delete(
                                f"{baseline.JOBS_PATH}/{identity}", headers={"X-NADOC-Doc": doc}), runtime)
                            sample["releases"].append(timing)
                            response.raise_for_status()
                        if any(value() is not None for value in ready_refs):
                            raise RuntimeError("Cancellation retained an owned candidate")
                        sample["worker_cleanup"] = worker_cleanup(worker_records[first_worker:])
                        if any(not (row["closed"] and row["process_closed"] and row["observed_reaped"]
                                   and row["buffers_unlinked"] and row["worker_released"])
                               for row in sample["worker_cleanup"]):
                            raise RuntimeError("Completed recovery retained a worker or leaked transport resources")
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
                            state_lock_hold=stats([v["hold_ms"] for v in probe.records[first_lock:]]),
                            phase_trace=phases.report(runtime))
                        phases.active = False
                        active_rss = None
                if not cleanup_jobs():
                    raise RuntimeError("Result catalog cleanup failed")
                for doc in docs:
                    state.drop_doc(doc)
    except Exception as error:
        failure = {"exception": type(error).__name__, "detail": str(error)[:4096]}
    finally:
        try:
            cleanup_jobs()
        finally:
            phases.active = False
            phase_patches.close()
        worker_evidence = worker_cleanup(worker_records)
        if any(not (row["closed"] and row["process_closed"] and row["buffers_unlinked"]
                    and row["worker_released"]) for row in worker_evidence):
            cleanup_errors.append("Owned worker or shared-memory buffers remain retained/unclosed")
        for doc in [*docs, background]:
            state.drop_doc(doc)
        if configured:
            host.configure(previous_policy)
        state._lock, session_cache._strict_persistence = original["lock"], original["owner"]
        recovery._run, recovery.start = original["run"], original["start"]
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
            "child_preparation_proof_and_handoff_wait": summarize_metrics([item["completion_wait"] for item in items
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
    print(json.dumps({"scope": "Independent in-memory reads; actual child preparation/proof, parent observation, two-slot retention and cancellation",
        "repeats": args.repeats, "completed": passed, "failure": failure, "fixture": fixture,
        "source_sha256": {str(Path(module.__file__).relative_to(Path.cwd())):
            sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (recovery, recovery_worker, recovery_inputs, revisions)},
        "benchmark_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "durable_commit_qualified": False, "public_availability_qualified": False,
        "latency_qualified": False, "memory_qualified": False,
        "completion_meaning": "Correctness and cleanup only; three cycles are diagnostic, and even 30 require review against declared targets and sampling gaps.",
        "memory_scope": "Scoped parent plus explicitly owned child RSS; baseline includes four near-8MB background handles and one near-16MB fixture. Each read adds an independent allocation retained by its exact ready candidate. Worker tracking is weak only. Gaps may miss peaks; shared pages double-count. No heap guarantee.",
        "storage_seam": "read_pending copies fixture bytes via memoryview.tobytes into actual bounded StoredRevision with no lease; read identity tracked by integer only; disk access/publication tripwired; no cache files",
        "historical_comparison": "Initial/phase reports at be6f284a remain unchanged. Their parent preparation and shared substituted input differ from this worker preparation and independent-read allocation; this is not an exact A/B memory comparison.",
        "phase_instrumentation": {
            "scope": "Parent read allocation, reservation, framing, worker construction/launch/result/cleanup, and revision handoff only. Parent Design decode/prepare/canonicalization/digest are tripwired after fixture setup; fresh spawned child preparation is unchanged and untraced.",
            "capacity_per_cycle": PHASE_CAPACITY, "read_capacity_per_cycle": READ_CAPACITY,
            "reported_slowest_reads_per_cycle": REPORTED_READS,
            "clock": "time.perf_counter process-wide monotonic seconds; phase/read/operation intervals align across parent threads.",
            "attribution_limits": [
                "Intervals include scheduling/GIL/GC delay and instrumentation overhead, not CPU attribution; no time is subtracted from user-observed latency.",
                "Inclusive phases nest and must not be added. Exclusive time subtracts immediate traced children only, not all helper work.",
                "Raw reservation includes input hash and context checks. Read-allocation time is an in-memory copy, not filesystem I/O.",
                "Worker supervision includes child preparation/proof wait plus traced launch, result and cleanup. Worker-start is launch only; no child CPU/phase attribution is claimed.",
                "Frame admission is also called within parent revision handoff. Nested intervals must not be counted twice.",
                "Only parent natural GC is observed; child GC is not sampled. Weak worker records store scalar close/reap evidence and buffer names, never tickets or bytes.",
                "Read intervals begin outside ASGI inside the external sampler's TestClient.get call; they exclude the tiny caller-to-wrapper dispatch overhead.",
                "All bounded observed reads contribute overlap counts; only the slowest32 intervals are printed. Overlap identifies correlation, not causation or exclusive blocking responsibility.",
                "Dropped/unfinished counters disclose incomplete traces; current scopes, five-second deadline, fixtures and GC policy are unchanged."]},
        "targets": {"recovery_deadline_seconds_unchanged": recovery.TIME_BUDGET,
            "measured_cycles_for_qualification": 30, "state_lock_p95_ms": 1, "state_lock_max_ms": 5,
            "start_p95_ms": 10, "start_max_ms": 100, "concurrent_start_p95_ms": 10,
            "concurrent_start_max_ms": 100, "rss_increment_bytes": 256 * 1024 * 1024},
        "cleanup": not cleanup_errors, "cleanup_errors": cleanup_errors,
        "worker_lifecycle": worker_evidence,
        "summary_by_recovery_ordinal": summary, "completed_result_release": release_summary,
        "samples": samples}, separators=(",", ":")))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
