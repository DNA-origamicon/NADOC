#!/usr/bin/env python3
"""Memory-only gated finite Apply/reapply HTTP comparison; root runs serially.

Both arms use this checkout and identical native-input fixtures. The sole policy
difference is the private route gate, set before each request. No production
lifespan, files, worker, solver, forced GC or browser is used. Compact stdout JSON
retains every request; correctness success is not latency qualification.
"""

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import resource
from threading import Barrier, Event, Thread
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from backend.api import doc_context, part_connection_application_commands as native
from backend.api import routes_connection_versions as routes, state
from backend.api.part_revision_status import revision_status
from backend.core import lattice, part_scope_references, sequences
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_pending_overhang_connections import Timings, append
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms
from tests.conftest import valid_overhang_sites
from tests.test_part_pending_connection_versions import proof


PATH = "/api/design/connection-versions"
LIGHT = "/__benchmark__/revision"
STAGES = ("source_admission", "source_index", "selection", "output_identity",
          "native_materialization", "linker_topology", "linker_removal", "sequences",
          "snapshot_copy", "snapshot_encode", "reconcile", "retry_ligations",
          "validation", "response_geometry", "response_serialization", "response_json")
CASES = (("six-cell", "ss", 1), ("six-cell", "ds", 16),
         ("sixteen-cell", "ss", 1), ("sixteen-cell", "ds", 16))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def fixture(background, material, count):
    design = create_empty_part("Finite Apply benchmark", "HONEYCOMB")
    cells = ([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]] if background == "six-cell"
             else [[row, column] for row in range(4) for column in range(4)])
    design = append(design, "bundle-create", {"_proof_version": 1,
        "history_seed": str(UUID(int=810)), "cells": cells,
        "length_bp": 42 if background == "six-cell" else 84,
        "name": "Finite Apply benchmark", "lattice_type": "HONEYCOMB"}, "bundle")
    for i, five_prime in enumerate((False, True), start=1):
        site = next(item for item in valid_overhang_sites(design) if item["is_five_prime"] == five_prime)
        design = append(design, "overhang-extrude", {"_proof_version": 1,
            "history_seed": str(UUID(int=810 + i)), **site,
            "direction": site["direction"].value, "length_bp": 12,
            "reuse_existing_helix": False}, f"endpoint-{i}")
    for i in range(count):
        design = append(design, "overhang-bulk", {"_proof_version": 1,
            "connection_version_contract": 1, "action": "connection-version-create",
            "version_id": f"retained-{i}", "name": f"Retained {i}", "created_at": float(i),
            "overhang_a_id": design.overhangs[0].id, "overhang_b_id": design.overhangs[1].id,
            "connection_type": f"root-to-root-{material}dna-linker",
            "overhang_a_seq": "ACGT" * 3, "overhang_b_seq": "TGCA" * 3,
            "bridge_length": 7, "bridge_seq": "GGNN", "applied": False}, f"retained-row-{i}")
    return design


class EncodingTimings:
    """Measure only this HTTP request's encoding, not recursive encoder calls.

    FastAPI's annotated-dict fast path includes direct JSON-byte encoding in
    serialize_response. JSONResponse.render is used by error responses instead.
    """

    def __init__(self, timers):
        self.timers = timers
        self.restore = []

    def __enter__(self):
        import fastapi.routing
        original = fastapi.routing.serialize_response
        render = JSONResponse.render
        self.restore = [(fastapi.routing, "serialize_response", original), (JSONResponse, "render", render)]

        async def serialize(*args, **kwargs):
            started = perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                if _PHASE.get() == "http_apply":
                    self.timers.events.append({"label": "response_serialization", "start": started, "end": perf_counter()})

        def rendered(instance, content):
            started = perf_counter()
            try:
                return render(instance, content)
            finally:
                if _PHASE.get() == "http_apply":
                    self.timers.events.append({"label": "response_json", "start": started, "end": perf_counter()})

        fastapi.routing.serialize_response, JSONResponse.render = serialize, rendered
        return self

    def __exit__(self, *_args):
        for owner, name, original in reversed(self.restore):
            setattr(owner, name, original)


