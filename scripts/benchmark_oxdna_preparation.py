#!/usr/bin/env python3
"""Diagnostic A/B of the gated owned oxDNA input boundary, without simulation.

Run serially under the repository validation guard, e.g.
``just validate-safe uv run python -m scripts.benchmark_oxdna_preparation``.
The real HTTP handler, protocol assembly and AnyIO thread handoff run. Geometry,
sequence analysis, fingerprints, engine probes, lineage and writers are bounded
in-memory substitutes. There is no production lifespan, workspace or native job.
Stdout JSON is the only artifact. This is not rollout or physical qualification.

Fixtures are literal eight-base DNA plus legacy history, not external designs.
Opaque recovery strings are actually allocated and retained but never decoded.
The 64/256-row cases diagnose history cost; they do not expand capture limits.
No retries, forced collections, GC policy changes or synthetic sleeps occur.
"""

import argparse
from collections import Counter
from contextlib import ExitStack
import gc
import json
from pathlib import Path
from threading import Barrier, Event, Thread
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import oxdna_preparation_capture as capture, routes_oxdna as routes, state
from backend.api.doc_context import DocContextMiddleware
from backend.api.part_revision_status import revision_status
from backend.core import models as m, oxdna_staleness, project_revisions, streptavidin
from backend.core import oxdna_preparation_inputs as inputs
from backend.core.oxdna_job import OxdnaJob
from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES
from backend.physics import oxdna_mobile_gold, oxdna_protein
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, stats
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms


POST_PATH = "/api/oxdna/jobs"
REVISION_PATH = "/api/design/revision"
WORKSPACE = Path("/dev/null/nadoc-oxdna-benchmark")  # Cannot become a directory.
BODY = {"backend": "CPU", "seed": 123, "autostart": False}
GC_EVENTS_PER_CASE = 4096
CONSUMERS = {"coating", "mobile", "protein", "sequence", "complementarity", "lineage",
             "geometry", "order", "fingerprint", "log-position", "writer"}


def source(rows, recovery_bytes):
    helix = m.Helix(id="h_XY_0_0", axis_start=m.Vec3(x=0, y=0, z=0),
        axis_end=m.Vec3(x=0, y=0, z=2.38), length_bp=8)
    strand = m.Strand(id="dna", sequence="ACGTACGT", domains=[m.Domain(
        helix_id=helix.id, start_bp=0, end_bp=7, direction=m.Direction.FORWARD)])
    history = [m.SnapshotLogEntry(id=f"legacy-{index}", op_kind="overhang-bulk",
        label="Legacy", params={"legacy": {"values": [index]}}) for index in range(rows)]
    if recovery_bytes:
        history[0].design_snapshot_gz_b64 = "x" * recovery_bytes
    return m.Design(id="benchmark-dna", helices=[helix], strands=[strand],
        metadata=m.DesignMetadata(name="Owned preparation diagnostic", tags=["archive"]),
        annotations=[m.Annotation(text="Keep this archive", refs=[{
            "kind": "strand", "id": "dna", "notes": ["retained"]}])],
        visibility_state=m.VisibilityState(hidden_base_keys=["h_XY_0_0:0:forward"]),
        feature_log=history, feature_log_cursor=len(history) - 1)


class Probes:
    def reset(self):
        self.consumers, self.effects, self.timing = [], [], []

    def consume(self, name, design, result=None):
        self.consumers.append((name, design))
        return result

    def timed(self, function, phase):
        def wrapped(*args, **kwargs):
            token = _PHASE.set(phase)
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                self.timing.append({"phase": phase, "ms": (perf_counter() - started) * 1000})
                _PHASE.reset(token)
        return wrapped

    def lineage(self, workspace, design, kind, _identity):
        assert workspace == WORKSPACE and kind == "oxdna"
        self.effects.append("lineage")
        return self.consume("lineage", design,
            SimpleNamespace(project_id=design.id, revision_id="benchmark-revision"))

    def save(self, _job, workspace):
        assert workspace == WORKSPACE
        self.effects.append("save")

    def writer(self, design, geometry, _job, workspace, _specs, **_kwargs):
        assert geometry == [] and workspace == WORKSPACE
        self.effects.append("writer")
        return self.consume("writer", design, {})


def forbidden(*_args, **_kwargs):
    raise RuntimeError("Benchmark reached an unreviewed filesystem, engine or job path")


