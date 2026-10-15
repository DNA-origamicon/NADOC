#!/usr/bin/env python3
"""Measure registered batch capture, full-source undo and HTTP contention.

Run serially under the repository validation guard. No production lifespan,
workspace writer or scientific solver is used. The disabled batch gate is
temporarily opened only in this isolated harness process, then restored. No
capture, recovery, transport or command budget is enlarged or retried.
"""

import argparse
from contextlib import contextmanager
import json
from threading import Barrier, Event, Thread
from time import monotonic, perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5
from weakref import ref

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs, state
from backend.api import part_publication_permit as permits
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_evaluation import EvaluationRequest, evaluate
from backend.api.part_history_verification import _slot
from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES
from backend.api.part_verification_worker import VerificationWorker
from backend.api.routes_feature_log import router
from backend.core.models import Annotation, AtomisticReference, AtomisticReferenceAtom, Design
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, digest, import_root
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_verification_capture import CaptureLimit, capture
from scripts.benchmark_cadnano_route import LockProbe, _PHASE, phase_wrapper, stats


JOBS_PATH = "/api/design/features/evaluation/jobs"
REVISION_PATH = "/__benchmark__/revision"
STAMP = "2026-10-15T12:00:00Z"


def identity(name):
    return str(uuid5(NAMESPACE_URL, "nadoc:batch-benchmark:" + name))


def command(kind, **params):
    return {"kind": kind, "version": 1, "params": params}


def request(design, commands, revision=0):
    return {"operation": "batch", "batch": {"batch_version": 1,
        "expected_design_id": design.id, "expected_revision": revision, "commands": commands}}


def operation(design, commands, name):
    return {"request": request(design, commands), "header": {"identity": identity(name),
        "timestamp": STAMP, "source_revision": 0, "source_design_id": design.id}}


def prepare(name, design, commands):
    before = design.model_dump_json()
    begin = perf_counter()
    result = evaluate(design, operation(design, commands, name))
    elapsed = (perf_counter() - begin) * 1000
    if design.model_dump_json() != before:
        raise RuntimeError("Native batch changed its source")
    return {"name": name, "design": design, "commands": commands, "prepared": result,
            "separate_native_evaluation_ms": elapsed}


def candidate(case):
    if case["prepared"]["status"] != "ready":
        raise RuntimeError(f"Fixture failed: {case['name']}: {case['prepared']}")
    return Design.model_validate(case["prepared"]["candidate"])


def gold_commands(prefix, count=32):
    return [command("nanoparticle-create", nanoparticle_id=identity(f"{prefix}:gold:{i}"), diameter_nm=10.)
            for i in range(count)]


def patch_commands(design, count=32, diameter=12.):
    return [command("nanoparticle-patch", nanoparticle_id=design.nanoparticles[i % len(design.nanoparticles)].id,
                    diameter_nm=diameter) for i in range(count)]


def mixed_commands(prefix):
    rows = []
    for i in range(5):
        helix, strand, group, gold = [identity(f"{prefix}:{kind}:{i}")
                                      for kind in ("helix", "strand", "group", "gold")]
        rows.extend([
            command("helix-add", helix_id=helix, axis_start={"x": i * 3., "y": 0., "z": 0.},
                    axis_end={"x": i * 3., "y": 0., "z": 10.88}, length_bp=32),
            command("strand-add", strand_id=strand, strand_type="scaffold", domains=[{
                "helix_id": helix, "start_bp": 0, "end_bp": 31, "direction": "FORWARD"}]),
            command("cluster_create", cluster_id=group, name=f"Group {i}", helix_ids=[helix]),
            command("cluster_op", cluster_id=group, translation=[1., 2., 3.],
                    rotation=[0., 0., 0., 1.], pivot=[0., 0., 0.]),
            command("nanoparticle-create", nanoparticle_id=gold, diameter_nm=10.),
            command("nanoparticle-patch", nanoparticle_id=gold, diameter_nm=12.),
        ])
    rows.extend([command("nanoparticle-patch", nanoparticle_id=identity(f"{prefix}:gold:0"), diameter_nm=13.),
                 command("nanoparticle-delete", nanoparticle_id=identity(f"{prefix}:gold:4"))])
    return rows