class RequestPhase:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = _PHASE.set("light" if scope.get("path") == LIGHT else "http_apply")
        try:
            await self.app(scope, receive, send)
        finally:
            _PHASE.reset(token)


def application():
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.add_middleware(RequestPhase)
    app.include_router(routes.router, prefix="/api")

    @app.get(LIGHT)
    def light():
        return phase_wrapper(revision_status, "light")()

    return app


def measure(client, doc, version, mode, locks, timers, runtime):
    headers = {"X-NADOC-Doc": doc}
    barrier, done, reading = Barrier(2), Event(), Event()
    light = {"count": 0, "total_ms": 0., "max_ms": 0., "last_end_ms": None,
             "deadline_reached": False}
    errors, statuses = [], Counter()
    origin = [None]

    def sample():
        try:
            barrier.wait(timeout=5)
            deadline = perf_counter() + 5
            while not done.is_set() and perf_counter() < deadline:
                begin = perf_counter()
                reading.set()
                response = client.get(LIGHT, headers=headers)
                end = perf_counter()
                statuses[response.status_code] += 1
                elapsed = (end - begin) * 1000
                light.update(count=light["count"] + 1, total_ms=light["total_ms"] + elapsed,
                    max_ms=max(light["max_ms"], elapsed), last_end_ms=(end - origin[0]) * 1000)
                done.wait(.010)
            light["deadline_reached"] = not done.is_set()
        except BaseException as error:
            errors.append(f"{type(error).__name__}: {error}"[:256])

    locks.records.clear()
    timers.events.clear()
    routes.OWNED_FINITE_CONNECTION_APPLY_ENABLED = mode == "native"
    sampler = Thread(target=sample, name="finite-apply-revision")
    sampler.start()
    response = None
    started = perf_counter()
    try:
        origin[0] = perf_counter()
        barrier.wait(timeout=5)
        if not reading.wait(5):
            raise RuntimeError("Revision sampler did not enter its first HTTP read")
        started = perf_counter()
        response = client.post(f"{PATH}/{version}/apply", headers=headers)
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}"[:256])
    finally:
        ended = perf_counter()
        done.set()
        sampler.join(timeout=5)
    if sampler.is_alive():
        raise RuntimeError("Finite Apply revision sampler did not stop")
    records = [row for row in locks.records if row["nesting"] == 0]
    held = [row for row in records if row["phase"] != "light"]
    gc_events = runtime.intervals(started, ended)
    row = {"status": response.status_code if response is not None else None,
        "http_ms": (ended - started) * 1000,
        "response_bytes": len(response.content) if response is not None else 0,
        "light": {**light, "statuses": dict(statuses)}, "errors": errors,
        "lock_ms": [item["hold_ms"] for item in held],
        "lock_wait_ms": [item["wait_ms"] for item in held],
        "light_lock_wait_max_ms": max((item["wait_ms"] for item in records if item["phase"] == "light"), default=0.),
        "gc_count": len(gc_events), "gc_overlap_ms": overlap_ms(gc_events, started, ended),
        "gc_lock_overlap_ms": sum(overlap_ms(gc_events, item["entered"], item["ended"]) for item in held),
        "stage_ms": [[(item["end"] - item["start"]) * 1000 for item in timers.events
                      if item["label"] == name] for name in STAGES]}
    return response, row


def normalize(value, identities):
    """Only known identity tokens change; never round or alter coordinates."""
    if isinstance(value, str):
        return identities.get(value, value)
    if isinstance(value, list):
        return [normalize(item, identities) for item in value]
    if isinstance(value, dict):
        return {identities.get(key, key): normalize(item, identities) for key, item in value.items()}
    return value


