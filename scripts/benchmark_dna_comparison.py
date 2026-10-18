#!/usr/bin/env python3
"""Memory-only native DNA comparison qualification; root runs serially.

No app lifespan, files, browser, physical engine or user sessions. The script
prints compact JSON only. Native fixture derivation is software display geometry.
Version two is enabled only in this isolated benchmark process and restored on
exit; the production host gate remains false. All actual admission limits stay
unchanged. GPU/renderer construction is a separate, still-unqualified increment.
"""

import argparse
from collections import Counter
import json
import pickle
import resource
from threading import Barrier, Event, Thread
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import doc_context, part_evaluation_comparison as owner, part_evaluation_jobs as jobs, state
from backend.api.part_evaluation import evaluate
from backend.api.part_proof_commands import execute
from backend.api.part_revision_status import revision_status
from backend.api.part_verification_worker import _result_bytes
from backend.api.routes_feature_log import router
from backend.core.part_command_errors import CommandContractError
from backend.core.part_comparison_projection import compare
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.part_history_contract import create_empty_part
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from backend.core.part_verification_capture import CaptureLimit, capture
from scripts.benchmark_cadnano_route import LockProbe, phase_wrapper, stats
from tests.conftest import make_minimal_design
from tests.test_part_comparison_projection import asset_part
from tests.test_part_dna_comparison import small
from tests.test_part_recipe_repair import row, set_input


PATH = "/api/design/features/evaluation/jobs"
REVISION = "/__benchmark__/revision"


def timed(callback):
    started = perf_counter()
    value = callback()
    return value, (perf_counter() - started) * 1000


def fixtures():
    for kind in ("straight", "loops", "bend", "sweep", "overhang", "child"):
        yield kind, small(kind)
    yield "1024-prospective-slots", make_minimal_design(helix_length_bp=512)
    design = small("overhang")
    assets = asset_part()
    design.nanoparticles, design.protein_assets, design.protein_attachments = assets.nanoparticles, assets.protein_assets, assets.protein_attachments
    yield "mixed-free-assets", design
    design = small("sweep")
    design.helices[0].length_bp = 100_000_000
    yield "oversized-empty-helix-refusal", design.model_copy(update={"strands": []})


def warm_case(name, source, repeats):
    candidate = source.model_dump(mode="json")
    rows = []
    for _ in range(repeats):
        row_data = {}
        try:
            isolated, row_data["capture_ms"] = timed(lambda: capture(source, preserve_entry_types=True))
            payload = {"source": isolated, "candidate": candidate, "projection_version": 2}
            row_data["worker_pickle_bytes"] = len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
            result, row_data["derive_two_panes_ms"] = timed(lambda: compare(isolated, candidate, projection_version=2))
            raw, row_data["encode_ms"] = timed(lambda: json.dumps(result, separators=(",", ":"), allow_nan=False).encode())
            row_data["prospective_result_bytes"] = len(raw)
            # Explain the previous short-ID versus UUID fixture size gap without
            # dropping any data or raising the existing shared result ceiling.
            expanded = {**result, **{side: {**result[side], "dna": {**result[side]["dna"],
                "nucleotides": unpack_records(result[side]["dna"]["nucleotides"])}}
                for side in ("published", "proposed")}}
            row_data["full_object_result_bytes"] = len(json.dumps(expanded, separators=(",", ":"), allow_nan=False).encode())
            bounded = json.loads(_result_bytes(result))
            row_data["status"] = bounded["status"]
            if bounded.get("issues"):
                row_data["code"] = bounded["issues"][0]["code"]
            row_data["projected_sites_per_pane"] = len(result["published"]["dna"]["nucleotides"])
        except CaptureLimit as error:
            row_data.update(status="capture_limit", detail=str(error))
        except CommandContractError as error:
            row_data.update(status="refused", code=error.code, detail=str(error))
        rows.append(row_data)
    return {"case": name, "status_counts": dict(Counter(row["status"] for row in rows)),
        "capture": stats([row["capture_ms"] for row in rows if "capture_ms" in row]),
        "derive_two_panes": stats([row["derive_two_panes_ms"] for row in rows if "derive_two_panes_ms" in row]),
        "encode": stats([row["encode_ms"] for row in rows if "encode_ms" in row]), "samples": rows}