def instrument(stack, observed):
    replacements = [
        (routes, "find_oxdna", lambda: "/unexecuted/oxDNA"),
        (routes, "oxdna_supports_physics_v3", lambda *_args: True),
        (routes, "_workspace", lambda: WORKSPACE),
        (routes, "start_job", forbidden),
        (OxdnaJob, "job_dir", forbidden), (OxdnaJob, "list_jobs", forbidden),
        (OxdnaJob, "save", lambda job, workspace: observed.save(job, workspace)),
        (routes, "count_undefined_bases",
            lambda design, **_kwargs: observed.consume("sequence", design, (0, 8))),
        (routes, "designed_pair_complementarity",
            lambda design: observed.consume("complementarity", design, (4, 4))),
        (streptavidin, "require_coating_simulation_support",
            lambda design, *_args: observed.consume("coating", design)),
        (oxdna_mobile_gold, "has_mobile_gold", lambda design: observed.consume("mobile", design, False)),
        (oxdna_protein, "has_proteins", lambda design: observed.consume("protein", design, False)),
        (routes, "_seed_geometry", lambda design: observed.consume("geometry", design, [])),
        (routes, "_strand_nucleotide_order", lambda design: observed.consume("order", design, list(range(8)))),
        (oxdna_staleness, "oxdna_design_fingerprint",
            lambda design: observed.consume("fingerprint", design, "v4:benchmark-only")),
        (oxdna_staleness, "effective_feature_log_position",
            lambda design: observed.consume("log-position", design, design.feature_log_cursor)),
        (project_revisions, "record_simulation_revision", observed.lineage),
        (routes, "prepare_oxdna_job", observed.writer),
        (capture, "capture_current", observed.timed(capture.capture_current, "capture")),
        (capture, "require_current", observed.timed(capture.require_current, "origin_guard")),
    ]
    for owner, name, replacement in replacements:
        stack.enter_context(patch.object(owner, name, replacement))


def revision():
    token = _PHASE.set("light_request")
    try:
        return revision_status()
    finally:
        _PHASE.reset(token)


def light_request(client, doc, design_id):
    # Submission starts outside ASGI so queue/GIL delays remain in the sample.
    started = perf_counter()
    response = client.get(REVISION_PATH, headers={"X-NADOC-Doc": doc})
    ended = perf_counter()
    expected = {"doc_id": doc, "design_id": design_id, "revision": 7, "has_design": True}
    return {"start": started, "end": ended, "ms": (ended - started) * 1000,
            "correct": response.status_code == 200 and response.json() == expected}


