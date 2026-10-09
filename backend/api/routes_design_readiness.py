"""Read-only readiness for the active part or visible assembled system."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import threading
import weakref

from fastapi import APIRouter

from backend.api import assembly_state, state
from backend.api.doc_context import get_current_doc
from backend.core.design_readiness import finish_readiness, standard_readiness
from backend.core.models import Design, PartSourceFile, PartSourceInline
from backend.core.oxdna_staleness import design_build_fingerprint
from backend.core.readiness_jobs import completed_simulation

router = APIRouter(tags=["design"])
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _source_stamps(assembly):
    """Invalidate source-file edits even when the assembly itself did not change."""
    from backend.core import assembly_flatten

    stamps = []
    for instance in assembly.instances:
        if not instance.visible or not isinstance(instance.source, PartSourceFile):
            continue
        raw = Path(instance.source.path)
        candidates = (raw, assembly_flatten._WORKSPACE_DIR / raw,
                      assembly_flatten._PROJECT_ROOT / raw, assembly_flatten._LIBRARY_DIR / raw)
        for path in candidates:
            try:
                stat = path.stat()
                stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
                break
            except OSError:
                continue
        else:
            stamps.append((instance.source.path, None, None))
    return tuple(stamps)


def _assembly_report(assembly):
    from backend.core.assembly_flatten import _load_design, flatten_assembly
    from backend.core.assembly_validate import validate_assembly_report

    resolved = []
    source_reports = []
    failures = []
    sources = {}
    for instance in assembly.instances:
        if not instance.visible:
            resolved.append(instance)
            continue
        try:
            key = ("file", instance.source.path) if isinstance(instance.source, PartSourceFile) else ("inline", id(instance.source.design))
            if key not in sources:
                design = _load_design(instance.source)
                sources[key] = (design, standard_readiness(design))
            design, report = sources[key]
            source_reports.append((instance, report))
            resolved.append(instance.model_copy(update={"source": PartSourceInline(design=design)}))
        except (OSError, ValueError) as exc:
            failures.append({"instance_id": instance.id, "name": instance.name or instance.id, "detail": str(exc)})
    if failures:
        report = standard_readiness(None)
        report.update(available=True, design_id=f"flat_{assembly.id}", steps=[{
            "id": "topology", "label": "Design integrity", "complete": False,
            "applicable": True, "action": "validation", "detail": "Resolve unavailable assembly parts.",
            "issues": [item["detail"] for item in failures], "targets": failures,
        }])
        return None, finish_readiness(report)
    resolved_assembly = assembly.model_copy(update={"instances": resolved})
    try:
        # This validator performs its own flatten-ID check. Run it before
        # retaining our canonical design, avoiding two large projections at once.
        assembly_report = validate_assembly_report(resolved_assembly)
        # Use the same canonical simulation boundary as /assembly/flatten.
        design = Design.from_json(flatten_assembly(resolved_assembly).to_json())
        report = standard_readiness(design)
        for step in report["steps"]:
            step["targets"] = [
                {"instance_id": instance.id, "name": instance.name or instance.id,
                 "detail": source_step["detail"]}
                for instance, source_report in source_reports
                for source_step in source_report["steps"]
                if source_step["id"] == step["id"] and source_step.get("applicable", True)
                and not source_step["complete"]
            ]
            if step["targets"]:
                step["complete"] = False
                step["detail"] = f"{len(step['targets'])} visible part instance(s) need this step."
                for instance, source_report in source_reports:
                    for source_step in source_report["steps"]:
                        if source_step["id"] != step["id"] or source_step["complete"]:
                            continue
                        step["issues"].extend(f"{instance.name}: {issue}" for issue in source_step["issues"])
                        if source_step["action"] == "validation":
                            step["action"] = "validation"
                step["issues"] = step["issues"][:20]
            if step["id"] == "topology" and not assembly_report["passed"]:
                step["complete"] = False
                step["detail"] = "Review assembly and design-integrity findings."
                step["issues"].extend(row.get("message", row["check"]) for row in assembly_report["results"] if not row["ok"])
        report["limitations"].append("Assembly readiness includes visible part instances and assembly-owned DNA, matching simulation scope.")
        return design, finish_readiness(report)
    except (OSError, ValueError) as exc:
        report = standard_readiness(None)
        report.update(available=True, design_id=f"flat_{assembly.id}", steps=[{
            "id": "topology", "label": "Design integrity", "complete": False,
            "applicable": True, "action": "validation", "detail": "Review assembly topology before simulation.",
            "issues": [str(exc)], "targets": [],
        }])
        return None, finish_readiness(report)


@router.get("/design/readiness")
def get_design_readiness(assembly: bool = False) -> dict:
    """Return checklist facts only; never mutate the active document or jobs."""
    from backend.api.assembly import _WORKSPACE_DIR

    if assembly:
        current = assembly_state.get_assembly()
        revision = assembly_state.revision()
        source_stamps = _source_stamps(current) if current is not None else ()
    else:
        current, revision = state.get_design_with_revision()
        source_stamps = ()
    context = "assembly" if assembly else "part"
    if current is None:
        return {**finish_readiness(standard_readiness(None)), "context": context, "document_id": None}
    key = (get_current_doc(), context)
    version = (id(current), revision, source_stamps)
    # Cache expensive validation/flattening/fingerprinting, not the simulation
    # verdict: a finished job must update the ring without editing the design.
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is None or cached[0]() is not current or cached[1] != version:
            design, report = _assembly_report(current) if assembly else (current, standard_readiness(current))
            fingerprint = design_build_fingerprint(design) if design is not None and report["available"] else None
            cached = (weakref.ref(current), version, design.id if design is not None else None, report, fingerprint)
            _CACHE[key] = cached
            _CACHE.move_to_end(key)
            while len(_CACHE) > 16:
                _CACHE.popitem(last=False)
    _, _, design_id, report, fingerprint = cached
    report = deepcopy(report)
    if design_id is not None and report["available"]:
        report = finish_readiness(report, completed_simulation(design_id, _WORKSPACE_DIR, fingerprint))
    return {**report, "context": context, "document_id": current.id}
