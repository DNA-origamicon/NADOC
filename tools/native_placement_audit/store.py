"""Fail-closed, append-only placement evidence. No production geometry imports."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "backend/core/native_full_placement.py", "backend/core/native_slab_placement.py",
    "backend/core/measured_atomistic.py", "backend/core/nucleotide_landmarks.py",
    "backend/core/data/measured_atomistic_template.json", "backend/core/display_placement.py",
    "backend/core/measured_positioning.py", "backend/core/design_geometry.py",
    "backend/core/deformation.py", "backend/core/deformation_scope.py",
    "backend/core/lattice.py", "backend/core/linker_relax.py",
    "backend/core/assembly_linker.py", "backend/core/assembly_linker_relax.py",
    "backend/physics/oxdna_interface.py",
    "backend/physics/native_oxdna.py",
    "backend/api/crud.py", "backend/api/routes_vr.py",
    "backend/api/assembly.py",
    "backend/api/routes_placement_integrity.py",
    "backend/api/vr_startup.py", "backend/api/vr_representation_loading.py",
    "frontend/src/scene/helix_renderer.js",
    "frontend/src/viewer/native_placement.js",
    "frontend/src/viewer/geometry_codec.js",
    "frontend/src/viewer/placement_scene_guard.js",
    "frontend/src/viewer/runtime.js",
    "frontend/src/main.js", "frontend/src/api/client.js",
    "frontend/src/state/store.js",
    "frontend/src/scene/export_video.js", "frontend/src/scene/photo_mode.js",
    "frontend/src/scene/native_pose_transport.js",
    "frontend/src/scene/overhang_strand_anim.js",
    "frontend/src/scene/overhang_unzip_overlay.js",
    "frontend/src/strand-anim/strand_renderer.js",
    "native/vr_viewer/src/main.cpp",
    "native/vr_viewer/src/placement_integrity.hpp",
    "native/vr_viewer/src/representation_loading.hpp",
    "tools/native_placement_audit/store.py",
    "tools/native_placement_audit/pytest_plugin.py",
    "tools/native_placement_audit/command.py",
    "frontend/native_placement_reporter.js",
)
REVIEW_FIELDS = ("root_cause", "affected_paths", "validation", "regression_tests", "evidence")
REVIEW_CHECKLIST = (
    "Preserve the failing document, source identities and exact reproduction.",
    "Compare actual and canonical bead/slab frames in shared coordinates; inspect each displaced site and forward/reverse registration.",
    "Trace all native Full producers and consumers, including full/compact/partial API responses, preview, undo/redo, reload and desktop/VR.",
    "Identify any fallback, independent reconstruction or stale cache that could select a second placement, even transiently.",
    "Add the missing regression and verify representative native, bent, twisted, moved and independently scoped cases, with numeric and visual evidence.",
    "Document the root cause, complete affected scope, validation results and remaining limits; explicitly acknowledge each incident without replacing geometry goldens.",
)


def report_directory(directory=None):
    return Path(directory or os.environ.get("NADOC_PLACEMENT_REPORT_DIR") or
                ROOT / ".native-placement-review").resolve()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _write(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(_jsonable(data), indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def source_ids(extra_files=()):
    result = {}
    for name in (*SOURCE_FILES, *extra_files):
        path = ROOT / name
        if path.is_file():
            label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            result[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def pending_reviews(directory=None):
    directory = report_directory(directory)
    # Path.glob/exists can suppress filesystem errors and make an unreadable
    # journal appear empty. Only a genuinely absent, never-created root is clear.
    try:
        with os.scandir(directory) as entries:
            root_names = {entry.name for entry in entries}
    except FileNotFoundError:
        return []
    incident_paths = []
    if "incidents" in root_names:
        with os.scandir(directory / "incidents") as entries:
            incident_paths = sorted(Path(entry.path) for entry in entries)
    marker_incidents = (json.loads((directory / "REVIEW_REQUIRED.json").read_text()).get("incidents", [])
                        if "REVIEW_REQUIRED.json" in root_names else [])
    known_incidents = {incident["incident_id"] for incident in marker_incidents}
    pending = []
    present_reports = set()
    for incident_directory in incident_paths:
        with os.scandir(incident_directory) as entries:
            incident_names = {entry.name for entry in entries}
        if "report.json" not in incident_names:
            if incident_directory.name not in known_incidents:
                raise ValueError(f"Placement incident has no report or review marker: {incident_directory}")
            continue
        incident = incident_directory / "report.json"
        present_reports.add(incident_directory.name)
        report = json.loads(incident.read_text())
        acknowledgement = incident.with_name("review.json")
        reviewed = False
        if "review.json" in incident_names:
            ack = json.loads(acknowledgement.read_text())
            reviewed = (ack.get("report_sha256") == hashlib.sha256(incident.read_bytes()).hexdigest()
                        and ack.get("reviewer") and all(ack.get("review", {}).get(k) for k in REVIEW_FIELDS))
        if not reviewed:
            pending.append({"incident_id": report["incident_id"], "test_id": report["test_id"],
                            "report": str(incident), "html": str(incident.with_name("report.html"))})
    # Losing incident evidence must not turn a known red latch into a pass.
    for old in marker_incidents:
        if old["incident_id"] not in present_reports:
            pending.append({**old, "missing_evidence": True})
    return pending


def _update_marker(directory):
    pending = pending_reviews(directory)
    _write(directory / "REVIEW_REQUIRED.json", {
        "schema_version": 1, "status": "review_required" if pending else "reviewed",
        "updated_at_utc": _now(), "incidents": pending,
        "instruction": "A passing rerun does not resolve this incident. Complete and explicitly acknowledge the placement review.",
    })


def record_failure(failure: dict, directory=None):
    """Persist one failure immediately; IO/serialization failures propagate.

    Required: test_id, exception. Optional: phase, evidence (expected/actual,
    per-site displacements and identities), reproduce_command, source_files,
    source_ids. Runtime callers may use test_id='runtime:<operation>'.
    """
    if not failure.get("test_id") or not failure.get("exception"):
        raise ValueError("Placement failure requires test_id and exception")
    directory = report_directory(directory)
    incident_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    report = {**_jsonable(failure), "schema_version": 1, "incident_id": incident_id,
              "status": "review_required", "timestamp_utc": _now(),
              "required_review": list(REVIEW_CHECKLIST),
              "source_ids": {**source_ids(failure.get("source_files", ())), **failure.get("source_ids", {})}}
    with _locked(directory):
        target = directory / "incidents" / incident_id
        target.mkdir(parents=True)
        _write(target / "report.json", report)
        summary = ("NATIVE FULL PLACEMENT: REVIEW REQUIRED\n"
                   f"Incident: {incident_id}\nTest/operation: {report['test_id']}\n"
                   f"When: {report['timestamp_utc']}\n"
                   f"Reproduce: {report.get('reproduce_command', 'See exception and evidence below')}\n\n"
                   "Placement must not be approved from a passing rerun alone. Review native bead/slab placement, "
                   "all affected render/API/preview paths, and the per-site evidence.\n\n"
                   "Required review:\n" + "\n".join(f"- {item}" for item in REVIEW_CHECKLIST) + "\n\n"
                   + json.dumps(report, indent=2, allow_nan=False) + "\n")
        (target / "report.txt").write_text(summary)
        (target / "report.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Native placement review required</title>"
            "<style>body{font:16px system-ui;margin:2rem;max-width:1000px}h1{color:#a21}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1rem}</style>"
            "<h1>Native Full placement: review required</h1>"
            "<p>A passing rerun does not clear this incident. The complete evidence follows.</p><pre>"
            + html.escape(summary) + "</pre>")
        _update_marker(directory)
    return {"incident_id": incident_id, "report": str(target / "report.json"),
            "html": str(target / "report.html"), "text": str(target / "report.txt")}


def check_review_gate(directory=None):
    """Return unresolved incidents; raises on malformed/unreadable evidence."""
    return pending_reviews(directory)


def acknowledge(incident_id, *, reviewer, review, directory=None):
    """Separate, explicit review action. Never called by test success hooks."""
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", incident_id):
        raise ValueError("Invalid incident ID")
    if not str(reviewer).strip() or any(not review.get(k) for k in REVIEW_FIELDS):
        raise ValueError("Review needs reviewer and nonempty " + ", ".join(REVIEW_FIELDS))
    directory = report_directory(directory)
    with _locked(directory):
        target = directory / "incidents" / incident_id
        report = target / "report.json"
        digest = hashlib.sha256(report.read_bytes()).hexdigest()
        if (target / "review.json").exists():
            raise ValueError("Incident already has a review; original review cannot be overwritten")
        _write(target / "review.json", {"incident_id": incident_id, "reviewer": reviewer,
               "reviewed_at_utc": _now(), "report_sha256": digest, "review": review})
        _update_marker(directory)