def response_semantics(response, identities, original_rows):
    result = normalize(response, identities)
    # Validator messages quote strand IDs with repr(). Normalize those exact
    # known quoted IDs too; keep all message text and numerical verdicts.
    for verdict in result.get("validation", {}).get("results", []):
        message = verdict.get("message", "")
        for old, new in sorted(identities.items(), key=lambda item: len(item[0]), reverse=True):
            message = message.replace(repr(old), repr(new))
            # topology_integrity.occupancy_errors emits this helix ID without
            # repr(). Preserve the warning, bp, polarity and strand ownership.
            if message.startswith("Duplicate nucleotide occupancy at ("):
                message = message.replace(f"({old}, bp ", f"({new}, bp ", 1)
        verdict["message"] = message
    # The new inputs are the intentional history difference. Keep every other
    # response field, including full precision coordinates and validation.
    for number, row in enumerate(result["design"]["feature_log"][original_rows:]):
        row["id"], row["timestamp"] = f"apply-row-{number}", "recorded-time"
        row["params"] = {name: row["params"][name] for name in ("version_id", "connection_type")}
        for name in ("design_snapshot_gz_b64", "post_state_gz_b64"):
            row[name] = "recorded-recovery" if row[name] else ""
        row["snapshot_size_bytes"] = row["post_state_size_bytes"] = 0
    return result


def differing_paths(left, right, limit=8):
    """Compact mismatch evidence without printing a design or geometry payload."""
    found, pending = [], [(left, right, [])]
    while pending and len(found) < limit:
        a, b, path = pending.pop()
        if type(a) is not type(b):
            found.append(path)
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                found.append([*path, "<keys>"])
            pending.extend((a[key], b[key], [*path, key]) for key in a.keys() & b.keys())
        elif isinstance(a, list):
            if len(a) != len(b):
                found.append([*path, "<length>"])
            pending.extend((x, y, [*path, i]) for i, (x, y) in enumerate(zip(a, b)))
        elif a != b:
            found.append(path)
    return found


def scalar_mismatches(left, right, paths):
    """Retain bounded scalar evidence for the first unequal pair, never models."""
    def scalar_at(value, path):
        for key in path:
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
                value = value[key]
            else:
                return {"kind": "unavailable"}
        if isinstance(value, str):
            return {"kind": "str", "value": value[:512], "truncated": len(value) > 512}
        if value is None or type(value) in (bool, int, float):
            return {"kind": type(value).__name__, "value": value}
        return {"kind": type(value).__name__}

    return [{"path": path, "legacy": scalar_at(left, path), "native": scalar_at(right, path)}
            for path in paths[:8]]