def ordinary_fixtures():
    empty = create_empty_part("Registered batch benchmark", "HONEYCOMB")
    gold = candidate(prepare("gold-seed", empty, gold_commands("gold")))
    mixed = candidate(prepare("mixed-seed", empty, mixed_commands("mixed-seed")))
    helices = [command("helix-add", helix_id=identity(f"work:helix:{i}"),
        axis_start={"x": i * 3., "y": 0., "z": 0.},
        axis_end={"x": i * 3., "y": 0., "z": 531.08}, length_bp=1562) for i in range(32)]
    work = candidate(prepare("work-seed", empty, helices))
    strands = [command("strand-add", strand_id=identity(f"work:strand:{i}"), strand_type="scaffold",
        domains=[{"helix_id": helix["params"]["helix_id"], "start_bp": 0, "end_bp": 1561,
                  "direction": "FORWARD"}]) for i, helix in enumerate(helices)]
    return [prepare("32-gold-commands", gold, patch_commands(gold)),
            prepare("32-mixed-native-commands", mixed, mixed_commands("mixed-next")),
            prepare("32-commands-49984-authored-residues", work, strands)]


def public_envelope_fixtures():
    """Exactly 64 output rows, including routing headers, with real inputs."""
    ordinary = ordinary_fixtures()
    gold, mixed = ordinary[:2]
    empty = create_empty_part("Public batch work boundary", "HONEYCOMB")
    # 31 helices + one group, then 31 strands + one group = 64 rows.
    # The authored spans total exactly the existing 50,000 work allowance.
    helices = [command("helix-add", helix_id=identity(f"public-work:helix:{i}"),
        axis_start={"x": i * 3., "y": 0., "z": 0.},
        axis_end={"x": i * 3., "y": 0., "z": length * .34}, length_bp=length)
        for i, length in enumerate([1640, *([1612] * 30)])]
    work = candidate(prepare("public-work-seed", empty, helices))
    strands = [command("strand-add", strand_id=identity(f"public-work:strand:{i}"), strand_type="scaffold",
        domains=[{"helix_id": helix["params"]["helix_id"], "start_bp": 0,
                  "end_bp": helix["params"]["length_bp"] - 1, "direction": "FORWARD"}])
        for i, helix in enumerate(helices)]
    history = candidate(prepare("public-63-source", gold["design"], patch_commands(gold["design"], 31)))
    return [gold,
        prepare("mixed-prefix-37-rows-plus-27-commands", mixed["design"], patch_commands(mixed["design"], 27)),
        prepare("public-50000-authored-residues", work, strands),
        prepare("public-63-source-rows-plus-one", history, patch_commands(history, 1))]


def recovery_bytes(design):
    size = 0
    for entry in design.feature_log:
        if entry.feature_type == "routing-cluster":
            size += len(entry.pre_state_gz_b64) + len(entry.post_state_gz_b64 or "")
            size += sum(len(child.diff_added_b64) + len(child.diff_removed_b64) + len(child.diff_modified_b64)
                        for child in entry.children)
        elif entry.feature_type == "snapshot":
            size += len(entry.design_snapshot_gz_b64) + len(entry.post_state_gz_b64 or "")
    return size