def native_recipe(length, helix_count):
    cells = [(0, 0), (0, 1), (1, 1), (1, 2), (1, 3), (0, 3)][:helix_count]
    params = {"_proof_version": 1, "history_seed": "2647c76b-9fe1-4407-9268-e9c33e36d881",
        "nominal_length_bp": length, "tracks": [{"key": str(index), "cell": list(cell),
            "intervals": [{"key": "body", "lo_bp": 0, "hi_bp": length - 1}]} for index, cell in enumerate(cells)]}
    design = execute("branch-seed", create_empty_part("Comparison benchmark", "HONEYCOMB"), params)
    design.feature_log = [row("seed", "branch-seed", params)]
    design.repair_draft = RepairDraft.model_validate({"version": 1, "draft_id": "benchmark-proposal", "generation": 0,
        "base_design_id": design.id, "base": repair_base_fingerprint(design).model_dump(mode="json"),
        "repair_version": 1, "actions": [set_input("seed", ["tracks", 0, "intervals", 0, "hi_bp"], length - 1, length - 2)]})
    return design


def prepare(doc, length, helix_count):
    token = doc_context.set_current_doc(doc)
    try:
        source = native_recipe(length, helix_count)
        state.load_design(source)
        revision = state.revision()
        admitted = jobs.start({"operation": "repair", "expected_revision": revision,
            "repair": {"repair_version": 1, "expected_design_id": source.id, "expected_revision": revision,
                       "actions": [action.model_dump(mode="json") for action in source.repair_draft.actions]}})
        identity = admitted["job_id"]
        with jobs._lock:
            job = jobs._jobs[identity]
            if job.result is None or job.result.get("status") != "ready":
                raise RuntimeError(f"Benchmark repair setup failed: {job.result}")
        return source, identity, {"projection_version": 2, "expected_design_id": source.id,
            "expected_revision": revision, "expected_draft_id": source.repair_draft.draft_id, "expected_generation": 0}
    finally:
        doc_context.reset_current_doc(token)


