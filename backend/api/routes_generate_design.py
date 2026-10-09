"""Temporary Help-menu generator. Planning is read-only; construction extends the active timeline."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import Field

from backend.api import state
from backend.api.generation_progress import tracking, report as progress, snapshot
from backend.api.crud import _design_response_with_geometry
from backend.api.generated_history import build_recorded
from backend.core.two_np_generator import GeneratorSettings
from backend.api.branch_optimization import plan_for_generation as plan_generated
from backend.core.validator import validate_design

router = APIRouter()


class GenerateRequest(GeneratorSettings):
    expected_revision: int = Field(ge=0)
    progress_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")


def _source():
    source, revision = state.copy_for_persist()
    if source is None:
        raise HTTPException(
            404,
            detail="Open a design containing two, three, or four gold nanoparticles first.",
        )
    return source, revision


@router.post("/design/generate-design/plan")
def plan_design(settings: GeneratorSettings):
    source, revision = _source()
    try:
        _, report = plan_generated(source, settings)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {
        **report,
        "revision": revision,
        "attachment_status": report.get("attachment_status", "Attachment reach and gold-core clearance are checked during generation."),
    }


@router.post("/design/generate-design")
def generate_design(body: GenerateRequest):
    with tracking(body.progress_id):
        return _generate_design(body)


@router.get("/design/generate-design/progress/{request_id}")
async def generation_progress(request_id: str):
    return snapshot(request_id)


def _generate_design(body):
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
    settings = GeneratorSettings(**body.model_dump(exclude={"expected_revision", "progress_id"}))
    try:
        progress("Planning", "Compare scaffold budgets, cross-sections and particle paths", .02)
        candidate, report = plan_generated(source, settings)
        generated, placement = build_recorded(source, candidate, settings)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    generated = generated.copy_with(id=source.id)
    if state.revision() != revision:
        raise HTTPException(409, detail="Design changed during generation. Recalculate before generating.")
    progress("Validate topology", "Check strands, crossovers and fixed-center attachments", .93)
    validation = validate_design(generated)
    if not validation.passed:
        raise HTTPException(
            422,
            detail={
                "message": "Generated topology did not pass validation.",
                "validation": str(validation),
            },
        )
    from backend.core.generator_validation import check_generated_structure
    progress("CanDo structural check", "Check duplex connectivity and solve linear shape and flexibility", .94)
    try:
        report["structural_validation"] = check_generated_structure(
            generated, placement["generated_helix_ids"]
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    pending_validation = None
    if settings.mechanics in ("fem-linear", "fem-nonlinear", "oxdna"):
        from backend.core.generator_validation import prepare_validation
        from backend.api.assembly import _WORKSPACE_DIR
        from backend.api import doc_context
        progress("Prepare validation", "Snapshot routed design for simulation", .95)
        try:
            pending_validation = prepare_validation(generated, settings.mechanics,
                _WORKSPACE_DIR, doc_id=doc_context.get_current_doc())
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
    # Preserve the active loadout and undo stack. No partial history becomes
    # visible unless all commands finish and the live revision still matches.
    progress("Commit construction history", "Preserve the active loadout and check the document revision", .96)
    state.set_design(generated, expected_revision=revision)
    if pending_validation:
        info, launch = pending_validation
        try:
            launch()
        except Exception as exc:
            info.update(status="failed_to_start", error=str(exc))
        report["validation_job"] = info
    progress("Build display geometry", "Calculate nucleotide positions and helix axes", .98)
    response = _design_response_with_geometry(
        generated, validation, full_feature_log=True
    )
    response["generation"] = {**report, **placement}
    return response
