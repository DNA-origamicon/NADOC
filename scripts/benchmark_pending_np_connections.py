#!/usr/bin/env python3
"""Memory-only pending NP HTTP/lock measurements; no simulations or limit changes.

Run serially under the repository validation guard. Native and compatibility
recording use the same prepared native owner/target and unchanged endpoints.
The compatibility baseline bypasses only the new native adapter in this process;
it is explicitly unverified and is not an older binary performance measurement.
"""

import argparse
from copy import deepcopy
import json
import pickle
from threading import Barrier, Event, Thread, get_ident
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_nanoparticle_connection_commands as native
from backend.api import part_thiol_patch_commands as thiol
from backend.api import routes_nanoparticles as routes, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_proof_commands import execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import admit, capture
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats
from scripts.benchmark_runtime_probe import RuntimeProbe, overlap_ms
from tests.conftest import valid_overhang_sites


PATH = "/api/design/nanoparticles/gold/connection-versions"
LIGHT = "/__benchmark__/revision"
MAX_DIAGNOSTIC_EVENTS = 4096


class Diagnostics:
    """Optional bounded correlation only; never alter collection or admission."""

    def __init__(self):
        self.runtime = RuntimeProbe(phase=lambda: _PHASE.get(), max_events=MAX_DIAGNOSTIC_EVENTS)
        self.stages, self.dropped_stages = [], 0
        self.originals = {}

    @property
    def gc_events(self):
        return self.runtime.events

    @property
    def dropped_gc(self):
        return self.runtime.dropped_events

    def install(self):
        self.runtime.__enter__()
        for name in ("_bounded", "typed_ownership_supported", "identity_index"):
            original = self.originals[name] = getattr(native, name)
            def measured(*args, _name=name, _original=original, **kwargs):
                if _PHASE.get() != "pending_native":
                    return _original(*args, **kwargs)
                start = perf_counter()
                try:
                    return _original(*args, **kwargs)
                finally:
                    end = perf_counter()
                    if len(self.stages) < MAX_DIAGNOSTIC_EVENTS:
                        self.stages.append({"stage": _name, "start": start, "end": end, "thread": get_ident()})
                    else:
                        self.dropped_stages += 1
            setattr(native, name, measured)

    def close(self):
        self.runtime.__exit__()
        for name, original in self.originals.items():
            setattr(native, name, original)

    def window(self, start, end, locks, light):
        collections = self.runtime.intervals(start, end)
        stages = [item for item in self.stages if start <= item["start"] and item["end"] <= end]
        return {"correlation_only": True, "gc_events": collections,
            "gc_route_overlap_ms": overlap_ms(collections, start, end),
            "gc_recording_lock_overlap_ms": [overlap_ms(collections, row["entered"], row["ended"]) for row in locks],
            "gc_light_request_overlap_ms": [overlap_ms(collections, row["start"], row["end"]) for row in light],
            "native_leaf_stages": {name: stats([(row["end"] - row["start"]) * 1000 for row in stages
                                               if row["stage"] == name]) for name in self.originals},
            "native_leaf_total_ms": sum((row["end"] - row["start"]) * 1000 for row in stages),
            "dropped_gc_events": self.dropped_gc, "dropped_stage_events": self.dropped_stages}


def append(design, kind, params, identity):
    before, before_size = state.encode_design_snapshot(design)
    result = execute(kind, design, params)
    after, after_size = state.encode_design_snapshot(result)
    row = SnapshotLogEntry(id=identity, op_kind=kind, label=identity,
        timestamp="2026-10-15T00:00:00Z", params=deepcopy(params),
        design_snapshot_gz_b64=before, snapshot_size_bytes=before_size,
        post_state_gz_b64=after, post_state_size_bytes=after_size)
    return result.copy_with(feature_log=[*design.feature_log, row])


