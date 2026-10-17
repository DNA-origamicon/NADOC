#!/usr/bin/env python3
"""Measure the actual pinned caDNAno HTTP route and shared-lock intervals.

Run serially under the repository validation guard. The app has no production
lifespan, sessions stay in one isolated document, and stdout JSON is the only
output. No workspace files, browser artifacts or physical jobs are created.
"""

import argparse
from contextvars import ContextVar
import json
import math
from pathlib import Path
from statistics import median
from threading import Barrier, Event, Thread, local
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_part_cadnano_import as routes, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.core.part_history_contract import create_empty_part


_PHASE = ContextVar("cadnano_route_benchmark_phase", default="other")
IMPORT_PATH = "/api/design/features/import/cadnano"
REVISION_PATH = "/__benchmark__/revision"


class LockProbe:
    """Delegate the real RLock; observe without adding sleeps or lock scope."""

    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.stack = local()
        self.records = []

    def acquire(self, *args, **kwargs):
        started = perf_counter()
        acquired = self.wrapped.acquire(*args, **kwargs)
        if acquired:
            entered = perf_counter()
            stack = getattr(self.stack, "entries", None)
            if stack is None:
                stack = self.stack.entries = []
            stack.append((started, entered, _PHASE.get()))
        return acquired

    def release(self):
        started, entered, phase = self.stack.entries.pop()
        ended = perf_counter()
        self.wrapped.release()
        self.records.append({"phase": phase, "started": started, "entered": entered, "ended": ended,
            "wait_ms": (entered - started) * 1000, "hold_ms": (ended - entered) * 1000,
            "nesting": len(self.stack.entries)})

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()

    def __getattr__(self, name):
        return getattr(self.wrapped, name)


def phase_wrapper(function, phase):
    def wrapped(*args, **kwargs):
        token = _PHASE.set(phase)
        try:
            return function(*args, **kwargs)
        finally:
            _PHASE.reset(token)
    return wrapped