def cycle(client, template, mode, iteration, locks, timers, runtime, *, replay=False, missing=False,
          compact_parity=False):
    doc = f"__benchmark_finite_apply_{uuid4()}"
    session = state._DesignSession(design=template.model_copy(deep=True), revision=7)
    if missing:
        session.design.connection_versions[0].overhang_b_id = "missing-endpoint"
    with state._lock:
        state._sessions[doc] = session
    samples, identities, outputs, compared = [], {}, [], []
    try:
        for offset, action in enumerate(("missing_endpoint",) if missing else ("apply", "reapply")):
            source = session.design
            old_authoring = digest(source.model_dump(mode="json", include=AUTHORING_FIELDS))
            old_document = digest(source.model_dump(mode="json"))
            previous_ids = [item.id for item in source.overhang_connections]
            history_rows, depth, revision = len(source.feature_log), len(session.history), session.revision
            response, sample = measure(client, doc, "retained-0", mode, locks, timers, runtime)
            samples.append({"action": action, **sample})
            current = session.design
            sample = samples[-1]
            sample["source_authoring_unchanged"] = old_authoring == digest(source.model_dump(mode="json", include=AUTHORING_FIELDS))
            sample["source_document_unchanged"] = old_document == digest(source.model_dump(mode="json"))
            if missing:
                sample["published_source_identity_preserved"] = current is source
                sample["correct_lifecycle"] = (sample["status"] == 404
                    and session.revision == revision and len(session.history) == depth
                    and old_document == digest(current.model_dump(mode="json"))
                    and sample["source_document_unchanged"])
                outputs.append(None)
                continue
            if sample["status"] != 200:
                sample["correct_lifecycle"] = False
                sample["error_body"] = response.text[:256] if response is not None else None
                outputs.append(None)
                break
            payload = response.json()
            connection = current.overhang_connections[0]
            for old, new in ((connection.id, f"output-{offset}"),
                             (f"__lnk__{connection.id}", f"__lnk__output-{offset}"),
                             *((f"__lnk__{connection.id}__{suffix}", f"__lnk__output-{offset}__{suffix}")
                               for suffix in ("s", "a", "b"))):
                identities[old] = new
            entry = current.feature_log[-1]
            native_row = entry.params.get("action") == native.ACTION
            sample["native_path_exercised"] = native_row
            stage_counts = {name: len(sample["stage_ms"][i]) for i, name in enumerate(STAGES)}
            sample["recording_work_expected"] = (stage_counts["snapshot_copy"] == 1
                and stage_counts["snapshot_encode"] == 2 and stage_counts["reconcile"] == 1
                and stage_counts["retry_ligations"] == 1 and stage_counts["validation"] == 1
                and (mode != "native" or all(stage_counts[name] == 1 for name in
                    ("source_admission", "source_index", "selection", "output_identity", "native_materialization"))))
            sample["correct_lifecycle"] = (session.revision == revision + 1
                and len(session.history) == depth + 1 and len(current.feature_log) == history_rows + 1
                and len(current.overhang_connections) == 1
                and current.connection_versions[0].applied
                and all(not item.applied for item in current.connection_versions[1:])
                and payload.get("partial_geometry") is not True
                and native_row == (mode == "native"))
            if native_row:
                sample["recorded_inputs_correct"] = (entry.params["connection_id"] == connection.id
                    and entry.params["conflict_connection_ids"] == previous_ids
                    and entry.params["conflict_version_ids"] == [row.id for row in template.connection_versions]
                    and entry.params["version_id"] == "retained-0"
                    and entry.params["connection_application_version"] == 1)
            semantic = {"authoring": normalize(current.model_dump(mode="json", include=AUTHORING_FIELDS), identities),
                "response": response_semantics(payload, identities, len(template.feature_log))}
            if not compact_parity:
                compared.append(semantic)
            outputs.append({key: digest(value) for key, value in semantic.items()})
            if compact_parity:
                # Keep only exact semantic digests between requests/arms. These
                # client-side graphs otherwise inflate the server's GC heap in
                # this in-process harness. No collection policy is changed.
                del semantic, payload, response
        replay_result = None
        if replay and len(outputs) == 2 and all(outputs):
            owned = Design.model_validate_json(session.design.model_dump_json())
            for row in owned.feature_log:
                row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "not an input"
            checked = proof(owned)
            replay_result = {key: checked.get(key) for key in ("status", "checked_commands", "native_editable", "issues")}
        return ({"mode": mode, "iteration": iteration, "samples": samples,
            "semantic_digests": outputs, "input_replay": replay_result}, compared)
    finally:
        state.drop_doc(doc)