def prefix(handles, *, background="six-cell"):
    design = create_empty_part("Pending nanoparticle HTTP qualification", "HONEYCOMB")
    cells = ([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]] if background == "six-cell"
             else [[row, column] for row in range(8) for column in range(8)])
    design = append(design, "bundle-create", {"_proof_version": 1, "history_seed": str(UUID(int=701)),
        "cells": cells, "length_bp": 42 if background == "six-cell" else 126,
        "name": "Pending nanoparticle HTTP qualification", "lattice_type": "HONEYCOMB"}, "bundle")
    site = next(item for item in valid_overhang_sites(design) if not item["is_five_prime"])
    design = append(design, "overhang-extrude", {"_proof_version": 1, "history_seed": str(UUID(int=702)),
        **site, "direction": site["direction"].value, "length_bp": 12}, "target")
    design = append(design, "overhang-sequence", {"_proof_version": 1,
        "overhang_id": design.overhangs[0].id, "sequence": "ACGT" * 3, "defer_reassign": True}, "sequence")
    design = append(design, "nanoparticle-create", {"_proof_version": 1, "nanoparticle_version": 1,
        "nanoparticle_id": "gold", "diameter_nm": 10.0}, "gold")
    return append(design, "nanoparticle-conjugate", {"_proof_version": 1, "thiol_version": 1,
        "history_seed": str(UUID(int=704)), "nanoparticle_id": "gold", "conjugation_id": "gold-graft",
        "replace_conjugation_ids": [], "scheme": "direct_thiol", "sequence": "ACGT" * 3,
        "count": handles, "attach_end": "5p", "spacer_nm": None, "seed": 17}, "graft")


def revision(doc):
    token = set_current_doc(doc)
    try:
        return state.revision()
    finally:
        reset_current_doc(token)


def timed_request(client, doc, probe, method, path, body=None, diagnostics=None):
    headers = {"X-NADOC-Doc": doc}
    start = perf_counter()
    baseline = client.get(LIGHT, headers=headers)
    baseline.raise_for_status()
    baseline_ms = (perf_counter() - start) * 1000
    gate, finished, light, errors = Barrier(2), Event(), [], []
    def sample():
        try:
            gate.wait(timeout=5)
            for _ in range(256):
                if finished.is_set():
                    break
                start = perf_counter()
                result = client.get(LIGHT, headers=headers)
                light.append({"start": start, "end": perf_counter(), "status": result.status_code})
                result.raise_for_status()
        except Exception as error:
            errors.append(str(error))
    sampler = Thread(target=sample, name="pending-np-light-request")
    first = len(probe.records)
    sampler.start()
    try:
        gate.wait(timeout=5)
        start = perf_counter()
        result = client.request(method, path, headers=headers, json=body)
        end = perf_counter()
        elapsed = (end - start) * 1000
    finally:
        finished.set()
        sampler.join(timeout=5)
    if sampler.is_alive():
        raise RuntimeError("Light-request sampler failed to finish")
    locks = [row for row in probe.records[first:] if row["nesting"] == 0]
    recording = [row for row in locks if row["phase"] in {"pending_native", "pending_legacy"}]
    return result, {"status": result.status_code, "route_ms": elapsed,
        "baseline_light_ms": baseline_ms,
        "light_ms": [(row["end"] - row["start"]) * 1000 for row in light],
        "recording_lock_ms": [row["hold_ms"] for row in recording],
        "recording_wait_ms": [row["wait_ms"] for row in recording],
        "other_lock_ms": [row["hold_ms"] for row in locks if row not in recording],
        "light_lock_wait_ms": [row["wait_ms"] for row in locks if row["phase"] == "light_request"],
        "overlapping_light_requests": sum(any(row["start"] <= lock["ended"] and lock["entered"] <= row["end"]
            for lock in recording) for row in light), "response_bytes": len(result.content), "errors": errors,
        **({"diagnostics": diagnostics.window(start, end, recording, light)} if diagnostics is not None else {})}


def prepare_retained(client, doc, design, count):
    headers = {"X-NADOC-Doc": doc}
    token = set_current_doc(doc)
    try:
        state.load_design(design)
    finally:
        reset_current_doc(token)
    if count:
        response = client.post(PATH, headers=headers, json={"strand_id": design.nanoparticle_conjugations[0].surface_strands[0].strand_id,
            "overhang_id": next(item.id for item in design.overhangs if not item.auxiliary_endpoint),
            "expected_revision": revision(doc), "name": "Retained candidate"})
        response.raise_for_status()
        version_id = response.json()["version_id"]
        for index in range(count - 1):
            response = client.patch(f"{PATH}/{version_id}", headers=headers,
                json={"expected_revision": revision(doc), "name": f"Retained candidate {index + 1}"})
            response.raise_for_status()
    token = set_current_doc(doc)
    try:
        return state.get_or_404().model_copy(deep=True)
    finally:
        reset_current_doc(token)


