"""
API layer — assembly validation + flatten route handlers (extracted from assembly.py).

This module hosts the three read-only "inspect/derive the assembly" endpoints:
validate the active assembly, flatten it to a preview Design, and flatten-and-load
it as the active design. They were factored out of ``assembly.py`` following the
same template as the crud.py / assembly.py sub-router lifts
(``routes_assembly_animations.py``, ``routes_assembly_configs.py``).

Routes
------
  GET  /assembly/validate                  — structured validation report
  GET  /assembly/flatten                    — preview merged Design JSON (no state change)
  POST /assembly/flatten/load-as-design     — flatten + load as the active design

URLs are unchanged from their previous home in assembly.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api import assembly_state
from backend.api import state as design_state

router = APIRouter()


# ── Assembly validation ───────────────────────────────────────────────────────

@router.get("/assembly/validate", status_code=200)
def validate_assembly() -> dict:
    """Validate the active assembly and return a structured report."""
    from backend.core.assembly_validate import validate_assembly_report
    assembly = assembly_state.get_or_create()
    return validate_assembly_report(assembly)


# ── Flatten to Design ────────────────────────────────────────────────────────

@router.get("/assembly/flatten", status_code=200)
def get_assembly_flatten() -> dict:
    """
    Return the active assembly flattened into a single merged Design JSON.
    Does not alter any state — preview only.
    """
    from backend.core.assembly_flatten import flatten_assembly
    assembly = assembly_state.get_or_create()
    try:
        design = flatten_assembly(assembly)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, detail=str(exc))
    return {"design": design.to_dict()}


@router.post("/assembly/flatten/load-as-design", status_code=200)
def flatten_load_as_design() -> dict:
    """
    Flatten the assembly into a single Design and load it as the active design.
    Clears assembly mode flag on the frontend side (response includes assemblyActive=False).
    """
    from backend.core.assembly_flatten import flatten_assembly
    from backend.core.validator import validate_design
    assembly = assembly_state.get_or_create()
    try:
        design = flatten_assembly(assembly)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, detail=str(exc))
    design_state.set_design(design)
    report = validate_design(design)
    from backend.api.crud import _design_response
    return _design_response(design, report)
