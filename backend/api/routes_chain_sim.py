"""
API layer — Chain Simulations project route handlers.

A *chain-simulation project* is a named, editable queue of MD chain stages the
user authors in the "Chain Simulations" sidebar. It is persisted ON THE DESIGN
(like a ``DesignAnimation``) so a chain plan travels with the ``.nadoc`` and
survives reload; the Launch step later turns a project into one or more live
``MdPipeline`` chains via ``POST /md/chains``.

These endpoints only mutate ``design.chain_sim_projects`` — display/job-request
annotation state, never a topology or geometry edit (Three-Layer Law). They
mirror ``routes_animations.py`` field-for-field (create / rename / delete +
one bulk stage-list replace); ``_design_response`` re-syncs the frontend store.

Routes
------
  POST   /design/chain-sim-projects                — create project
  PATCH  /design/chain-sim-projects/{project_id}   — rename
  DELETE /design/chain-sim-projects/{project_id}   — remove
  PUT    /design/chain-sim-projects/{project_id}/stages — replace the ordered stage list

Mounting is done in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.crud import _design_response
from backend.core.models import ChainSimProject, ChainSimStage

router = APIRouter()


class CreateChainSimProjectBody(BaseModel):
    name: str = "Chain"
    # Optional initial stages (used by Duplicate, which creates then fills in one call
    # is also fine — but accepting stages here keeps a duplicate atomic).
    stages: Optional[List[ChainSimStage]] = None


class PatchChainSimProjectBody(BaseModel):
    name: Optional[str] = None


class SetChainSimStagesBody(BaseModel):
    stages: List[ChainSimStage] = Field(default_factory=list)


@router.post("/design/chain-sim-projects", status_code=200)
def create_chain_sim_project(body: CreateChainSimProjectBody) -> dict:
    """Create a new named chain-simulation project. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    project = ChainSimProject(name=body.name, stages=body.stages or [])
    updated = design.model_copy(
        update={"chain_sim_projects": list(design.chain_sim_projects) + [project]},
        deep=True,
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/chain-sim-projects/{project_id}", status_code=200)
def update_chain_sim_project(project_id: str, body: PatchChainSimProjectBody) -> dict:
    """Rename a chain-simulation project. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    projects = list(design.chain_sim_projects)
    idx = next((i for i, p in enumerate(projects) if p.id == project_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Chain-sim project {project_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    projects[idx] = projects[idx].model_copy(update=patch)
    updated = design.model_copy(update={"chain_sim_projects": projects}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/chain-sim-projects/{project_id}", status_code=200)
def delete_chain_sim_project(project_id: str) -> dict:
    """Remove a chain-simulation project. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    projects = [p for p in design.chain_sim_projects if p.id != project_id]
    if len(projects) == len(design.chain_sim_projects):
        raise HTTPException(404, detail=f"Chain-sim project {project_id!r} not found.")

    updated = design.model_copy(update={"chain_sim_projects": projects}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.put("/design/chain-sim-projects/{project_id}/stages", status_code=200)
def set_chain_sim_stages(project_id: str, body: SetChainSimStagesBody) -> dict:
    """Replace a project's ordered stage list (every queue edit goes through here)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    projects = list(design.chain_sim_projects)
    idx = next((i for i, p in enumerate(projects) if p.id == project_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Chain-sim project {project_id!r} not found.")

    projects[idx] = projects[idx].model_copy(update={"stages": list(body.stages)})
    updated = design.model_copy(update={"chain_sim_projects": projects}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)