def intermediate_history_fixtures(seed):
    """Measure exact retained-row boundaries using only real native batches."""
    design, cases, growth = seed, [], []
    for target in (64, 128, 256):
        while len(design.feature_log) < target:
            count = min(32, target - len(design.feature_log))
            before_rows = len(design.feature_log)
            step = prepare(f"intermediate-seed:{target}:{before_rows}", design,
                           patch_commands(design, count, 10. + (before_rows // 32) % 5))
            design = candidate(step)
            if len(design.feature_log) != before_rows + count:
                raise RuntimeError("Gold batch did not retain each declared native row")
            growth.append({"source_rows": before_rows, "commands": count,
                "candidate_rows": len(design.feature_log),
                "candidate_recovery_bytes": recovery_bytes(design),
                "evaluation_ms": step["separate_native_evaluation_ms"]})
        if len(design.feature_log) != target:
            raise RuntimeError("Intermediate source does not have the requested row count")
        case = prepare(f"native-history-{target}-source-rows", design, patch_commands(design))
        output = candidate(case)
        begin = perf_counter()
        edit = evaluate(output, {"request": {"operation": "edit", "index": len(output.feature_log) - 1,
            "params": {"diameter_nm": 17.}}, "header": {}})
        case["independent_candidate_edit"] = {"status": edit["status"],
            "candidate_rows": len(output.feature_log),
            "evaluation_ms": (perf_counter() - begin) * 1000,
            "issues": edit.get("issues", [])}
        if edit["status"] != "ready":
            raise RuntimeError(f"Intermediate batch output was not editable: {edit}")
        cases.append(case)
    return cases, growth


def history_boundary(seed):
    """Grow real <=32-command batches to the first recovery/entry refusal.

    Binary-search only the final command count to locate the exact last admitted
    history. No snapshot or authoring output is synthesized. Fixture preparation
    is outside the HTTP samples and its timings are reported separately.
    """
    design, last, attempts = seed, None, []
    count, round_id = 32, 0
    while True:
        case = prepare(f"history:{round_id}:{count}", design, patch_commands(design, count, 10. + round_id % 5))
        result = case["prepared"]
        attempts.append({"source_rows": len(design.feature_log), "commands": count,
            "evaluation_ms": case["separate_native_evaluation_ms"], "status": result["status"],
            "issues": result.get("issues", []), "source_unchanged": True,
            "candidate_returned": "candidate" in result})
        if result["status"] == "ready":
            last, design = case, candidate(case)
            attempts[-1]["candidate_recovery_bytes"] = recovery_bytes(design)
            round_id += 1
            if len(design.feature_log) > 2000:
                raise RuntimeError("Entry budget did not apply")
            continue
        if count == 1:
            break
        # Refusal is monotonic in appended snapshot count for this fixed source;
        # find a fitting suffix without widening either production budget.
        count //= 2
    if last is None:
        raise RuntimeError("No retained-history batch was editable")
    edit = evaluate(design, {"request": {"operation": "edit", "index": len(design.feature_log) - 1,
        "params": {"diameter_nm": 17.}}, "header": {}})
    if edit["status"] != "ready":
        raise RuntimeError(f"Last admitted batch history was not editable: {edit}")
    refusal = attempts[-1]
    last["name"] = "longest-actually-editable-retained-history"
    return last, {"attempts": attempts, "last_editable_rows": len(design.feature_log),
        "last_editable_recovery_bytes": recovery_bytes(design), "independent_edit_status": edit["status"],
        "first_single_command_refusal": refusal, "unchanged_recovery_limit": MAX_RECOVERY_BYTES,
        "expected_atomic_refusal": (refusal["status"] == "unverified" and not refusal["candidate_returned"]
            and any(issue.get("code") in {"entry_limit", "command_limit"} for issue in refusal["issues"]))}


def excluded_state_fixtures(base):
    """Artificial storage probes, not scientific atom placements or qualification."""
    atom = dict(serial=1, name="P", element="P", residue="DA", chain_id="A", seq_num=1,
        x=0., y=0., z=0., strand_id="storage-probe", helix_id="storage-probe", bp_index=0, direction="FORWARD")
    physical = AtomisticReference(source="Synthetic storage-cost probe; no physical calculation",
        atoms=[AtomisticReferenceAtom(**{**atom, "serial": i + 1}) for i in range(10_000)])
    presentation = [Annotation(id=f"probe:{i}", text="Storage probe", refs=[{
        "kind": "storage-probe", "values": list(range(100))}]) for i in range(1000)]
    draft = RepairDraft.model_validate({"version": 1, "draft_id": "storage-probe", "generation": 0,
        "base_design_id": base.id, "base": {"version": 1, "root_sha256": "0" * 64,
            "commands_sha256": "0" * 64, "sources_sha256": "0" * 64}, "repair_version": 1,
        "actions": [{"action": "set_input", "feature_id": base.feature_log[0].id,
            "parameter_path": ["nanoparticle_id"], "expected_old": "x" * 30_000, "value": "unresolved"}]})
    cases = []
    for name, fields in (("excluded-physical-10000-atoms", {"atomistic_reference": physical}),
                         ("excluded-presentation-100000-values", {"annotations": presentation}),
                         ("excluded-repair-draft", {"repair_draft": draft})):
        # The real worker receives only the authoring-equivalent base. Keep the
        # excluded payload on the live source, where commit/undo actually pays
        # for it, instead of fabricating a larger worker transport result.
        case = prepare(name, base, patch_commands(base, 1))
        case["design"] = base.copy_with(**fields)
        case["qualification_scope"] = False
        cases.append(case)
    poisoned = list(base.feature_log)
    poisoned[0] = poisoned[0].model_copy(update={"post_state_gz_b64": "x" * (MAX_RECOVERY_BYTES + 1)})
    case = prepare("excluded-oversized-old-recovery", base, patch_commands(base, 1))
    case.update(design=base.copy_with(feature_log=poisoned), qualification_scope=False)
    cases.append(case)
    return cases


@contextmanager
def document(doc):
    token = set_current_doc(doc)
    try:
        yield
    finally:
        reset_current_doc(token)


def reset_source(doc, design):
    with document(doc):
        state.load_design(design)
        return state.revision()


def remove_job(job_id):
    if job_id is not None:
        with jobs._lock:
            jobs._jobs.pop(job_id, None)


def concurrent_request(client, headers, callback, probe):
    begin = perf_counter()
    client.get(REVISION_PATH, headers=headers).raise_for_status()
    baseline = (perf_counter() - begin) * 1000
    first, barrier, done = len(probe.records), Barrier(2), Event()
    samples, errors = [], []

    def sample():
        barrier.wait(5)
        for _ in range(256):
            if done.is_set():
                break
            start = perf_counter()
            try:
                client.get(REVISION_PATH, headers=headers).raise_for_status()
            except Exception as error:
                errors.append(str(error))
                break
            samples.append((start, perf_counter()))

    sampler = Thread(target=sample, name="batch-light-http-probe")
    sampler.start()
    try:
        barrier.wait(5)
        begin = perf_counter()
        response = callback()
        elapsed = (perf_counter() - begin) * 1000
    finally:
        done.set()
        sampler.join(5)
    if sampler.is_alive():
        raise RuntimeError("Light-request probe did not stop")
    rows = probe.records[first:]
    holds = [row for row in rows if row["phase"] in {"capture", "publication"} and row["nesting"] == 0]
    return response, {"http_ms": elapsed, "baseline_revision_http_ms": baseline,
        "revision_http_ms": [(end - start) * 1000 for start, end in samples],
        "overlapping_revision_requests": sum(any(start <= row["ended"] and row["entered"] <= end
            for row in holds) for start, end in samples), "errors": errors,
        **{f"{phase}_lock_{what}_ms": [row[f"{what}_ms"] for row in rows
            if row["phase"] == phase and row["nesting"] == 0]
           for phase in ("capture", "publication", "light_request") for what in ("hold", "wait")}}


def summarize(rows):
    arrays = ("revision_http_ms", *(f"{phase}_lock_{what}_ms"
        for phase in ("capture", "publication", "light_request") for what in ("hold", "wait")))
    return {"http": stats([row["http_ms"] for row in rows]),
        "baseline_revision_http": stats([row["baseline_revision_http_ms"] for row in rows]),
        **{key.removesuffix("_ms"): stats([value for row in rows for value in row[key]]) for key in arrays},
        "overlapping_revision_requests": sum(row["overlapping_revision_requests"] for row in rows), "samples": rows}


def publication_correct(doc, case, revision, *, undo=True):
    expected = candidate(case)
    preserved = {name for name, role in FIELD_ROLES.items() if role in {"presentation", "physical", "repair_draft"}}
    with document(doc):
        current = state.get_or_404()
        same = (digest(current.model_dump(mode="json", include=AUTHORING_FIELDS))
            == digest(expected.model_dump(mode="json", include=AUTHORING_FIELDS)))
        same = same and current.feature_log == expected.feature_log and current.input_sources == expected.input_sources
        same = same and current.model_dump(include=preserved) == case["design"].model_dump(include=preserved)
        if undo:
            with state._lock:
                snapshot = state._session().history[-1] if state._session().history else None
            same = same and snapshot is not None and snapshot is not case["design"]
            same = same and snapshot.model_dump_json() == case["design"].model_dump_json()
        return same and state.revision() == revision + 1 and state.undo_depth() == 1 and state.redo_depth() == 0


def repeated_case(client, doc, case, repeats, probe, snapshots):
    candidate(case)
    original_submit, held = jobs._submit, []
    capture_rows, commit_rows, headers = [], [], {"X-NADOC-Doc": doc}
    jobs._submit = lambda job, *_a: held.append(job)
    try:
        for _ in range(repeats):
            revision, job_id = reset_source(doc, case["design"]), None
            try:
                response, row = concurrent_request(client, headers, lambda: client.post(JOBS_PATH, headers=headers,
                    json=request(case["design"], case["commands"], revision)), probe)
                row.update(http_status=response.status_code, response=response.json())
                if response.status_code == 202:
                    job_id = response.json()["job_id"]
                    row["intercepted_cancel_status"] = client.delete(f"{JOBS_PATH}/{job_id}", headers=headers).status_code
                elif response.status_code != 413:
                    row["errors"].append(f"Unexpected capture response: {response.text}")
                capture_rows.append(row)
            finally:
                if held:
                    held.pop()
                    _slot.release()
                remove_job(job_id)
            revision, job_id = reset_source(doc, case["design"]), str(uuid4())
            definition = EvaluationRequest.model_validate(request(case["design"], case["commands"], revision))
            request_digest = digest(definition.model_dump(mode="json"))
            with state._lock:
                session_identity = state._sessions[doc].identity
                admission = permits.admit_evaluation(doc, state._sessions[doc],
                    operation="batch", request_sha256=request_digest)
            with jobs._lock:
                jobs._jobs[job_id] = jobs.EvaluationJob(doc, ref(case["design"]), revision,
                    created=monotonic(), status="complete", admitted_operation="batch",
                    session_identity=session_identity, admission=admission,
                    request_sha256=request_digest, result=dict(case["prepared"]))
            first_snapshot = len(snapshots)
            try:
                response, row = concurrent_request(client, headers,
                    lambda: client.post(f"{JOBS_PATH}/{job_id}/commit", headers=headers), probe)
                row.update(http_status=response.status_code, response=response.json(), snapshot_ms=snapshots[first_snapshot:])
                row["correct_publication"] = response.status_code == 200 and publication_correct(doc, case, revision)
                if not row["correct_publication"]:
                    row["errors"].append(f"Publication mismatch: {response.text}")
                commit_rows.append(row)
            finally:
                remove_job(job_id)
    finally:
        jobs._submit = original_submit
    design = case["design"]
    return {"name": case["name"], "qualification_scope": case.get("qualification_scope", True),
        "commands": len(case["commands"]), "history_rows": len(design.feature_log),
        "history_entries_including_children": len(design.feature_log) + sum(len(row.children)
            for row in design.feature_log if row.feature_type == "routing-cluster"),
        "source_json_bytes": len(design.model_dump_json().encode()), "candidate_json_bytes": len(json.dumps(case["prepared"]["candidate"]).encode()),
        "retained_recovery_encoded_bytes": recovery_bytes(design), "retained_input_sources": len(design.input_sources),
        "separate_native_evaluation_ms": case["separate_native_evaluation_ms"], "repeats": repeats,
        "independent_candidate_edit": case.get("independent_candidate_edit"),
        "capture_refusals": sum(row["http_status"] == 413 for row in capture_rows),
        "correct_publications": sum(row["correct_publication"] for row in commit_rows),
        "publication_snapshot": stats([value for row in commit_rows for value in row["snapshot_ms"]]),
        "capture_without_worker": summarize(capture_rows), "commit_prepared_candidate": summarize(commit_rows)}


def cold_replay(design):
    begin = perf_counter()
    try:
        isolated = capture(design)
    except CaptureLimit as error:
        return {"status": "unverified", "issues": [{"code": "capture_limit", "detail": str(error)}]}
    worker = VerificationWorker(isolated)
    try:
        worker.start()
        if not worker.wait(5):
            return {"status": "unverified", "issues": [{"code": "time_limit"}]}
        return {**worker.result(), "elapsed_ms": (perf_counter() - begin) * 1000}
    finally:
        worker.close()


def actual_job(client, doc, case, mode="complete"):
    original_submit, original_worker = jobs._submit, jobs.EvaluationWorker
    started, done, threads, timings = Event(), Event(), [], {}
    revision, job_id = reset_source(doc, case["design"]), None
    headers = {"X-NADOC-Doc": doc}

    class ObservedWorker(original_worker):
        def __init__(self, *args, **kwargs):
            begin = perf_counter()
            super().__init__(*args, **kwargs)
            timings["parent_worker_constructor_ms"] = (perf_counter() - begin) * 1000

        def start(self):
            begin = perf_counter()
            super().start()
            timings["process_start_call_ms"] = (perf_counter() - begin) * 1000
            started.set()

    def submit(*args):
        def run():
            try:
                jobs._run(*args)
            finally:
                done.set()
        thread = Thread(target=run, name="batch-live-benchmark-supervisor", daemon=False)
        threads.append(thread)
        thread.start()

    jobs._submit, jobs.EvaluationWorker = submit, ObservedWorker
    try:
        begin = perf_counter()
        verification_only = case.get("verification_only", False)
        body = {"operation": "verify"} if verification_only else request(case["design"], case["commands"], revision)
        response = client.post(JOBS_PATH, headers=headers, json=body)
        timings["start_http_ms"] = (perf_counter() - begin) * 1000
        if response.status_code != 202:
            return {"mode": mode, "start_http_status": response.status_code, "response": response.json(), **timings}
        job_id, path = response.json()["job_id"], f"{JOBS_PATH}/{response.json()['job_id']}"
        if mode != "complete":
            if not started.wait(10):
                raise RuntimeError("Worker did not start")
            stop = perf_counter()
            if mode == "cancel":
                client.delete(path, headers=headers).raise_for_status()
            else:
                with document(doc):
                    source, current = state.get_design_with_revision()
                    state.set_design(source.model_copy(deep=True), expected_revision=current, expected_source=source)
            if not done.wait(10):
                raise RuntimeError("Worker did not reap after cancellation/staleness")
            timings["stop_to_supervisor_reaped_ms"] = (perf_counter() - stop) * 1000
        elif not done.wait(jobs.TIME_BUDGET + 10):
            raise RuntimeError("Worker exceeded existing deadline")
        timings["start_to_supervisor_reaped_ms"] = (perf_counter() - begin) * 1000
        polled = client.get(path, headers=headers).json()
        # Live feature IDs are generated by the host's fresh UUID seed. Compare
        # the retained result of this actual job, not a fixture's unrelated seed.
        with jobs._lock:
            live_case = {**case, "prepared": dict(jobs._jobs[job_id].result)}
        begin = perf_counter()
        committed = client.post(path + "/commit", headers=headers)
        timings["commit_http_ms"] = (perf_counter() - begin) * 1000
        with document(doc):
            current = state.get_or_404()
            if mode == "complete" and verification_only:
                correct = (committed.status_code == 409 and polled["result"]["status"] == "verified"
                    and current.model_dump_json() == case["design"].model_dump_json()
                    and state.revision() == revision and state.undo_depth() == 0)
                replay = None
            elif mode == "complete":
                correct = committed.status_code == 200 and publication_correct(doc, live_case, revision)
                replay = cold_replay(Design.from_json(current.to_json())) if correct else None
            else:
                correct = (committed.status_code == 409 and current.model_dump_json() == case["design"].model_dump_json()
                    and state.revision() == revision + int(mode == "source_changed")
                    and state.undo_depth() == int(mode == "source_changed"))
                replay = None
        free = _slot.acquire(blocking=False)
        if free:
            _slot.release()
        return {"mode": mode, "start_http_status": 202, "poll": polled,
            "commit_http_status": committed.status_code, "commit": committed.json(),
            "source_guard_correct": correct, "cold_replay": replay,
            "shared_admission_released_after_reaping": free, **timings}
    finally:
        if job_id:
            with jobs._lock:
                if job_id in jobs._jobs:
                    jobs._jobs[job_id].cancelled.set()
        for thread in threads:
            thread.join(10)
            if thread.is_alive():
                raise RuntimeError("Benchmark supervisor remains alive")
        remove_job(job_id)
        jobs._submit, jobs.EvaluationWorker = original_submit, original_worker


def provenance_diagnostics():
    native = create_empty_part("Provenance probes", "HONEYCOMB")
    rootless = native.copy_with(recipe_root=None)
    results = {}
    for name, design in (("rootless", rootless),
                         ("explicit_import_basis", rootless.copy_with(recipe_root=import_root(rootless)))):
        result = prepare(name, design, gold_commands(name, 1))["prepared"]
        results[name] = {"status": result["status"], "issues": result.get("issues", []),
            "source_assessment": result.get("source_assessment"), "candidate_returned": "candidate" in result}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--intermediate-history-only", action="store_true",
                        help="Measure 64/128/256 native source rows without the maximum-history search or storage probes")
    parser.add_argument("--public-envelope-only", action="store_true",
                        help="Measure actual guarded 64-row publication scope without broader storage probes")
    args = parser.parse_args()
    if args.public_envelope_only and args.intermediate_history_only:
        parser.error("Choose only one qualification scope")
    if not 30 <= args.repeats <= 60:
        parser.error("Use 30..60 repeats per boundary")
    doc = f"__benchmark_registered_batch_jobs_{uuid4()}__"
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(router, prefix="/api")

    @app.get(REVISION_PATH)
    def revision():
        token = _PHASE.set("light_request")
        try:
            return {"revision": state.revision()}
        finally:
            _PHASE.reset(token)

    original = (state._lock, state.capture_design_for_evaluation, state.set_design,
                state._snapshot_copy, part_batch_evaluation.REGISTERED_BATCH_ENABLED)
    probe, snapshots = LockProbe(original[0]), []

    def snapshot(design):
        begin = perf_counter()
        try:
            return original[3](design)
        finally:
            snapshots.append((perf_counter() - begin) * 1000)

    state._lock = probe
    state.capture_design_for_evaluation = phase_wrapper(original[1], "capture")
    state.set_design = phase_wrapper(original[2], "publication")
    state._snapshot_copy = snapshot
    part_batch_evaluation.REGISTERED_BATCH_ENABLED = True
    try:
        boundary = None
        if args.public_envelope_only:
            fixtures, growth, excluded = public_envelope_fixtures(), [], []
        elif args.intermediate_history_only:
            empty = create_empty_part("Intermediate native history benchmark", "HONEYCOMB")
            seed = candidate(prepare("intermediate-gold-seed", empty, gold_commands("intermediate-gold")))
            fixtures, growth = intermediate_history_fixtures(seed)
            excluded = []
        else:
            fixtures = ordinary_fixtures()
            intermediate, growth = intermediate_history_fixtures(fixtures[0]["design"])
            longest, boundary = history_boundary(fixtures[0]["design"])
            fixtures.extend([*intermediate, longest])
            excluded = excluded_state_fixtures(fixtures[0]["design"])
        provenance = provenance_diagnostics()
        with TestClient(app) as client:
            startup = actual_job(client, doc, {"design": create_empty_part("Empty worker startup", "HONEYCOMB"),
                                              "verification_only": True})
            cases = [repeated_case(client, doc, case, args.repeats, probe, snapshots) for case in [*fixtures, *excluded]]
            live = [{"case": case["name"], **actual_job(client, doc, case)} for case in fixtures]
            races = [actual_job(client, doc, fixtures[1], mode) for mode in ("cancel", "source_changed")]
    finally:
        try:
            state.drop_doc(doc)
        finally:
            (state._lock, state.capture_design_for_evaluation, state.set_design,
             state._snapshot_copy, part_batch_evaluation.REGISTERED_BATCH_ENABLED) = original
    leaked = doc in state.revision_map()
    print(json.dumps({"scope": "Actual HTTP capture; independent prepared publication with full-source undo; real spawned lifecycle",
        "public_gate_before_and_after": original[4], "harness_only_gate_override": True,
        "ordinary_capture_profile_unchanged": {"max_nodes": 30_000, "max_bytes": 2_000_000, "seconds": .025},
        "session_cleanup_verified": not leaked, "retained_history_boundary": boundary,
        "intermediate_history_only": args.intermediate_history_only,
        "public_envelope_only": args.public_envelope_only,
        "intermediate_history_native_preparation": growth,
        "provenance_diagnostics": provenance, "empty_root_worker_startup_baseline": startup,
        "cases": cases, "real_spawned_jobs": live, "real_worker_races": races,
        "notes": ["No production lifespan, workspace writes or scientific calculations; artificial excluded-state records measure storage costs only.",
            "Capture samples intercept submission after actual locked capture and do not measure worker computation or native cancellation.",
            "Prepared commits run independently of capture refusals and are not evidence of successful end-to-end admission.",
            "Undo equality checks cover the complete retained source, including history, physical/presentation state and repair draft.",
            "Intermediate boundaries have exactly 64/128/256 native source rows; each appends 32 commands and its complete candidate is independently editable.",
            "When the maximum-history search runs, its final native history is independently editable and the next single command must fail atomically at unchanged budgets.",
            "A source may fit ordinary capture while excluded physical/presentation/draft data makes undo publication expensive.",
            "Empty-root verification measures spawn/import/trivial-proof overhead without a native build; parent process-start call timings are separate.",
            "Cold proof uses its unchanged ordinary capture and deadline; no successful cold assessment is inferred from a ready batch.",
            "Lock probes add overhead; zero observed overlap is not evidence of zero contention. Refusals are retained without retry.",
            "Exit status checks harness correctness only. Qualification requires reviewing capture refusals, p95 lock/HTTP costs and full-source scope."]}, indent=2))
    bad_samples = any(case["correct_publications"] != args.repeats or any(row["errors"]
        for stage in ("capture_without_worker", "commit_prepared_candidate") for row in case[stage]["samples"]) for case in cases)
    bad_live = any(row["start_http_status"] not in {202, 413} or (row["start_http_status"] == 202 and (
        not row["source_guard_correct"] or not row["shared_admission_released_after_reaping"])) for row in [startup, *live, *races])
    return int(leaked or bad_samples or bad_live or (boundary is not None and not boundary["expected_atomic_refusal"]))


if __name__ == "__main__":
    raise SystemExit(main())