def route_case(client, doc, name, length, helix_count, repeats, probe):
    rows = []
    source, identity, body = prepare(doc, length, helix_count)
    original = source.model_dump_json()
    # Outside timed requests: exact result sizes for the actual admitted recipe,
    # rather than a shorter-ID approximation from make_minimal_design.
    with jobs._lock:
        candidate = jobs._jobs[identity].result["candidate"]
    measured = warm_case("actual_recipe_size", source, 1)
    actual = compare(source, candidate, projection_version=2)
    actual_bytes = len(json.dumps(actual, separators=(",", ":"), allow_nan=False).encode())
    headers = {"X-NADOC-Doc": doc}
    for _ in range(repeats):
        start_index = len(probe.records)
        gate, finished = Barrier(2), Event()
        light = {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "last_completed_ms": None,
                 "deadline_reached": False}
        light_statuses, light_errors = Counter(), []

        def sample_revision():
            gate.wait(timeout=5)
            started = perf_counter()
            while not finished.is_set():
                if perf_counter() - started >= 5:
                    light["deadline_reached"] = True
                    break
                try:
                    response, elapsed = timed(lambda: client.get(REVISION, headers=headers))
                    light["count"] += 1
                    light["total_ms"] += elapsed
                    light["max_ms"] = max(light["max_ms"], elapsed)
                    light["last_completed_ms"] = (perf_counter() - started) * 1000
                    light_statuses[response.status_code] += 1
                except Exception as error:
                    light_errors.append(str(error))
                    break
                # Sample throughout the whole request, including parent decode/
                # response encoding. No early fixed-count cutoff or busy loop.
                finished.wait(.01)

        thread = Thread(target=sample_revision, name="dna-comparison-revision")
        thread.start()
        try:
            gate.wait(timeout=5)
            response, elapsed = timed(lambda: client.post(f"{PATH}/{identity}/comparison", json=body, headers=headers))
        finally:
            finished.set()
            thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Comparison benchmark revision reader did not stop")
        records = probe.records[start_index:]
        value = response.json()
        detail = value.get("detail")
        rows.append({"status": response.status_code, "code": detail.get("code") if isinstance(detail, dict) else detail,
            "route_ms": elapsed, "response_bytes": len(response.content), "light_request": {
                **light, "mean_ms": light["total_ms"] / light["count"] if light["count"] else None},
            "light_status_counts": dict(light_statuses), "light_errors": light_errors,
            "capture_lock": stats([item["hold_ms"] for item in records if item["phase"] == "comparison_capture"]),
            "all_lock_holds": stats([item["hold_ms"] for item in records]),
            "waits": stats([item["wait_ms"] for item in records]),
            "site_counts": [len(value[side]["dna"]["nucleotides"]) for side in ("published", "proposed")] if response.status_code == 200 else None})
    token = doc_context.set_current_doc(doc)
    try:
        unchanged = state.get_or_404() is source and source.model_dump_json() == original and state.revision() == body["expected_revision"] and state.undo_depth() == 0
        with jobs._lock:
            candidate_retained = jobs._jobs[identity].result.get("status") == "ready"
    finally:
        doc_context.reset_current_doc(token)
        with jobs._lock:
            job = jobs._jobs.pop(identity, None)
            if job is not None:
                job.cancelled.set()
    return {"case": name, "source_and_revision_unchanged": unchanged, "candidate_retained": candidate_retained,
        "actual_recipe_size": measured, "actual_candidate_result_bytes": actual_bytes,
        "status_counts": dict(Counter(row["status"] for row in rows)), "samples": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--http-repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 9 or not 1 <= args.http_repeats <= 9:
        parser.error("Use 1..9 repetitions")
    # Warm native geometry/encoding is a separate measurement from spawned HTTP
    # projection. The cold worker still sees independently captured input.
    warm = [warm_case(name, source, args.repeats) for name, source in fixtures()]
    doc = f"__benchmark_dna_comparison_{uuid4()}__"
    original_lock, original_capture, original_submit, original_gate = state._lock, owner._capture_source, jobs._submit, owner.DNA_COMPARISON_ENABLED
    probe = LockProbe(original_lock)
    application = FastAPI()
    application.add_middleware(doc_context.DocContextMiddleware)
    application.include_router(router, prefix="/api")
    application.add_api_route(REVISION, revision_status, methods=["GET"])

    def prepare_inline(job, captured, operation):
        # Setup is outside measured projection. Run the real repair evaluator
        # once; no forged candidate or extra worker catalog is introduced.
        try:
            job.result = evaluate(captured, operation)
            job.status = "complete"
        finally:
            jobs._slot.release()

    state._lock = probe
    owner._capture_source = phase_wrapper(original_capture, "comparison_capture")
    jobs._submit, owner.DNA_COMPARISON_ENABLED = prepare_inline, True
    routes, setup_errors = [], []
    try:
        with TestClient(application) as client:
            for name, length, count in (("tiny_recipe", 12, 1), ("boundary_recipe", 512, 1), ("six_helices", 84, 6)):
                try:
                    routes.append(route_case(client, doc, name, length, count, args.http_repeats, probe))
                except (HTTPException, RuntimeError) as error:
                    setup_errors.append({"case": name, "detail": str(error)})
    finally:
        with jobs._lock:
            for identity, job in list(jobs._jobs.items()):
                if job.doc == doc:
                    job.cancelled.set()
                    jobs._jobs.pop(identity, None)
        state.drop_doc(doc)
        state._lock, owner._capture_source = original_lock, original_capture
        jobs._submit, owner.DNA_COMPARISON_ENABLED = original_submit, original_gate
    cleaned = doc not in state.revision_map() and not any(job.doc == doc for job in jobs._jobs.values())
    transport_passed = not setup_errors and len(routes) == 3 and all(
        set(row["status_counts"]) == {200} and not any(sample["light_request"]["deadline_reached"]
            or sample["light_errors"] for sample in row["samples"]) for row in routes)
    print(json.dumps({"scope": "Native software display only; no physical validity, GPU or app qualification",
        "transport_admission_passed": transport_passed,
        "production_gate_unchanged": owner.DNA_COMPARISON_ENABLED is original_gate,
        "source_and_worker_limits_unchanged": True, "session_and_catalog_cleanup_verified": cleaned,
        "process_children_max_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "notes": ["The child RSS is the process-wide high-water child maximum on Linux, not a per-request measurement.",
            "Warm projection has no worker deadline; production HTTP uses the unchanged hard five-second process deadline.",
            "The HTTP recipe is prepared by the real repair evaluator outside measured time; each projection uses a fresh spawned worker.",
            "Refused/capture-busy/over-budget rows are retained without retry. No admission ceiling is raised.",
            "Revision sampling runs at 10 ms intervals until response completion or a five-second measurement deadline; count/mean/max and final sample time are reported without per-request arrays.",
            "Concurrent revision samples and lock instrumentation add overhead; these fixtures do not prove a universal latency bound."],
        "warm": warm, "http": routes, "setup_errors": setup_errors}, indent=2))
    return int(not cleaned or not transport_passed or any(not row["source_and_revision_unchanged"] or not row["candidate_retained"] for row in routes))


if __name__ == "__main__":
    raise SystemExit(main())