def attempt(client, docs, original, before, projected, enabled, observed, locks, runtime):
    observed.reset()
    routes.OWNED_DNA_PREPARATION_ENABLED = enabled
    baseline = light_request(client, docs[0], original.id)
    locks.records.clear()
    gate, finished = Barrier(2), Event()
    requests, errors = [], []

    def sample():
        try:
            gate.wait(timeout=5)
            for index in range(64):
                if finished.is_set():
                    break
                other = bool(index % 2)
                row = light_request(client, docs[int(other)], "other-dna" if other else original.id)
                requests.append({**row, "document": "other" if other else "source"})
        except Exception as error:
            errors.append(f"Light request: {type(error).__name__}: {error}")

    sampler = Thread(target=sample, name="oxdna-preparation-light-http", daemon=True)
    sampler.start()
    response = None
    started = ended = perf_counter()
    try:
        gate.wait(timeout=5)
        started = perf_counter()
        response = client.post(POST_PATH, json=BODY, headers={"X-NADOC-Doc": docs[0]})
    except Exception as error:
        errors.append(f"Preparation: {type(error).__name__}: {error}")
    finally:
        ended = perf_counter()
        finished.set()
        sampler.join(timeout=5)
    if sampler.is_alive():
        raise RuntimeError("Light-request sampler failed to stop; refuse further measurements")
    records = list(locks.records)
    events = runtime.intervals(started, ended)
    status = None if response is None else response.status_code
    payload = {} if response is None else response.json()
    detail = payload.get("detail")
    code = detail.get("code") if type(detail) is dict else None
    one_input = not observed.consumers or all(design is observed.consumers[0][1] for _, design in observed.consumers)
    consumer_parity = one_input and (not observed.consumers
        or observed.consumers[0][1].model_dump(mode="json") == projected)
    private = not observed.consumers or (observed.consumers[0][1] is not original
        and observed.consumers[0][1].annotations[0].refs is not original.annotations[0].refs
        and observed.consumers[0][1].feature_log[0] is not original.feature_log[0])
    calls = Counter(item["phase"] for item in observed.timing)
    if status == 200:
        correct = (payload.get("status") == "queued" and payload.get("n_nucleotides") == 8
            and {name for name, _ in observed.consumers} == CONSUMERS
            and observed.effects == ["lineage", "save", "writer", "save"]
            and consumer_parity and one_input and (not enabled or private)
            and calls == ({"capture": 1, "origin_guard": 1} if enabled else {}))
    else:
        correct = (enabled and status == 413 and code == "oxdna_input_capture_limit"
            and not observed.consumers and not observed.effects and calls == {"capture": 1})
    with locks.wrapped:
        session = state._sessions[docs[0]]
        source_unchanged = (session.design is original and session.revision == 7
            and not session.history and not session.redo and original.model_dump(mode="json") == before)
    correct = correct and source_unchanged and baseline["correct"] and all(row["correct"] for row in requests) and not errors
    overlaps = sum(any(row["start"] <= item["ended"] and item["entered"] <= row["end"]
                       for item in records if item["phase"] == "capture") for row in requests)
    row = {"arm": "enabled" if enabled else "disabled", "http_status": status, "error_code": code,
        "http_ms": (ended - started) * 1000, "baseline_revision_ms": baseline["ms"],
        "capture_ms": [item["ms"] for item in observed.timing if item["phase"] == "capture"],
        "origin_guard_ms": [item["ms"] for item in observed.timing if item["phase"] == "origin_guard"],
        "capture_hold_ms": [item["hold_ms"] for item in records if item["phase"] == "capture"],
        "capture_wait_ms": [item["wait_ms"] for item in records if item["phase"] == "capture"],
        "guard_hold_ms": [item["hold_ms"] for item in records if item["phase"] == "origin_guard"],
        "light_wait_ms": [item["wait_ms"] for item in records if item["phase"] == "light_request"],
        "light_requests": [{"document": item["document"], "ms": item["ms"], "correct": item["correct"]}
                           for item in requests], "capture_overlapping_requests": overlaps,
        "gc_overlap_ms": overlap_ms(events, started, ended), "gc_generations": [item["generation"] for item in events],
        "counters": dict(calls), "effects": dict(Counter(observed.effects)),
        "source_unchanged": source_unchanged, "consumer_parity": consumer_parity,
        "one_input": one_input, "owned_input": private if enabled and status == 200 else None,
        "correct": correct, "errors": errors}
    # Random host job identity and timestamp are the only expected A/B variation.
    comparable = {key: value for key, value in payload.items() if key not in {"job_id", "created_at"}}
    observed.reset()  # Do not retain previous owned Design graphs across attempts.
    return row, comparable


