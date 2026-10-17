#!/usr/bin/env python3
"""Measure closed-dispatch overhead without production lifespan or model work.

Run serially through validation_guard. Tiny documents and responses stay in
memory; only the requested compact JSON report is persisted. This does not
qualify batch capture/publication, browser responsiveness or adversarial load.
"""

import argparse
import json
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_publication_policy as policy, state
from backend.api import doc_context
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_revision_status import revision_status
from backend.api.part_strict_http import StrictPartDispatch


PATH = "/api/design/revision"


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "median_ms": None, "p95_ms": None, "max_ms": None}
    return {"count": len(ordered), "median_ms": median(ordered),
            "p95_ms": ordered[ceil(len(ordered) * .95) - 1], "max_ms": ordered[-1]}


def application():
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)

    @app.get(PATH)
    def revision():
        # Existing compatibility read: no copying, geometry or proof work.
        return revision_status()

    return app


def run(repeats):
    prior = policy.current_configuration()
    compat, strict = f"__http_benchmark__{uuid4()}", f"__http_benchmark__{uuid4()}"
    token = set_current_doc(compat)
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    result = {"scope": "in-memory TestClient dispatch/read overhead only", "repeats": repeats,
              "gc_policy": "unchanged", "model_execution": False, "production_lifespan": False,
              "completed": False, "unexpected_results": [], "cleanup_errors": []}
    measured = {}
    stage, iteration, case = "fixture", None, None
    try:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            document_modes={strict: "registered_only"}))
        compatibility_design = state.create_empty_part("Compatibility dispatch probe")
        with TestClient(application()) as original, TestClient(StrictPartDispatch(application())) as dispatched:
            response = dispatched.post("/api/design/registered-empty", headers={"X-NADOC-Doc": strict},
                                       json={"name": "Strict dispatch probe"})
            if response.status_code != 201:
                raise RuntimeError(f"Empty fixture admission failed: {response.status_code} {response.text}")
            expected_ids = {compat: compatibility_design.id, strict: response.json()["design_id"]}
            rows = {
                "compatibility_original": (original, compat, PATH, 200),
                "compatibility_dispatched": (dispatched, compat, PATH, 200),
                "strict_revision": (dispatched, strict, PATH, 200),
                "strict_policy": (dispatched, strict, "/api/design/construction-policy", 200),
                "strict_unknown_refusal": (dispatched, strict, "/api/design", 403),
            }
            measured = {name: [] for name in rows}
            # Warm each app once, then rotate order to reduce systematic bias.
            stage = "warmup"
            for case, (client, doc, path, expected) in rows.items():
                if client.get(path, headers={"X-NADOC-Doc": doc}).status_code != expected:
                    raise RuntimeError("Dispatch warm-up returned an unexpected status")
            names = list(rows)
            stage = "measured_requests"
            for index in range(repeats):
                iteration = index
                offset = index % len(names)
                for name in names[offset:] + names[:offset]:
                    case = name
                    client, doc, path, expected = rows[name]
                    begin = perf_counter()
                    response = client.get(path, headers={"X-NADOC-Doc": doc})
                    measured[name].append((perf_counter() - begin) * 1000)
                    if response.status_code != expected:
                        result["unexpected_results"].append({"case": name, "iteration": index,
                                                             "status": response.status_code})
                    else:
                        body = response.json()  # Correctness work is outside the timed interval.
                        valid = (body.get("doc_id") == doc and body.get("design_id") == expected_ids[doc]
                                 and body.get("revision") == 1 and body.get("has_design") is True) if path == PATH else (
                            body.get("doc_id") == strict and body.get("mode") == "registered_only"
                            and body.get("policy_generation") == policy.resolve(strict).generation
                            if name == "strict_policy" else body.get("detail", {}).get("code") == "construction_policy")
                        if not valid:
                            result["unexpected_results"].append({"case": name, "iteration": index,
                                                                 "error": "Unexpected scalar response identity/content"})
            result["completed"] = True
    except Exception as error:
        result["unexpected_results"].append({"stage": stage, "case": case, "iteration": iteration,
                                             "error": f"{type(error).__name__}: {error}"})
    finally:
        for name, cleanup in (("compatibility_document", lambda: state.drop_doc(compat)),
                              ("strict_document", lambda: state.drop_doc(strict)),
                              ("policy", lambda: state.configure_part_publication_policy(prior)),
                              ("context", lambda: reset_current_doc(token)),
                              ("request_revision", lambda: doc_context.set_request_revision(request_revision)),
                              ("request_entry", lambda: doc_context.set_request_feature_log_entry_id(request_entry))):
            try:
                cleanup()
            except Exception as error:
                result["cleanup_errors"].append({"stage": name, "error": f"{type(error).__name__}: {error}"})
        result["cleanup_ok"] = (not result["cleanup_errors"] and compat not in state._sessions
                                and strict not in state._sessions)
        result["cases"] = {name: distribution(values) for name, values in measured.items()}
        before, after = measured.get("compatibility_original", []), measured.get("compatibility_dispatched", [])
        result["paired_compatibility_overhead"] = distribution([b - a for a, b in zip(before, after)])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.repeats <= 1000:
        parser.error("--repeats must be between 10 and 1000")
    report = run(args.repeats)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["completed"] and not report["unexpected_results"] and report["cleanup_ok"] else 1)