def run(repeats, *, compact_parity=False):
    original_lock, original_gate = state._lock, routes.OWNED_FINITE_CONNECTION_APPLY_ENABLED
    before_sessions, before_gc = dict(state._sessions), tuple(gc.callbacks)
    timers, locks = Timings(), LockProbe(original_lock)
    observed_gc_events = dropped_gc_events = 0
    report = {"comparison": "Same current runtime, private gate false/true; no historical binary",
        "repeats": repeats, "natural_gc": True, "forced_gc": False,
        "compact_parity": compact_parity,
        "response_retention": ("Only exact authoring/response digests survive between requests and arms; raw, decoded and normalized client responses are released. Untimed decoding/normalization still shares this process and may shift GC cadence."
            if compact_parity else "Full decoded/normalized client responses survive between requests and arms for mismatch diagnostics; this inflates the shared server/client GC heap and is not external-browser latency qualification."),
        "production_gate_initial": original_gate, "stage_columns": STAGES,
        "response_normalization": "Exact generated identity keys/values, quoted validator references and documented duplicate-occupancy (ID, bp location tokens; appended history id/time/recovery sizes and intentional params representation only",
        "serialization_stages": "response_serialization includes FastAPI annotated-dict direct JSON-byte encoding; response_json measures JSONResponse.render, ordinarily error responses. Stages are nested, not additive.",
        "gc_probe_scope": "One bounded 16,384-event probe per alternating pair; observed/dropped counts aggregated without changing GC policy",
        "source_policy": "Authoring unchanged in both arms; complete source unchanged required for native, legacy history aliasing reported",
        "latency_qualified": False, "cases": [], "fixture_errors": [], "cleanup": False,
        "source_sha256": {str(Path(module.__file__).relative_to(Path.cwd())): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                          for module in (native, routes, part_scope_references)},
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    templates = []
    for background, material, count in CASES:
        try:
            templates.append((background, material, count, fixture(background, material, count)))
        except Exception as error:
            report["fixture_errors"].append({"background": background, "material": material,
                "pending_rows": count, "code": getattr(error, "code", None),
                "error": f"{type(error).__name__}: {error}"[:512]})
    try:
        state._lock = locks
        for owner, name, label in ((native, "_bounded_source", "source_admission"),
            (native, "identity_index", "source_index"), (native, "_select_inputs", "selection"),
            (native, "_check_outputs", "output_identity"), (native, "_materialize", "native_materialization"),
            (lattice, "generate_linker_topology", "linker_topology"), (lattice, "remove_linker_topology", "linker_removal"),
            (sequences, "reassign_strands", "sequences"), (state, "_snapshot_copy", "snapshot_copy"),
            (state, "encode_design_snapshot", "snapshot_encode"), (state, "reconcile_cluster_membership", "reconcile"),
            (state, "_retry_pending_ligations", "retry_ligations"), (state, "validate_design", "validation"),
            (routes, "_design_response_with_geometry", "response_geometry")):
            timers.wrap(owner, name, label)
        with EncodingTimings(timers), TestClient(application(), raise_server_exceptions=False) as client:
            for background, material, count, template in templates:
                original = digest(template.model_dump(mode="json"))
                case = {"background": background, "material": material, "pending_rows": count,
                    "native_rows": len(template.feature_log), "helices": len(template.helices),
                    "strands": len(template.strands), "declared_bp": sum(row.length_bp for row in template.helices),
                    "retained_recovery_bytes": sum(len(getattr(row, field) or "") for row in template.feature_log
                        for field in ("design_snapshot_gz_b64", "post_state_gz_b64")), "pairs": []}
                report["cases"].append(case)
                for iteration in range(repeats):
                    pair, comparison = {}, {}
                    order = ("legacy", "native") if iteration % 2 == 0 else ("native", "legacy")
                    with RuntimeProbe(phase=lambda: _PHASE.get(), max_events=16_384) as runtime:
                        for mode in order:
                            pair[mode], comparison[mode] = cycle(client, template, mode, iteration, locks, timers, runtime,
                                replay=mode == "native" and iteration == 0, compact_parity=compact_parity)
                    observed_gc_events += len(runtime.events)
                    dropped_gc_events += runtime.dropped_events
                    equal = (len(pair["legacy"]["semantic_digests"]) == 2
                        and all(pair["legacy"]["semantic_digests"])
                        and pair["legacy"]["semantic_digests"] == pair["native"]["semantic_digests"])
                    mismatch_paths = (([["semantic_digests"]] if compact_parity else
                        differing_paths(comparison["legacy"], comparison["native"])) if not equal else [])
                    if mismatch_paths and not compact_parity and "first_scalar_mismatches" not in case:
                        case["first_scalar_mismatches"] = scalar_mismatches(
                            comparison["legacy"], comparison["native"], mismatch_paths)
                    case["pairs"].append({"order": order, "semantic_parity": equal,
                        "mismatch_paths": mismatch_paths,
                        "observed_gc_events": len(runtime.events), "dropped_gc_events": runtime.dropped_events, **pair})
                    del comparison
                case["template_unchanged"] = original == digest(template.model_dump(mode="json"))
                samples = [(mode, row) for pair in case["pairs"] for mode in ("legacy", "native")
                           for row in pair[mode]["samples"]]
                case["summary"] = {mode: {action: {
                    "http": stats([row["http_ms"] for arm, row in samples if arm == mode and row["action"] == action]),
                    "light_max": stats([row["light"]["max_ms"] for arm, row in samples if arm == mode and row["action"] == action]),
                    "lock_total": stats([sum(row["lock_ms"]) for arm, row in samples if arm == mode and row["action"] == action]),
                    "lock": stats([value for arm, row in samples if arm == mode and row["action"] == action for value in row["lock_ms"]])}
                    for action in ("apply", "reapply")} for mode in ("legacy", "native")}
                case["worst_gc_sample"] = max(samples, key=lambda item: item[1]["gc_overlap_ms"])
                if len(report["cases"]) == 1:
                    # One diagnostic pair, not a refusal latency distribution.
                    with RuntimeProbe(phase=lambda: _PHASE.get(), max_events=16_384) as runtime:
                        report["missing_endpoint_diagnostic"] = [cycle(client, template, mode, 0,
                            locks, timers, runtime, missing=True)[0] for mode in ("legacy", "native")]
                    observed_gc_events += len(runtime.events)
                    dropped_gc_events += runtime.dropped_events
    finally:
        timers.close()
        routes.OWNED_FINITE_CONNECTION_APPLY_ENABLED = original_gate
        state._lock = original_lock
        report["cleanup"] = (state._sessions == before_sessions and tuple(gc.callbacks) == before_gc
            and routes.OWNED_FINITE_CONNECTION_APPLY_ENABLED is original_gate and state._lock is original_lock)
    report.update(max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  observed_gc_events=observed_gc_events, dropped_gc_events=dropped_gc_events)

    def valid_cycle(value):
        return all(row["correct_lifecycle"] and row["source_authoring_unchanged"]
            and (value["mode"] != "native" or row["source_document_unchanged"])
            and row.get("recorded_inputs_correct", True) and not row["errors"]
            and row.get("recording_work_expected", True) and row["light"]["count"] > 0
            and not row["light"]["deadline_reached"]
            and set(row["light"]["statuses"]).issubset({200}) for row in value["samples"])

    report["all_correctness_checks_passed"] = report["cleanup"] and not dropped_gc_events and not report["fixture_errors"] and all(
        case["template_unchanged"] and all(pair["semantic_parity"] and all(valid_cycle(pair[mode])
            for mode in ("legacy", "native")) for pair in case["pairs"])
        and case["pairs"][0]["native"]["input_replay"] is not None
        and case["pairs"][0]["native"]["input_replay"]["status"] == "verified"
        for case in report["cases"]) and all(valid_cycle(row) for row in report.get("missing_endpoint_diagnostic", []))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=31)
    parser.add_argument("--compact-parity", action="store_true",
        help="Release large client response graphs before the next request; retain exact semantic digests")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 31:
        parser.error("repeats must be between 1 and 31")
    result = run(args.repeats, compact_parity=args.compact_parity)
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))
    raise SystemExit(0 if result["all_correctness_checks_passed"] else 1)