def measure(client, docs, name, row_count, recovery_bytes, repeats, observed, locks, runtime, result):
    samples, pairs = [], []
    # Install the case before fallible setup so earlier samples survive an
    # unexpected fixture, request, parity or cleanup failure.
    result.update(case=name, history_rows=row_count, recovery_bytes=recovery_bytes,
        expected_enabled_byte_refusal=recovery_bytes > MAX_RECOVERY_BYTES,
        samples=samples, correct=False)
    original = source(row_count, recovery_bytes)
    before = original.model_dump(mode="json")
    projected = original.without_reference_geometry().model_dump(mode="json")
    with locks.wrapped:
        state._sessions[docs[0]] = state._DesignSession(design=original, revision=7)
    for index in range(repeats):
        pair = {}
        for enabled in ((False, True) if index % 2 == 0 else (True, False)):
            row, comparable = attempt(client, docs, original, before, projected,
                enabled, observed, locks, runtime)
            if recovery_bytes > MAX_RECOVERY_BYTES and enabled and row["http_status"] != 413:
                row["correct"] = False
                row["errors"].append("Oversized recovery was not refused")
            samples.append({"pair": index, **row})
            pair[enabled] = (row, comparable)
        if all(pair[enabled][0]["http_status"] == 200 for enabled in (False, True)):
            pairs.append({"pair": index, "response_equal": pair[False][1] == pair[True][1],
                "http_delta_ms": pair[True][0]["http_ms"] - pair[False][0]["http_ms"]})
    arms = {}
    for arm in ("disabled", "enabled"):
        selected = [row for row in samples if row["arm"] == arm]
        arms[arm] = {"http": stats([row["http_ms"] for row in selected]),
            "baseline_light_http": stats([row["baseline_revision_ms"] for row in selected]),
            "status_counts": dict(Counter(str(row["http_status"]) for row in selected)),
            **{key: stats([value for row in selected for value in row[key]]) for key in (
                "capture_ms", "origin_guard_ms", "capture_hold_ms", "capture_wait_ms", "guard_hold_ms", "light_wait_ms")},
            "light_http": stats([item["ms"] for row in selected for item in row["light_requests"]]),
            "correct_attempts": sum(row["correct"] for row in selected)}
    result.update({"arms": arms, "matched_success_http_delta": stats([row["http_delta_ms"] for row in pairs]),
        "response_equal_pairs": sum(row["response_equal"] for row in pairs), "matched_pairs": len(pairs),
        "correct": all(row["correct"] for row in samples) and all(row["response_equal"] for row in pairs)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=31)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 64:
        parser.error("Use 1..64 alternating pairs")
    if routes.OWNED_DNA_PREPARATION_ENABLED is not False:
        parser.error("The ordinary route must remain disabled before this diagnostic")
    docs = (f"__oxdna_benchmark_{uuid4()}__", f"__oxdna_light_{uuid4()}__")
    other = source(1, 0)
    other.id = "other-dna"
    original_lock, original_gate = state._lock, routes.OWNED_DNA_PREPARATION_ENABLED
    callbacks, gc_enabled, gc_threshold = tuple(gc.callbacks), gc.isenabled(), gc.get_threshold()
    locks, observed = LockProbe(original_lock), Probes()
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")
    app.get(REVISION_PATH)(revision)
    cases, failure = [], None
    try:
        with original_lock:
            state._sessions[docs[1]] = state._DesignSession(design=other, revision=7)
        with ExitStack() as stack:
            stack.enter_context(patch.object(state, "_lock", locks))
            instrument(stack, observed)
            client = stack.enter_context(TestClient(app))
            for name, rows, size in (("tiny", 1, 0), ("history-64", 64, 0),
                    ("history-256", 256, 0), ("opaque-recovery-near-8MB", 1, 7_990_000),
                    ("opaque-recovery-over-8MB", 1, MAX_RECOVERY_BYTES + 1)):
                result = {}
                cases.append(result)
                with RuntimeProbe(phase=_PHASE.get, max_events=GC_EVENTS_PER_CASE) as runtime:
                    try:
                        measure(client, docs, name, rows, size, args.repeats, observed, locks, runtime, result)
                    finally:
                        result["gc_probe"] = {"capacity": runtime.max_events,
                            "observed_events": len(runtime.events), "dropped_events": runtime.dropped_events}
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    finally:
        routes.OWNED_DNA_PREPARATION_ENABLED = original_gate
        with original_lock:
            for doc in docs:
                state._sessions.pop(doc, None)
    cleanup = (state._lock is original_lock and routes.OWNED_DNA_PREPARATION_ENABLED is original_gate
        and not any(doc in state._sessions for doc in docs) and tuple(gc.callbacks) == callbacks
        and gc.isenabled() == gc_enabled and gc.get_threshold() == gc_threshold)
    report = {"diagnostic_only": True, "rollout_qualified": False, "physical_receipts_complete": False,
        "scope": "Actual HTTP and threaded handoff; in-memory geometry/lineage/writer substitutes",
        "pairs_per_case": args.repeats, "limits": {"nodes": inputs.MAX_NODES, "bytes": inputs.MAX_BYTES,
            "seconds": inputs.CAPTURE_SECONDS, "recovery_bytes": MAX_RECOVERY_BYTES},
        "natural_gc": True, "retries": 0, "forced_collections": 0,
        "gc_probe_capacity_per_case": GC_EVENTS_PER_CASE,
        "gc_probe_observed_events": sum(row.get("gc_probe", {}).get("observed_events", 0) for row in cases),
        "gc_probe_dropped_events": sum(row.get("gc_probe", {}).get("dropped_events", 0) for row in cases),
        "cleanup_verified": cleanup, "failure": failure,
        "notes": ["All actual recovery strings remain opaque; no physical package or native engine is produced.",
            "Light request timestamps are taken by an external thread before HTTP submission, including queue/GIL delay.",
            "No overlap is not evidence of no contention; sampling is capped at 64 reads per preparation.",
            "GC overlap is correlation, not a subtraction from observed latency. Instrumentation adds overhead.",
            "A fresh bounded GC probe is installed for each case; observed/dropped counts disclose incomplete correlation.",
            "Capture refusals remain in samples; matched-success deltas exclude refused pairs explicitly.",
            "Exit status checks diagnostic correctness and cleanup, not a latency target or rollout permission."],
        "cases": cases}
    print(json.dumps(report, indent=2))
    return int(failure is not None or not cleanup or len(cases) != 5 or any(not row["correct"] for row in cases))


if __name__ == "__main__":
    raise SystemExit(main())