def stats(samples):
    if not samples:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(samples)
    return {"count": len(samples), "p50_ms": median(ordered),
            "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1], "max_ms": ordered[-1]}


def measure(client, doc, name, raw, repeats, probe):
    rows, errors = [], []
    for _iteration in range(repeats):
        token = set_current_doc(doc)
        try:
            state.load_design(create_empty_part("Fresh import benchmark", "HONEYCOMB"))
            params = {"expected_design_id": state.get_or_404().id, "expected_revision": state.revision()}
        finally:
            reset_current_doc(token)
        headers = {"X-NADOC-Doc": doc}
        started = perf_counter()
        baseline = client.get(REVISION_PATH, headers=headers)
        baseline_ms = (perf_counter() - started) * 1000
        baseline.raise_for_status()
        first_record = len(probe.records)
        gate, finished = Barrier(2), Event()
        requests = []

        def sample_revision():
            gate.wait(timeout=5)
            # Each HTTP call yields to the ASGI loop. Bound total sample work
            # independently of source speed; no sleeps or forced contention.
            for _ in range(256):
                if finished.is_set():
                    break
                begin = perf_counter()
                try:
                    response = client.get(REVISION_PATH, headers=headers)
                    response.raise_for_status()
                except Exception as error:
                    errors.append(str(error))
                    break
                requests.append({"start": begin, "end": perf_counter()})

        sampler = Thread(target=sample_revision, name="cadnano-benchmark-revision")
        sampler.start()
        try:
            gate.wait(timeout=5)
            started = perf_counter()
            response = client.post(IMPORT_PATH, params=params, content=raw,
                                   headers={**headers, "content-type": "application/json"})
            route_ms = (perf_counter() - started) * 1000
        finally:
            finished.set()
            sampler.join(timeout=5)
        if sampler.is_alive():
            raise RuntimeError("Benchmark sampler did not finish")
        response.raise_for_status()
        records = probe.records[first_record:]
        publication = [row for row in records if row["phase"] == "publication" and row["nesting"] == 0]
        overlaps = sum(any(request["start"] <= lock["ended"] and lock["entered"] <= request["end"]
                           for lock in publication) for request in requests)
        token = set_current_doc(doc)
        try:
            design = state.get_or_404()
            correct = (state.revision() == params["expected_revision"] + 1
                and state.undo_depth() == 1 and len(design.feature_log) == 1
                and design.feature_log[0].op_kind == "cadnano-import"
                and response.json()["revision"] == state.revision())
        finally:
            reset_current_doc(token)
        rows.append({"route_ms": route_ms, "baseline_revision_ms": baseline_ms,
            "revision_request_ms": [(request["end"] - request["start"]) * 1000 for request in requests],
            "publication_overlapping_requests": overlaps,
            "source_reference_capture_ms": [row["hold_ms"] for row in records if row["phase"] == "source_reference_capture"],
            "publication_hold_ms": [row["hold_ms"] for row in publication],
            "publication_wait_ms": [row["wait_ms"] for row in publication],
            "light_request_lock_wait_ms": [row["wait_ms"] for row in records if row["phase"] == "light_request"],
            "response_read_hold_ms": [row["hold_ms"] for row in records if row["phase"] == "private_preparation"],
            "response_bytes": len(response.content), "correct_publication": correct})
    def combine(key):
        return [value for row in rows for value in row[key]]
    return {"case": name, "source_bytes": len(raw), "repeats": repeats,
        "http_route": stats([row["route_ms"] for row in rows]),
        "baseline_light_request": stats([row["baseline_revision_ms"] for row in rows]),
        "concurrent_light_request": stats(combine("revision_request_ms")),
        "source_reference_capture_lock_hold": stats(combine("source_reference_capture_ms")),
        "publication_lock_hold": stats(combine("publication_hold_ms")),
        "publication_lock_wait": stats(combine("publication_wait_ms")),
        "light_request_lock_wait": stats(combine("light_request_lock_wait_ms")),
        "response_read_lock_hold": stats(combine("response_read_hold_ms")),
        "publication_overlapping_requests": sum(row["publication_overlapping_requests"] for row in rows),
        "correct_publications": sum(row["correct_publication"] for row in rows),
        "errors": errors, "samples": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error("Use 1..25 repeats")
    doc = f"__benchmark_cadnano_route_{uuid4()}__"
    original_lock, original_capture, original_publish, original_prepare = (
        state._lock, state.get_design_with_revision, state.set_design, routes._prepare)
    probe = LockProbe(original_lock)
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")

    @app.get(REVISION_PATH)
    def revision():
        token = _PHASE.set("light_request")
        try:
            return {"revision": state.revision()}
        finally:
            _PHASE.reset(token)

    examples = Path(__file__).resolve().parent.parent / "Examples" / "cadnano"
    sources = [(name, (examples / name).read_bytes()) for name in (
        "Honeycomb_6hb_test1.json", "6hb_cadnano_native_test1.json")]
    small = sources[0][1]
    sources.append(("100KB-source-boundary", small + b" " * (routes.MAX_SOURCE_BYTES - len(small))))
    state._lock = probe
    state.get_design_with_revision = phase_wrapper(original_capture, "source_reference_capture")
    state.set_design = phase_wrapper(original_publish, "publication")
    routes._prepare = phase_wrapper(original_prepare, "private_preparation")
    try:
        with TestClient(app) as client:
            cases = [measure(client, doc, name, raw, args.repeats, probe) for name, raw in sources]
    finally:
        try:
            state.drop_doc(doc)
        finally:
            state._lock = original_lock
            state.get_design_with_revision = original_capture
            state.set_design = original_publish
            routes._prepare = original_prepare
    leaked = doc in state.revision_map()
    print(json.dumps({"scope": "Actual raw HTTP import into fresh empty parts; reference capture, private preparation, one-undo publication and concurrent lightweight HTTP requests",
        "repeats": args.repeats, "capture_limits_unchanged": True,
        "ordinary_proof_capture_invoked": False, "session_cleanup_verified": not leaked,
        "measurement_notes": ["Lock timings include Python instrumentation overhead; no forced lock delays.",
            "Nine repetitions qualify these fixtures, not a general latency ceiling.",
            "Overlap counts indicate observed concurrent requests spanning publication; zero overlap is not evidence of zero contention.",
            "Source-reference capture copies no model; full proof is absent from the import route."],
        "cases": cases}, indent=2))
    return int(leaked or any(row["errors"] or row["correct_publications"] != args.repeats for row in cases))


if __name__ == "__main__":
    raise SystemExit(main())
