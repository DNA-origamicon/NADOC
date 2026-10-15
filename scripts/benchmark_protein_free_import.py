#!/usr/bin/env python3
"""Serial memory-only qualification of the ordinary native free-import route.

No files, molecular simulations or production sessions are written. Measures
actual HTTP, one native parse, shared-lock capture/publication, recovery, and
concurrent light requests under unchanged ordinary admission limits.
"""

import argparse
import gc
import json
import pickle
from threading import Barrier, Event, Thread, get_ident
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_protein_import_recording as recording
from backend.api import routes_design_interchange as routes, state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_verification_worker import VerificationWorker
from backend.core import protein
from backend.core.models import Annotation, CameraPose, Design, Domain, Helix, Strand, Vec3
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_verification_capture import capture
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats


PATH = "/api/design/import/pdb-auto"
LIGHT = "/__benchmark__/revision"


class GCProbe:
    """Observe collection intervals without collecting or changing GC policy."""

    def __init__(self):
        self.events, self.active, self.dropped = [], {}, 0
        self.initial_policy = {"enabled": gc.isenabled(), "thresholds": gc.get_threshold()}

    def callback(self, phase, info):
        key = (get_ident(), info["generation"])
        if phase == "start":
            self.active[key] = (perf_counter(), _PHASE.get())
            return
        started = self.active.pop(key, None)
        if started is None:
            return
        ended = perf_counter()
        if len(self.events) >= 10_000:
            self.dropped += 1
            return
        self.events.append({"thread": key[0], "generation": key[1], "phase": started[1],
            "start": started[0], "end": ended, "elapsed_ms": (ended - started[0]) * 1000,
            "collected": info["collected"], "uncollectable": info["uncollectable"]})


def overlap(left, right):
    return left["start"] <= right["end"] and right["start"] <= left["end"]


