"""Temporary Help-menu generator. Planning is read-only; construction extends the active timeline."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import Field

from backend.api import state
from backend.api.crud import _design_response_with_geometry
from backend.api.generated_history import build_recorded
from backend.core.two_np_generator import GeneratorSettings, plan_rods
from backend.core.validator import validate_design

router = APIRouter()


class GenerateRequest(GeneratorSettings):
    expected_revision: int = Field(ge=0)


def _source():
    source, revision = state.copy_for_persist()
    if source is None:
        raise HTTPException(
            404, detail="Open a design containing two gold nanoparticles first."
        )
    return source, revision


@router.post("/design/generate-design/plan")
def plan_design(settings: GeneratorSettings):
    source, revision = _source()
    try:
        _, report = plan_rods(source, settings)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        **report,
        "revision": revision,
        "attachment_status": "Attachment reach and gold-core clearance are checked during generation.",
    }


@router.post("/design/generate-design")
def generate_design(body: GenerateRequest):
    source, revision = _source()
    if body.expected_revision != revision:
        raise HTTPException(
            409, detail="Design changed. Recalculate before generating."
        )
    if (
        source.feature_log_cursor not in (-1, len(source.feature_log) - 1)
        or source.feature_log_sub_cursor is not None
    ):
        raise HTTPException(
            409,
            detail="Return to the end of the feature log, or revert to the desired step, before generating.",
        )
    state._assert_active_loadout_editable(source)
    settings = GeneratorSettings(**body.model_dump(exclude={"expected_revision"}))
    try:
        candidate, report = plan_rods(source, settings)
        generated, placement = build_recorded(source, candidate, settings)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    generated = generated.copy_with(id=source.id)
    validation = validate_design(generated)
    if not validation.passed:
        raise HTTPException(
            422,
            detail={
                "message": "Generated topology did not pass validation.",
                "validation": str(validation),
            },
        )
    # Preserve the active loadout and undo stack. No partial history becomes
    # visible unless all commands finish and the live revision still matches.
    state.set_design(generated, expected_revision=revision)
    response = _design_response_with_geometry(
        generated, validation, full_feature_log=True
    )
    response["generation"] = {**report, **placement}
    return response
