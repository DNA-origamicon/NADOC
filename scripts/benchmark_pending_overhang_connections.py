#!/usr/bin/env python3
"""Memory-only ordinary pending CRUD route comparison, with natural GC.

The baseline executes the exact historical route module from bc2ae3cb using the
same current state/core runtime. This measures added feature-recording work; it
is not a whole historical binary A/B. No workspace files or app lifespan run.
Root executes serially under the repository validation guard; stdout JSON only.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import resource
import subprocess
from threading import Barrier, Event, Thread
from time import perf_counter
from types import ModuleType
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_connection_version_commands as native
from backend.api import routes_connection_versions as current_routes, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_proof_commands import execute
from backend.api.part_revision_status import revision_status
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms
from tests.conftest import valid_overhang_sites


BASELINE = "bc2ae3cb"
PATH = "/api/design/connection-versions"
LIGHT = "/__benchmark__/revision"


def historical_routes():
    source = subprocess.run(["git", "show", f"{BASELINE}:backend/api/routes_connection_versions.py"],
        check=True, capture_output=True, timeout=5).stdout
    if len(source) > 100_000:
        raise RuntimeError("Historical route source exceeds the benchmark allowance")
    module = ModuleType("_pending_ordinary_historical_routes")
    exec(compile(source, f"{BASELINE}:routes_connection_versions.py", "exec"), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def append(design, kind, values, identity):
    before, before_size = state.encode_design_snapshot(design)
    result = execute(kind, design, values)
    after, after_size = state.encode_design_snapshot(result)
    row = SnapshotLogEntry(id=identity, op_kind=kind, label=identity,
        timestamp="2026-10-15T00:00:00Z", params=deepcopy(values),
        design_snapshot_gz_b64=before, snapshot_size_bytes=before_size,
        post_state_gz_b64=after, post_state_size_bytes=after_size)
    return result.copy_with(feature_log=[*design.feature_log, row])


def prefix(background):
    design = create_empty_part("Pending ordinary route benchmark", "HONEYCOMB")
    cells = ([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]] if background == "six-cell"
             else [[row, column] for row in range(4) for column in range(4)])
    design = append(design, "bundle-create", {"_proof_version": 1,
        "history_seed": str(UUID(int=810)), "cells": cells,
        "length_bp": 42 if background == "six-cell" else 84,
        "name": "Pending ordinary route benchmark", "lattice_type": "HONEYCOMB"}, "bundle")
    for i, five_prime in enumerate((False, True), start=1):
        site = next(item for item in valid_overhang_sites(design) if item["is_five_prime"] == five_prime)
        design = append(design, "overhang-extrude", {"_proof_version": 1,
            "history_seed": str(UUID(int=810 + i)), **site,
            "direction": site["direction"].value, "length_bp": 12}, f"endpoint-{i}")
    return design


def table(design, count):
    for i in range(count):
        design = append(design, "overhang-bulk", {"_proof_version": 1,
            "connection_version_contract": 1, "action": native.CREATE,
            "version_id": f"retained-{i}", "name": f"Retained {i}", "created_at": float(i),
            "overhang_a_id": design.overhangs[0].id, "overhang_b_id": design.overhangs[1].id,
            "connection_type": "root-to-root-ssdna-linker", "overhang_a_seq": "ACGT" * 3,
            "overhang_b_seq": None, "bridge_length": 7, "bridge_seq": None, "applied": False}, f"retained-row-{i}")
    return design


class Timings:
    def __init__(self):
        self.events, self.restore = [], []

    def wrap(self, owner, name, label, *, phase=None):
        original = getattr(owner, name)
        self.restore.append((owner, name, original))
        def measured(*args, **kwargs):
            token = _PHASE.set(phase) if phase else None
            start = perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.events.append({"label": label, "start": start, "end": perf_counter()})
                if token is not None:
                    _PHASE.reset(token)
        setattr(owner, name, measured)

    def close(self):
        for owner, name, original in reversed(self.restore):
            setattr(owner, name, original)


def app_for(routes):
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")
    @app.get(LIGHT)
    def light():
        return phase_wrapper(revision_status, "light")()
    return app


def measured(client, doc, method, path, body, locks, timers, runtime):
    headers = {"X-NADOC-Doc": doc}
    gate, done = Barrier(2), Event()
    light = {"count": 0, "total_ms": 0., "max_ms": 0., "last_end": None, "deadline_reached": False}
    errors = []
    def sample():
        try:
            gate.wait(timeout=5)
            deadline = perf_counter() + 5
            while not done.is_set() and perf_counter() < deadline:
                begin = perf_counter()
                response = client.get(LIGHT, headers=headers)
                end = perf_counter()
                response.raise_for_status()
                elapsed = (end - begin) * 1000
                light.update(count=light["count"] + 1, total_ms=light["total_ms"] + elapsed,
                             max_ms=max(light["max_ms"], elapsed), last_end=end)
                done.wait(.010)
            light["deadline_reached"] = not done.is_set()
        except BaseException as error:
            errors.append(f"{type(error).__name__}: {error}")
    locks.records.clear()
    timers.events.clear()
    sampler = Thread(target=sample, name="ordinary-pending-revision")
    sampler.start()
    try:
        gate.wait(timeout=5)
        start = perf_counter()
        response = client.request(method, path, headers=headers, json=body)
        end = perf_counter()
    finally:
        done.set()
        sampler.join(timeout=5)
    if sampler.is_alive():
        raise RuntimeError("Revision sampler failed to finish")
    records = [row for row in locks.records if row["nesting"] == 0]
    recording = [row for row in records if row["phase"] in {"current", "historical"}]
    gc_events = runtime.intervals(start, end)
    return response, {"status": response.status_code, "route_ms": (end - start) * 1000,
        "response_bytes": len(response.content), "light_count": light["count"],
        "light_mean_ms": light["total_ms"] / max(1, light["count"]), "light_max_ms": light["max_ms"],
        "light_last_end_relative_ms": None if light["last_end"] is None else (light["last_end"] - start) * 1000,
        "sampler_deadline_reached": light["deadline_reached"], "errors": errors,
        "recording_lock_ms": [row["hold_ms"] for row in recording],
        "recording_wait_ms": [row["wait_ms"] for row in recording],
        "other_lock_ms": [row["hold_ms"] for row in records if row["phase"] not in {"current", "historical", "light"}],
        "light_lock_wait_ms": [row["wait_ms"] for row in records if row["phase"] == "light"],
        "stages": {name: stats([(item["end"] - item["start"]) * 1000 for item in timers.events if item["label"] == name])
                   for name in ("snapshot_copy", "snapshot_encode", "validation", "response")},
        "gc_count": len(gc_events), "gc_overlap_ms": overlap_ms(gc_events, start, end),
        "gc_lock_overlap_ms": sum(overlap_ms(gc_events, row["entered"], row["ended"]) for row in recording)}


def cycle(client, template, mode, iteration, locks, timers, runtime):
    doc = f"__benchmark_pending_ordinary_{uuid4()}"
    token = set_current_doc(doc)
    try:
        state.load_design(template.model_copy(deep=True))
        revision, depth = state.revision(), state.undo_depth()
    finally:
        reset_current_doc(token)
    rows = []
    try:
        body = {"overhang_a_id": template.overhangs[0].id, "overhang_b_id": template.overhangs[1].id,
                "connection_type": "root-to-root-ssdna-linker", "bridge_length": 7, "name": "Measured candidate"}
        response, row = measured(client, doc, "POST", PATH, body, locks, timers, runtime)
        rows.append({"mode": mode, "iteration": iteration, "action": "create", **row})
        response.raise_for_status()
        identity = response.json()["design"]["connection_versions"][-1]["id"]
        response, row = measured(client, doc, "PATCH", f"{PATH}/{identity}", {"name": "Measured edit", "bridge_length": 9}, locks, timers, runtime)
        rows.append({"mode": mode, "iteration": iteration, "action": "patch", **row})
        response.raise_for_status()
        response, row = measured(client, doc, "DELETE", f"{PATH}/{identity}", None, locks, timers, runtime)
        rows.append({"mode": mode, "iteration": iteration, "action": "delete", **row})
        response.raise_for_status()
        token = set_current_doc(doc)
        try:
            design = state.get_or_404()
            correct = (state.revision() == revision + 3 and state.undo_depth() == depth + 3
                and design.model_dump(mode="json", include=AUTHORING_FIELDS) == template.model_dump(mode="json", include=AUTHORING_FIELDS)
                and len(design.feature_log) == len(template.feature_log) + (3 if mode == "current" else 0))
            snapshot_bytes = sum(len(getattr(entry, key, "") or "") for entry in design.feature_log
                for key in ("design_snapshot_gz_b64", "post_state_gz_b64"))
            signature = (design.model_dump_json(), state.revision(), state.undo_depth())
        finally:
            reset_current_doc(token)
        response, row = measured(client, doc, "POST", PATH, {**body, "overhang_b_id": "missing"}, locks, timers, runtime)
        rows.append({"mode": mode, "iteration": iteration, "action": "missing_endpoint", **row})
        token = set_current_doc(doc)
        try:
            refusal_atomic = (response.status_code == 404 and signature == (
                state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()))
        finally:
            reset_current_doc(token)
        return {"samples": rows, "correct_lifecycle": correct, "refusal_atomic": refusal_atomic,
                "recovery_encoded_bytes": snapshot_bytes}
    finally:
        state.drop_doc(doc)


def run(repeats):
    historical, digest = historical_routes()
    original_lock = state._lock
    locks, timers = LockProbe(original_lock), Timings()
    runtime = RuntimeProbe(phase=lambda: _PHASE.get(), max_events=4096)
    before_sessions = set(state._sessions)
    report = {"baseline_commit": BASELINE, "baseline_route_sha256": digest,
        "baseline_scope": "Exact historical route module; shared current state/core runtime; not a whole-binary A/B",
        "natural_gc": True, "forced_gc": False, "repeats": repeats, "cases": [], "cleanup": False}
    prefixes = {background: prefix(background) for background in ("six-cell", "sixteen-cell")}
    templates = [(background, count, table(prefixes[background].model_copy(deep=True), count))
                 for background, count in (("six-cell", 0), ("six-cell", 16), ("six-cell", 128),
                                            ("sixteen-cell", 16), ("sixteen-cell", 64))]
    state._lock = locks
    timers.wrap(state, "_snapshot_copy", "snapshot_copy")
    timers.wrap(state, "encode_design_snapshot", "snapshot_encode")
    timers.wrap(state, "validate_design", "validation")
    timers.wrap(state, "mutate_and_validate", "legacy_mutation", phase="historical")
    timers.wrap(native, "try_record", "native_mutation", phase="current")
    timers.wrap(current_routes, "_design_response", "response")
    timers.wrap(historical, "_design_response", "response")
    try:
        with runtime, TestClient(app_for(historical)) as old, TestClient(app_for(current_routes)) as new:
            clients = {"historical": old, "current": new}
            for background, count, template in templates:
                case = {"background": background, "retained_candidates": count, "native_prefix_rows": 3,
                        "retained_rows": len(template.feature_log), "cycles": [],
                        "fixture_authority": "Native inputs and matching recorded recovery for every candidate",
                        "cold_proof_executed_in_benchmark": False,
                        "helices": len(template.helices), "strands": len(template.strands),
                        "declared_bp": sum(helix.length_bp for helix in template.helices),
                        "retained_encoded_recovery_bytes": sum(len(getattr(row, key, "") or "")
                            for row in template.feature_log for key in ("design_snapshot_gz_b64", "post_state_gz_b64"))}
                report["cases"].append(case)
                for iteration in range(repeats):
                    order = ("historical", "current") if iteration % 2 == 0 else ("current", "historical")
                    for mode in order:
                        case["cycles"].append(cycle(clients[mode], template, mode, iteration, locks, timers, runtime))
                samples = [sample for item in case["cycles"] for sample in item["samples"]]
                case["summary"] = {mode: {action: {
                    "route": stats([row["route_ms"] for row in samples if row["mode"] == mode and row["action"] == action]),
                    "light_max": stats([row["light_max_ms"] for row in samples if row["mode"] == mode and row["action"] == action]),
                    "lock": stats([value for row in samples if row["mode"] == mode and row["action"] == action for value in row["recording_lock_ms"]]),
                } for action in ("create", "patch", "delete", "missing_endpoint")} for mode in clients}
                case["worst_gc_sample"] = max(samples, key=lambda row: row["gc_overlap_ms"])
    finally:
        timers.close()
        state._lock = original_lock
        report["cleanup"] = set(state._sessions) == before_sessions
    report.update(max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  dropped_gc_events=runtime.dropped_events)
    report["all_checks_passed"] = report["cleanup"] and all(
        item["correct_lifecycle"] and item["refusal_atomic"]
        and all(not row["errors"] and not row["sampler_deadline_reached"] for row in item["samples"])
        for case in report["cases"] for item in case["cycles"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error("repeats must be between 1 and 25")
    result = run(args.repeats)
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