def pdb(count, *, dense=False, pad=0):
    # Original text is the input; no generated candidate is used as a source.
    text = "REMARK synthetic bounded import qualification\n"
    for index in range(count):
        x = 0.0 if dense else (index % 25) * 3.0
        y = 0.0 if dense else (index // 25) * 3.0
        text += (f"ATOM  {index + 1:5d}  CA  ALA A{index + 1:4d}    "
                 f"{x:8.3f}{y:8.3f}{0.:8.3f}  1.00  0.00           C\n")
    text += "END\n"
    return text + (" " * max(0, pad - len(text.encode())))


def initial(with_dna=False):
    if not with_dna:
        return create_empty_part("Native protein benchmark", "HONEYCOMB")
    # Ordinary rootless DNA remains a rootless document after this native
    # suffix. This deliberately measures the compatibility path without proof.
    return Design(helices=[Helix(id="retained", length_bp=42,
        axis_start=Vec3(x=0., y=0., z=0.), axis_end=Vec3(x=0., y=0., z=14.28))], strands=[Strand(id="retained-scaffold",
        strand_type="scaffold", domains=[Domain(helix_id="retained", start_bp=0, end_bp=41,
                                                direction="FORWARD")])])


def retained_profile(client, doc, profile):
    """Build retained recipes through actual HTTP imports, outside sample timing.

    Repeated source actions keep separate asset/placement identities. No prior
    feature receipt or parsed atom set is fabricated to bypass admission.
    """
    counts = {"empty": (), "retained-same-source": (128,), "retained-new-source": (128,),
              "retained-metadata": (128,), "repeated-imports": (32,) * 8,
              "retained-1000-atoms": (1000,), "aggregate-node-refusal": (1000, 1000)}[profile]
    summaries = []
    for index, count in enumerate(counts):
        token = set_current_doc(doc)
        try:
            revision = state.revision()
        finally:
            reset_current_doc(token)
        response = client.post(PATH, headers={"X-NADOC-Doc": doc}, json={"content": pdb(count),
            "name": f"retained-{index}.pdb", "operation_id": str(uuid4()), "expected_revision": revision})
        if response.status_code != 200:
            raise RuntimeError(f"Retained fixture {profile} import {index} refused: {response.status_code} {response.text[:2000]}")
        summaries.append({"source_atom_records": count, "feature_ids": response.json()["recipe_recording"]["feature_ids"]})
    if profile == "retained-metadata":
        token = set_current_doc(doc)
        try:
            design = state.get_or_404()
            source = describe(b"unpublished replacement source\n" * 128,
                              format="blob", media_type="application/octet-stream")
            draft = RepairDraft.model_validate({"version": 1, "draft_id": "benchmark-retained-proposal",
                "generation": 0, "base_design_id": design.id, "base": {"version": 1,
                "root_sha256": "a" * 64, "commands_sha256": "b" * 64, "sources_sha256": "c" * 64},
                "repair_version": 1, "actions": [{"action": "set_input", "feature_id": design.feature_log[0].id,
                "parameter_path": ["name"], "expected_old": "retained-0.pdb", "value": "Proposed name"}]})
            state.load_design(design.copy_with(
                annotations=[Annotation(text=f"Retained annotation {index}: " + "x" * 1970) for index in range(20)],
                camera_poses=[CameraPose()], repair_draft=draft,
                input_sources={**design.input_sources, source.sha256: embed(source, b"unpublished replacement source\n" * 128)}))
        finally:
            reset_current_doc(token)
    return summaries


def measure(client, doc, name, raw, repeats, probe, parses, gc_probe, capture_spans,
            *, with_dna=False, expect=200, profile="empty"):
    rows, errors, captured_part = [], [], None
    for iteration in range(repeats):
        token = set_current_doc(doc)
        try:
            state.load_design(initial(with_dna))
            library_before_setup = set(state._protein_library)
        finally:
            reset_current_doc(token)
        setup = retained_profile(client, doc, profile)
        token = set_current_doc(doc)
        try:
            source, revision, depth = state.get_or_404(), state.revision(), state.undo_depth()
            before = source.model_dump_json()
            library = set(state._protein_library)
            before_rows, before_assets = len(source.feature_log), len(source.protein_assets)
            before_placements = len(source.protein_attachments)
            incoming_digest = describe(raw.encode(), format="pdb", media_type="chemical/x-pdb").sha256
            expected_sources = set(source.input_sources) | {incoming_digest}
        finally:
            reset_current_doc(token)
        headers = {"X-NADOC-Doc": doc}
        first_gc, first_span = len(gc_probe.events), len(capture_spans)
        baseline_started = perf_counter()
        baseline = client.get(LIGHT, headers=headers)
        baseline_ms = (perf_counter() - baseline_started) * 1000
        baseline.raise_for_status()
        gate, finished = Barrier(2), Event()
        requests = []
        def light_requests():
            gate.wait(timeout=5)
            for _ in range(256):
                if finished.is_set():
                    break
                begin = perf_counter()
                try:
                    response = client.get(LIGHT, headers=headers)
                except Exception as error:
                    errors.append({"iteration": iteration, "light_request_exception": str(error)})
                    break
                requests.append({"start": begin, "end": perf_counter(), "status": response.status_code})
        sampler = Thread(target=light_requests, name="protein-import-light-requests")
        first_lock, first_parse = len(probe.records), len(parses)
        sampler.start()
        try:
            gate.wait(timeout=5)
            begin = perf_counter()
            response = client.post(PATH, headers=headers, json={"content": raw, "name": name,
                "operation_id": str(uuid4()), "expected_revision": revision})
            route_ended = perf_counter()
            route_ms = (route_ended - begin) * 1000
        finally:
            finished.set()
            sampler.join(timeout=5)
        if sampler.is_alive():
            raise RuntimeError("Benchmark light-request sampler did not finish")
        token = set_current_doc(doc)
        try:
            design = state.get_or_404()
            success = response.status_code == 200
            correct = (response.status_code == expect and (
                (len(design.feature_log) == before_rows + 2 and len(design.protein_assets) == before_assets + 1
                 and len(design.protein_attachments) == before_placements + 1 and state.revision() == revision + 1
                 and state.undo_depth() == depth + 1 and design.recipe_root == source.recipe_root
                 and design.feature_log[:-2] == source.feature_log
                 and design.protein_assets[:-1] == source.protein_assets
                 and design.protein_attachments[:-1] == source.protein_attachments
                 and design.annotations == source.annotations and design.camera_poses == source.camera_poses
                 and design.repair_draft == source.repair_draft
                 and set(design.input_sources) == expected_sources
                 and all(design.input_sources[key] == value for key, value in source.input_sources.items())
                 and set(state._protein_library) == library | {design.protein_assets[-1].id})
                if success else (design.model_dump_json() == before and state.revision() == revision
                                 and state.undo_depth() == depth and set(state._protein_library) == library)))
            if not correct:
                errors.append({"iteration": iteration, "status": response.status_code, "detail": response.text[:2000]})
            if success and not with_dna and captured_part is None:
                captured_part = Design.from_json(design.to_json())
            payload = response.json()
            recovery = sum(len(getattr(row, key, "") or "") for row in design.feature_log
                           for key in ("design_snapshot_gz_b64", "post_state_gz_b64"))
            records = [item for item in probe.records[first_lock:] if item["nesting"] == 0]
            locks = {phase: [item for item in records if item["phase"] == phase]
                     for phase in ("source_capture", "publication")}
            overlaps = sum(any(request["start"] <= lock["ended"] and lock["entered"] <= request["end"]
                               for lock in locks["publication"]) for request in requests)
            candidate_spans = [span for span in capture_spans[first_span:]
                               if span["phase"] == "candidate_admission"]
            comparisons = {phase: [{"start": item["entered"], "end": item["ended"]} for item in spans]
                           for phase, spans in locks.items()}
            comparisons["candidate_admission"] = candidate_spans
            collections = [{**event, "overlaps": {phase: any(overlap(event, span) for span in spans)
                                                  for phase, spans in comparisons.items()}}
                           for event in gc_probe.events[first_gc:]
                           if overlap(event, {"start": begin, "end": route_ended})]
            rows.append({"status": response.status_code, "correct": correct, "route_ms": route_ms,
                "baseline_light_ms": baseline_ms,
                "parser_calls": len(parses) - first_parse, "recovery_bytes": recovery,
                "atom_count": len(design.protein_assets[-1].atoms) if success else None,
                "bond_count": len(design.protein_assets[-1].bonds) if success else None,
                "retained_rows": before_rows, "retained_assets": before_assets,
                "result_rows": len(design.feature_log), "result_sources": len(design.input_sources),
                "result_atom_count": sum(len(asset.atoms) for asset in design.protein_assets),
                "retained_setup": setup,
                "error_detail": None if success else payload.get("detail"),
                "candidate_admission_spans": candidate_spans, "gc_collections": collections,
                "stages_ms": payload.get("process_metrics", {}).get("stages_ms", {}),
                "capture_ms": [item["hold_ms"] for item in locks["source_capture"]],
                "publication_ms": [item["hold_ms"] for item in locks["publication"]],
                "light_ms": [(item["end"] - item["start"]) * 1000 for item in requests],
                "publication_overlaps": overlaps})
            if any(item["status"] != 200 for item in requests):
                errors.append({"light_request_failure": True})
            parse_count = len(parses) - first_parse
            if parse_count > 1 or (success and parse_count != 1):
                errors.append({"iteration": iteration, "native_parser_count": parse_count})
            if success:
                # Outside all timed spans, verify the populated publication's
                # single undo includes retained metadata and source bytes.
                after = design.model_dump_json()
                state.undo()
                undo_ok = state.get_or_404().model_dump_json() == before
                state.redo()
                redo_ok = state.get_or_404().model_dump_json() == after
                rows[-1]["undo_redo_exact"] = undo_ok and redo_ok
                if not (undo_ok and redo_ok):
                    errors.append({"iteration": iteration, "undo_redo_exact": False})
            for identity in set(state._protein_library) - library_before_setup:
                state._protein_library.pop(identity, None)
        finally:
            reset_current_doc(token)
    cold = None
    if captured_part is not None:
        for row in captured_part.feature_log:
            row.design_snapshot_gz_b64 = row.post_state_gz_b64 = "poisoned recovery"
        try:
            isolated = capture(captured_part)
            size = len(pickle.dumps(isolated, protocol=pickle.HIGHEST_PROTOCOL))
            worker = VerificationWorker(isolated)
            begin = perf_counter()
            try:
                worker.start()
                ready = worker.wait(5)
                result = worker.result() if ready else {"status": "timeout"}
                cold = {"input_pickle_bytes": size, "elapsed_ms": (perf_counter() - begin) * 1000, "result": result}
                if result["status"] != "reproduced_import":
                    errors.append({"cold_replay_failed": result})
            finally:
                worker.close()
        except ValueError as error:
            errors.append({"cold_capture_or_transport_refused": str(error)})
    return {"name": name, "retained_profile": profile, "source_bytes": len(raw.encode()), "requested_atom_records": sum(
        line.startswith("ATOM  ") for line in raw.splitlines()), "expected_status": expect,
        "correct_transactions": sum(row["correct"] for row in rows), "errors": errors,
        "route": stats([row["route_ms"] for row in rows]),
        "capture_lock": stats([elapsed for row in rows for elapsed in row["capture_ms"]]),
        "publication_lock": stats([elapsed for row in rows for elapsed in row["publication_ms"]]),
        "candidate_admission": stats([row["stages_ms"]["native_candidate_admission"] for row in rows
                                      if "native_candidate_admission" in row["stages_ms"]]),
        "candidate_admission_all_attempts": stats([span["elapsed_ms"] for row in rows
                                                   for span in row["candidate_admission_spans"]]),
        "gc_during_requests": stats([event["elapsed_ms"] for row in rows for event in row["gc_collections"]]),
        "baseline_light_requests": stats([row["baseline_light_ms"] for row in rows]),
        "light_requests": stats([elapsed for row in rows for elapsed in row["light_ms"]]),
        "publication_overlap_count": sum(row["publication_overlaps"] for row in rows),
        "cold": cold, "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--suite", choices=("all", "boundaries", "retained"), default="all",
                        help="Run retained-state publication cases, original boundaries, or both")
    parser.add_argument("--case", help="Restrict the selected suite to one exact case name for diagnosis")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 30:
        parser.error("repeats must be between 1 and 30")
    doc = f"__protein_import_benchmark_{uuid4()}__"
    originals = (state._lock, recording.capture_import, recording.publish_import, protein.parse_protein_pdb,
                 recording.prepare_import, recording.capture, routes.NATIVE_FREE_IMPORT_ENABLED, recording.admit)
    probe, parses = LockProbe(originals[0]), []
    gc_probe, capture_spans = GCProbe(), []
    state._lock = probe
    routes.NATIVE_FREE_IMPORT_ENABLED = True  # Private qualification; production gate stays closed.
    recording.capture_import = phase_wrapper(originals[1], "source_capture")
    recording.publish_import = phase_wrapper(originals[2], "publication")
    recording.prepare_import = phase_wrapper(originals[4], "native_preparation")

    def tracked_admission(operation, phase):
        def tracked(*args, **kwargs):
            token, begin, completed = _PHASE.set(phase), perf_counter(), False
            try:
                result = operation(*args, **kwargs)
                completed = True
                return result
            finally:
                ended = perf_counter()
                capture_spans.append({"phase": phase, "start": begin, "end": ended,
                                      "elapsed_ms": (ended - begin) * 1000, "completed": completed})
                _PHASE.reset(token)
        return tracked

    recording.capture = tracked_admission(originals[5], "source_capture")
    recording.admit = tracked_admission(originals[7], "candidate_admission")
    def count_parse(*args, **kwargs):
        parses.append(True)
        token = _PHASE.set("native_parse")
        try:
            return originals[3](*args, **kwargs)
        finally:
            _PHASE.reset(token)
    protein.parse_protein_pdb = count_parse
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(routes.router, prefix="/api")
    @app.get(LIGHT)
    def revision():
        token = _PHASE.set("light_request")
        try:
            return {"revision": state.revision()}
        finally:
            _PHASE.reset(token)
    cases, run_failure, current_case = [], None, None
    original_library = dict(state._protein_library)
    gc_callback = gc_probe.callback
    gc.callbacks.append(gc_callback)
    try:
        with TestClient(app) as client:
            boundaries = [
                ("small-original-source", pdb(9), False, 200, "empty"),
                ("existing-rootless-DNA", pdb(9), True, 200, "empty"),
                ("1000-atom-record-boundary", pdb(1000), False, 200, "empty"),
                ("250KB-source-boundary", pdb(9, pad=250_000), False, 200, "empty"),
                ("dense-100-atom-bond-refusal", pdb(100, dense=True), False, 413, "empty")]
            retained = [
                ("retained-protein-same-source", pdb(128), False, 200, "retained-same-source"),
                ("retained-protein-new-source", pdb(256), False, 200, "retained-new-source"),
                ("retained-presentation-and-proposal", pdb(128), False, 200, "retained-metadata"),
                ("eight-real-imports-then-ninth", pdb(32), False, 200, "repeated-imports"),
                ("retained-1000-atoms-plus-1000", pdb(1000), False, 200, "retained-1000-atoms"),
                ("retained-2000-atoms-plus-1000-refusal", pdb(1000), False, 413, "aggregate-node-refusal")]
            selected = boundaries if args.suite == "boundaries" else retained if args.suite == "retained" else boundaries + retained
            if args.case:
                selected = [case for case in selected if case[0] == args.case]
                if not selected:
                    raise ValueError("Requested case is not in the selected suite")
            for name, raw, dna, expect, profile in selected:
                current_case = name
                cases.append(measure(client, doc, name, raw, args.repeats, probe, parses, gc_probe, capture_spans,
                                     with_dna=dna, expect=expect, profile=profile))
    except Exception as error:
        # Preserve completed case evidence on a later fixture/transport fault.
        # An interrupted run is not a successful full qualification.
        run_failure = {"case": current_case, "exception": type(error).__name__, "detail": str(error)}
    finally:
        state.drop_doc(doc)
        state._protein_library.clear()
        state._protein_library.update(original_library)
        (state._lock, recording.capture_import, recording.publish_import, protein.parse_protein_pdb,
         recording.prepare_import, recording.capture, routes.NATIVE_FREE_IMPORT_ENABLED, recording.admit) = originals
        gc.callbacks.remove(gc_callback)
    leaked = doc in state.revision_map()
    print(json.dumps({"scope": "Actual ordinary free protein HTTP import; original bytes, native suffix, one undo/revision/library publication",
        "repeats": args.repeats, "suite": args.suite, "case": args.case,
        "experimental_host_gate_enabled_for_run": True,
        "gc_observation": {"policy": gc_probe.initial_policy, "events": gc_probe.events,
                           "dropped_events": gc_probe.dropped,
                           "policy_unchanged": gc_probe.initial_policy == {
                               "enabled": gc.isenabled(), "thresholds": gc.get_threshold()}},
        "limits_unchanged": {"capture_nodes": 30_000, "capture_bytes": 2_000_000,
            "capture_seconds_cooperative": 0.025, "recovery_bytes": 8_000_000},
        "candidate_admission": {"isolated_copy": False, "same_node_byte_accounting": True,
                                "separate_deadline": False, "private_input_only": True},
        "notes": ["Synthetic sources qualify size/work boundaries, not molecular realism.",
            "Retained heavy physical/loadout state is outside this initial native ordinary-import slice.",
            "No full-prefix proof is performed on import; cold proof is measured separately afterward.",
            "Experimental native import is explicitly enabled only in this harness and restored on exit.",
            "GC callbacks observe intervals only; no collect(), disable(), threshold changes or retries are used.",
            "Private candidate resource admission has no second isolation copy/deadline; source capture keeps its 25 ms allowance.",
            "Library remains a cache; no replay source is reconstructed from its atoms.",
            "Retained recipes are created by real HTTP imports before timing; all preparation failures stop qualification.",
            "Repeated imports verify unchanged prefix/assets/proposals/source bytes and exact single undo/redo outside timing.",
            "Aggregate atom-limit refusal preserves the existing design, history, revision and library.",
            "Publication lock instrumentation includes nested state helpers; only outermost spans are counted.",
            "Legacy metadata formatting may infer zero bonds again; parser counts distinguish native parse repetition."],
        "session_cleanup_verified": not leaked, "completed": run_failure is None,
        "run_failure": run_failure, "cases": cases}, indent=2))
    return int(leaked or run_failure is not None
               or any(item["errors"] or item["correct_transactions"] != args.repeats for item in cases))


if __name__ == "__main__":
    raise SystemExit(main())