def summarize(report):
    """Retain timing evidence even when a later capture or worker refuses."""
    actions = ("create", "rename", "move", "resize", "delete") if report.get("motion") else ("create", "rename", "delete")
    for action in actions:
        samples = [row for row in report.get("samples", []) if row["action"] == action]
        report[action] = {"route": stats([row["route_ms"] for row in samples]),
            **{key: stats([value for row in samples for value in row[key]]) for key in
               ("recording_lock_ms", "recording_wait_ms", "light_ms", "light_lock_wait_ms")}}


def measure(client, doc, report, repeats, probe, handles, retained, mode, background, diagnostics=None, *, motion=False):
    report["active_phase"] = "fixture_preparation"
    template = prepare_retained(client, doc, prefix(handles, background=background), retained)
    report["active_phase"] = "template_node_byte_admission"
    admit(template)  # Same node/byte profile; no source copying or extra allowance.
    if mode == "native" and not native._bounded(template):
        raise RuntimeError("Declared native background exceeds reference admission")
    expected_rows = len(template.feature_log)
    report.update(handles=handles, retained_rows=expected_rows, mode=mode, background=background, motion=motion,
        native_capture_node_byte_admission=True, helices=len(template.helices),
        strands=len(template.strands), domains=sum(len(item.domains) for item in template.strands),
        declared_bp=sum(item.length_bp for item in template.helices), samples=[], errors=[])
    captured = None
    expected_steps = 5 if motion else 3
    move = {"pivot": [2., -1., 3.], "translation": [1., 3., -2.], "rotation": [0., 0., .6, .8]}
    if motion:
        from backend.core.nanoparticle import replace_gold_nanosphere
        from backend.core.part_history_proof import AUTHORING_FIELDS

        expected = replace_gold_nanosphere(template, "gold", gizmo_move=move)
        expected = replace_gold_nanosphere(expected, "gold", diameter_nm=14.)
        expected_authoring = expected.model_dump(mode="json", include=AUTHORING_FIELDS)
    for iteration in range(repeats):
        report["active_phase"] = "route_lifecycle"
        token = set_current_doc(doc)
        try:
            state.load_design(template.model_copy(deep=True))
            start_revision, start_depth = state.revision(), state.undo_depth()
        finally:
            reset_current_doc(token)
        body = {"strand_id": template.nanoparticle_conjugations[0].surface_strands[0].strand_id,
            "overhang_id": next(item.id for item in template.overhangs if not item.auxiliary_endpoint),
            "expected_revision": start_revision, "name": "Measured candidate"}
        result, timing = timed_request(client, doc, probe, "POST", PATH, body, diagnostics=diagnostics)
        report["samples"].append({"iteration": iteration, "action": "create", **timing})
        result.raise_for_status()
        version_id = result.json()["version_id"]
        result, timing = timed_request(client, doc, probe, "PATCH", f"{PATH}/{version_id}",
            {"expected_revision": start_revision + 1, "name": "Measured rename"}, diagnostics=diagnostics)
        report["samples"].append({"iteration": iteration, "action": "rename", **timing})
        result.raise_for_status()
        if motion:
            for action, patch in (("move", {"gizmo_move": move}), ("resize", {"diameter_nm": 14.})):
                result, timing = timed_request(client, doc, probe, "PATCH", "/api/design/nanoparticles/gold",
                                               patch, diagnostics=diagnostics)
                report["samples"].append({"iteration": iteration, "action": action, **timing})
                result.raise_for_status()
        result, timing = timed_request(client, doc, probe, "DELETE",
            f"{PATH}/{version_id}?expected_revision={start_revision + expected_steps - 1}", diagnostics=diagnostics)
        report["samples"].append({"iteration": iteration, "action": "delete", **timing})
        result.raise_for_status()
        token = set_current_doc(doc)
        try:
            design = state.get_or_404()
            suffix = design.feature_log[-expected_steps:]
            connection_rows = [suffix[index] for index in ((0, 1, 4) if motion else (0, 1, 2))]
            correct = (state.revision() == start_revision + expected_steps and state.undo_depth() == start_depth + expected_steps
                and len(design.feature_log) == expected_rows + expected_steps
                and design.nanoparticle_connection_versions == template.nanoparticle_connection_versions
                and all(("nanoparticle_connection_version" in row.params) == (mode == "native")
                        for row in connection_rows))
            if motion:
                correct = correct and design.model_dump(mode="json", include=AUTHORING_FIELDS) == expected_authoring
                correct = correct and all(("thiol_version" in row.params) == (mode == "native") for row in suffix[2:4])
                if mode == "native":
                    selected = [item.id for item in template.nanoparticle_connection_versions] + [version_id]
                    correct = correct and all(row.params.get("pending_connection_version_ids") == selected for row in suffix[2:4])
            else:
                correct = correct and (design.nanoparticle_conjugations == template.nanoparticle_conjugations
                    and design.helices == template.helices and design.strands == template.strands)
            if not correct:
                report["errors"].append({"iteration": iteration, "publication_mismatch": True})
            report["samples"][-1]["correct_lifecycle"] = correct
            report["recovery_bytes"] = sum(len(getattr(row, key, "") or "") for row in design.feature_log
                for key in ("design_snapshot_gz_b64", "post_state_gz_b64"))
            if captured is None and mode == "native":
                captured = design.model_copy(deep=True)
            # Undo/redo is verified outside timing, including actual recovery.
            state.undo()
            assert any(item.id == version_id for item in state.get_or_404().nanoparticle_connection_versions)
            state.redo()
            assert all(item.id != version_id for item in state.get_or_404().nanoparticle_connection_versions)
        finally:
            reset_current_doc(token)
    summarize(report)
    if captured is not None:
        for row in captured.feature_log:
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
        report["active_phase"] = "cold_capture"
        capture_started = perf_counter()
        report["cold_capture"] = {"status": "interrupted"}
        try:
            isolated = capture(captured)
            report["cold_capture"] = {"status": "admitted"}
        except Exception as error:
            report["cold_capture"] = {"status": "refused", "exception": type(error).__name__,
                                      "detail": str(error)}
            raise
        finally:
            report["cold_capture"].update(elapsed_ms=(perf_counter() - capture_started) * 1000,
                cooperative_seconds=0.025, nodes=30_000, bytes=2_000_000, private_input=True)
        report["active_phase"] = "cold_transport"
        report["cold_input_pickle_bytes"] = len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL))
        worker = VerificationWorker(isolated)
        report["active_phase"] = "cold_worker"
        start = perf_counter()
        try:
            worker.start()
            ready = worker.wait(5)
            report["cold_result"] = worker.result() if ready else {"status": "timeout"}
            report["cold_ms"] = (perf_counter() - start) * 1000
            if report["cold_result"]["status"] != "verified":
                report["errors"].append({"cold_replay": report["cold_result"]})
        finally:
            worker.close()
    report["active_phase"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=("native", "legacy", "both"), default="both")
    parser.add_argument("--diagnostics", action="store_true",
                        help="Record bounded GC overlap and native admission leaf timings; no GC policy changes")
    parser.add_argument("--motion", action="store_true",
                        help="Add pending move/resize lifecycle cells while retaining all baseline cells")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be between 1 and 30")
    doc = f"__pending_np_benchmark_{uuid4()}"
    originals = state._lock, native.try_record, state.mutate_with_feature_log, thiol.native_route_eligible
    probe = LockProbe(originals[0])
    state._lock = probe
    state.mutate_with_feature_log = phase_wrapper(originals[2], "pending_legacy")
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")
    @app.get(LIGHT)
    def light():
        token = _PHASE.set("light_request")
        try:
            return {"revision": state.revision()}
        finally:
            _PHASE.reset(token)
    cases, failure = [], None
    diagnostics = Diagnostics() if args.diagnostics else None
    try:
        if diagnostics is not None:
            diagnostics.install()
        with TestClient(app) as client:
            for mode in (("native", "legacy") if args.mode == "both" else (args.mode,)):
                native.try_record = (phase_wrapper(originals[1], "pending_native") if mode == "native"
                                     else lambda *_args, **_kwargs: None)
                thiol.native_route_eligible = originals[3] if mode == "native" else lambda *_args: False
                state.mutate_with_feature_log = phase_wrapper(originals[2], "pending_" + mode)
                selected = [(handles, retained, "six-cell") for handles in (1, 16) for retained in (0, 16)]
                selected.append((16, 16, "64-cell-126bp"))
                selected = [(handles, retained, background, moving) for moving in ((False, True) if args.motion else (False,))
                            for handles, retained, background in selected]
                for handles, retained, background, moving in selected:
                    report = {"case": f"{mode}-{handles}-handles-{retained}-retained-{background}" + ("-motion" if moving else ""),
                              "motion": moving}
                    cases.append(report)
                    try:
                        measure(client, doc, report, args.repeats, probe, handles, retained, mode, background, diagnostics, motion=moving)
                        report["completed"] = True
                    except Exception as error:
                        # Each next case installs a fresh private native prefix.
                        # Keep over-scope/background failures without losing the
                        # remaining native/compatibility comparison evidence.
                        report["completed"] = False
                        report["failure"] = {"phase": report.get("active_phase"),
                            "exception": type(error).__name__, "detail": str(error)}
                        report.setdefault("errors", []).append(report["failure"])
                    finally:
                        summarize(report)
    except Exception as error:
        failure = {"case": cases[-1]["case"] if cases else None,
                   "exception": type(error).__name__, "detail": str(error)}
    finally:
        if diagnostics is not None:
            diagnostics.close()
        state.drop_doc(doc)
        state._lock, native.try_record, state.mutate_with_feature_log, thiol.native_route_eligible = originals
    clean = doc not in state.revision_map()
    errors = any(item.get("errors") or any(row["errors"] for row in item.get("samples", [])) for item in cases)
    print(json.dumps({"scope": "Actual pending NP HTTP create/rename/delete; optional native move/resize, no application solver",
        "notes": ["Compatibility baseline bypasses only the new native adapter; same current process and endpoints.",
            "Native owner/target prefix and retained rows are built before measurement, never copied from candidate geometry.",
            "The larger background is a 64-cell, 126bp native bundle plus 16 thiol handles and 16 retained candidate rows.",
            "Every measured template must pass unchanged ordinary node/byte admission; no fixture shrinking or retries.",
            "Common recovery and metadata reconciliation remain inside the existing recording lock.",
            "No source proof is required for UI recording; fresh-worker proof is measured once per native case afterward.",
            "Optional motion adds two atomic rows before deletion; its geometry oracle uses unchanged native replacement outside timing.",
            "Diagnostic event limits apply to the whole run, including extra motion cells; dropped counts remain explicit.",
            "No limits, GC policy, physics, retry behavior or production sessions are changed."],
        "repeats": args.repeats, "all_cases_attempted": failure is None,
        "diagnostics": None if diagnostics is None else {
            "scope": "Benchmark-only correlation; all GC policy and runtime limits unchanged",
            "event_limit_per_family": MAX_DIAGNOSTIC_EVENTS,
            "gc_events": len(diagnostics.gc_events), "stage_events": len(diagnostics.stages),
            "dropped_gc_events": diagnostics.dropped_gc, "dropped_stage_events": diagnostics.dropped_stages},
        "completed": failure is None and all(item.get("completed", False) for item in cases),
        "correctness_verified": failure is None and not errors and clean,
        "latency_qualified": False,
        "latency_status": "Unqualified: this harness records timings but applies no latency acceptance threshold.",
        "exit_status_basis": "Correctness and cleanup only; a zero exit does not qualify latency.",
        "failure": failure, "failed_cases": [item["case"] for item in cases if item.get("errors")],
        "session_cleanup_verified": clean, "cases": cases}, indent=2))
    return int(failure is not None or errors or not clean)


if __name__ == "__main__":
    raise SystemExit(main())
