"""Job-state rules for editing NAMD simulation regions."""

from fastapi import HTTPException
import json
from backend.api.simulation_submodel import SubmodelBox, read_selection, save_selection
from backend.core.md_job import MdStatus


def require_prepared_selection(job, workspace):
    """Never interpret an older display-only region as a prepared submodel."""
    box = read_selection(job.job_dir(workspace))["box"]
    recipe_path = job.package_dir(workspace) / "submodel.json"
    prepared = (
        json.loads(recipe_path.read_text()).get("box") if recipe_path.exists() else None
    )

    def geometry(value):
        normalized = SubmodelBox(**value).model_dump(mode="json") if value else {}
        return {k: v for k, v in normalized.items() if k != "visible"}

    if geometry(box) != geometry(prepared):
        raise HTTPException(
            409,
            "The saved submodel does not match the prepared simulation. Create and prepare a new relaxation with this region before running.",
        )


def save_job_selection(
    job, workspace, selection, *, clear_artifacts, reset_runtime, editable
):
    directory = job.job_dir(workspace)
    old = read_selection(directory)
    new = selection.model_dump(mode="json")

    def geometry(record):
        return {k: v for k, v in (record.get("box") or {}).items() if k != "visible"}

    if geometry(old) != geometry(new):
        if not editable(job) or job.run_kind == "production":
            raise HTTPException(
                409,
                "This job's simulation region is frozen. Copy the relaxation to change its submodel.",
            )
        if job.status == MdStatus.queued:
            if (job.minimization and job.minimization.status != "pending") or any(
                segment.status != "pending" for segment in job.segments
            ):
                raise HTTPException(
                    409, "The submodel cannot change after simulation has started"
                )
            # Unstarted inputs may be rebuilt; retain the exact Design snapshot.
            snapshot = directory / "design.json"
            source = snapshot.read_bytes() if snapshot.exists() else None
            clear_artifacts(job)
            if source is not None:
                snapshot.write_bytes(source)
            reset_runtime(job)
            job.package_subdir = ""
            job.name_stem = ""
            job.status = MdStatus.draft
        job.prep_params = {**(job.prep_params or {}), "submodel": new["box"]}
        if job.prep_params_set is not None:
            job.prep_params_set = sorted(set(job.prep_params_set) | {"submodel"})
        job.save(workspace)
    return save_selection(directory, selection)
