"""
API layer — assembly linker route handlers (extracted from assembly.py).

This module hosts the cohesive cluster of *assembly-level linker* endpoints:
linker helices and strands live directly on the ``Assembly`` (not on any part)
and bridge cross-part overhangs; the linker-geometry endpoint emits their
world-space nucleotide beads for the renderer / relax solver. They were
factored out of ``assembly.py`` following the same template as the other
assembly-side sub-routers (``routes_assembly_animations.py``,
``routes_assembly_configs.py``).

Routes
------
  POST   /assembly/linker-helices              — append a linker Helix
  DELETE /assembly/linker-helices/{helix_id}   — remove a linker helix
  POST   /assembly/linker-strands              — append a linker Strand
  DELETE /assembly/linker-strands/{strand_id}  — remove a linker strand
  GET    /assembly/linker-geometry             — world-space linker nucleotide geometry

The heavy geometry compute helper ``_linker_geometry_for_assembly`` stays in
``assembly.py`` and is imported back: it depends on the api-layer
``crud._geometry_for_design`` (so it cannot move to ``backend/core`` without
inverting the api→core dependency arrow) and is also called from the
overhang-connections region + the relax test suite. Importing that one helper
back here is strictly less coupling than moving it.

URLs are unchanged from their previous home in assembly.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
# _assembly_response is the shared assembly response helper (the assembly-side
# twin of crud.py's _design_response); _linker_geometry_for_assembly is the
# bespoke linker-geometry compute helper that stays in assembly.py (see module
# docstring). Both are imported back from assembly.py.
from backend.api.assembly import _assembly_response, _linker_geometry_for_assembly
from backend.core.models import Helix, Strand, Vec3

router = APIRouter()


# ── Request bodies ────────────────────────────────────────────────────────────

class AddLinkerHelixRequest(BaseModel):
    axis_start: list[float]         # [x, y, z] nm
    axis_end:   list[float]         # [x, y, z] nm
    length_bp:  int
    phase_offset: float = 0.0
    id: Optional[str] = None        # auto-generated if omitted


class AddLinkerStrandRequest(BaseModel):
    id: Optional[str] = None        # prefix with "__vsc__" for virtual scaffold connections
    strand_type: str = "staple"
    domains: list[dict] = []
    color: Optional[str] = None
    notes: Optional[str] = None     # JSON string; VSC metadata stored here


# ── Linker helices ────────────────────────────────────────────────────────────

@router.post("/assembly/linker-helices", status_code=201)
def add_linker_helix(body: AddLinkerHelixRequest) -> dict:
    """Append a linker Helix to assembly.assembly_helices."""
    import uuid as _uuid
    assembly = assembly_state.get_or_404()
    helix = Helix(
        id=body.id or str(_uuid.uuid4()),
        axis_start=Vec3(x=body.axis_start[0], y=body.axis_start[1], z=body.axis_start[2]),
        axis_end=Vec3(x=body.axis_end[0], y=body.axis_end[1], z=body.axis_end[2]),
        length_bp=body.length_bp,
        phase_offset=body.phase_offset,
    )
    new_helices = list(assembly.assembly_helices) + [helix]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_helices": new_helices})
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/linker-helices/{helix_id}", status_code=200)
def delete_linker_helix(helix_id: str) -> dict:
    """Remove a linker helix by id."""
    assembly = assembly_state.get_or_404()
    new_helices = [h for h in assembly.assembly_helices if h.id != helix_id]
    if len(new_helices) == len(assembly.assembly_helices):
        raise HTTPException(404, detail=f"Linker helix {helix_id!r} not found.")
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_helices": new_helices})
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Linker strands ────────────────────────────────────────────────────────────

@router.post("/assembly/linker-strands", status_code=201)
def add_linker_strand(body: AddLinkerStrandRequest) -> dict:
    """
    Append a linker Strand to assembly.assembly_strands.

    Virtual scaffold connections use ids prefixed with '__vsc__' and encode
    endpoint metadata in the notes field as a JSON string.
    """
    import uuid as _uuid
    from backend.core.models import Domain, StrandType
    assembly = assembly_state.get_or_404()

    strand_id = body.id or str(_uuid.uuid4())
    try:
        stype = StrandType(body.strand_type)
    except ValueError:
        stype = StrandType.STAPLE

    domains = []
    for d in (body.domains or []):
        try:
            domains.append(Domain(**d))
        except Exception:
            pass

    strand = Strand(
        id=strand_id,
        strand_type=stype,
        domains=domains,
        color=body.color,
        notes=body.notes,
    )
    new_strands = list(assembly.assembly_strands) + [strand]
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_strands": new_strands})
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/linker-strands/{strand_id}", status_code=200)
def delete_linker_strand(strand_id: str) -> dict:
    """Remove a linker strand by id."""
    assembly = assembly_state.get_or_404()
    new_strands = [s for s in assembly.assembly_strands if s.id != strand_id]
    if len(new_strands) == len(assembly.assembly_strands):
        raise HTTPException(404, detail=f"Linker strand {strand_id!r} not found.")
    assembly_state.snapshot()
    assembly_state.set_assembly_silent(
        assembly.model_copy(update={"assembly_strands": new_strands})
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Linker geometry ───────────────────────────────────────────────────────────

@router.get("/assembly/linker-geometry", status_code=200)
def get_linker_geometry() -> dict:
    """Linker nucleotide geometry for the live assembly (see
    :func:`_linker_geometry_for_assembly`)."""
    return _linker_geometry_for_assembly(assembly_state.get_or_404())
