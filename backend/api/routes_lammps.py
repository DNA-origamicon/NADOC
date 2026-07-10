"""LAMMPS (CG-DNA / parallel oxDNA) job REST API — Phase 3 of project_lammps_oxdna.

Thin HTTP layer over the lean ``LammpsJob`` model + the ``lammps_runner`` managed-run
orchestration.  Creates a run from the **active design** (reusing the validated oxDNA
topology/conf writers → native LAMMPS-data transcode), launches it in the background,
and exposes list/status/stop.  No UI and no trajectory read-back yet (later phases).

Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core import lammps_runner
from backend.core.lammps_job import LammpsJob, LammpsStatus, new_lammps_job
from backend.core.oxdna_runner import lammps_available
from backend.physics import lammps_interface as L
from backend.physics.oxdna_interface import count_undefined_bases, topology_rows, write_configuration

router = APIRouter(tags=["lammps"])


def _workspace() -> Path:
    return _WORKSPACE_DIR


class CreateLammpsJobRequest(BaseModel):
    steps:              int   = 100_000
    dump_every:         int   = 1000
    temperature:        float = 0.1     # oxDNA reduced units (~300 K)
    salt_molar:         float = 0.5
    ranks:              int   = 1        # MPI ranks (>1 needs an MPI-enabled lmp)
    design_source_path: str | None = None
    # External forces (steer the run like an oxDNA one — see resolve_lammps_forces):
    #   field   = {"field_pN": p, "dir": [x,y,z]}      uniform E-field (needs ≥1 anchor)
    #   wall    = {"dir": [x,y,z], "offset_nm": d, "stiff": s}   axis-aligned surface
    #   anchors = [{"kind": "overhang"|"cluster"|"domain"|"strand"|"base", ...}]
    field:              dict | None = None
    wall:               dict | None = None
    anchors:            list[dict] | None = None
    anchor_stiff:       float | None = None


@router.get("/lammps/available")
async def get_lammps_available() -> dict:
    """Is a CG-DNA-capable LAMMPS installed?
    → ``{available, lammps_bin, cgdna_capable, max_ranks, free_ranks}``.

    ``max_ranks`` is the physical-core ceiling for a run's cores (see
    ``lammps_runner.available_cpu_cores`` for why physical, not logical) so the UI
    can bound the cores input; ``free_ranks`` is how many of those cores are *not*
    currently busy (drives the "use free cores" button — accounts for a NAMD/oxDNA
    run already using cores).  ``free_ranks`` is re-sampled on every call.
    """
    return {**lammps_available(),
            "max_ranks": lammps_runner.available_cpu_cores(),
            "free_ranks": lammps_runner.free_cpu_cores()}


@router.post("/lammps/jobs")
async def create_lammps_job(body: CreateLammpsJobRequest) -> dict:
    """Prepare + launch a LAMMPS oxDNA2 run from the active design.

    Reuses NADOC's oxDNA topology/conf writers, transcodes to a LAMMPS data file, and
    starts a background run.  400s when LAMMPS/CG-DNA is missing or the design is not
    fully sequenced (the same base-definiteness oxDNA requires).
    """
    avail = lammps_available()
    if not avail["available"]:
        raise HTTPException(
            400, "LAMMPS not found. Build it via the MD Engines panel or "
                 "scripts/lammps_doctor.py --fix (see docs/lammps_setup.md).")
    if not avail["cgdna_capable"]:
        raise HTTPException(
            400, "LAMMPS is installed but was built without the CG-DNA package, so it "
                 "cannot run the oxDNA force field. Rebuild with -D PKG_CG-DNA=on.")
    if body.ranks < 1:
        raise HTTPException(400, "ranks must be >= 1")
    max_ranks = lammps_runner.available_cpu_cores()
    if body.ranks > max_ranks:
        plural = "s" if max_ranks != 1 else ""
        raise HTTPException(
            400,
            f"Requested {body.ranks} MPI ranks but only {max_ranks} physical CPU "
            f"core{plural} are available. MPI cannot launch more ranks than cores "
            f"(and hyperthreads don't speed up MD) — reduce ranks to {max_ranks} or fewer.")

    design = design_state.get_or_404()
    name = None
    if body.design_source_path:
        name = Path(body.design_source_path).stem or None
    name = (name or design.metadata.name or "design").replace(" ", "_")

    undefined, _total = count_undefined_bases(design, exclude_reference=True)
    if undefined > 0:
        plural = "s" if undefined != 1 else ""
        raise HTTPException(
            400,
            f"Design has {undefined} undefined base{plural} — the oxDNA force field "
            "LAMMPS runs needs every nucleotide assigned a definite base (A/C/G/T). "
            "Finish assigning sequences before starting a LAMMPS run.")

    from backend.api.crud import _geometry_for_design
    geometry = _geometry_for_design(design, compact_skips=True)

    ws = _workspace()
    job = new_lammps_job(
        name, steps=body.steps, dump_every=body.dump_every,
        temperature=body.temperature, salt_molar=body.salt_molar, ranks=body.ranks,
        design_source_path=body.design_source_path,
    )
    job.status = LammpsStatus.preparing
    job.save(ws)

    params = L.LammpsInputParams(
        steps=body.steps, dump_every=body.dump_every,
        temperature=body.temperature, salt_molar=body.salt_molar)
    prep_kwargs: dict = {}
    if body.field:
        prep_kwargs["field"] = body.field
    if body.wall:
        prep_kwargs["wall"] = body.wall
    if body.anchors:
        prep_kwargs["anchors"] = body.anchors
    if body.anchor_stiff is not None:
        prep_kwargs["anchor_stiff"] = body.anchor_stiff
    try:
        info = lammps_runner.prepare_lammps_job(
            design, geometry, job.job_dir(ws), params, **prep_kwargs)
    except lammps_runner.LammpsError as e:   # e.g. a field with no resolvable anchor
        job.status = LammpsStatus.failed
        job.error = str(e)
        job.save(ws)
        raise HTTPException(400, str(e)) from e
    except ValueError as e:     # e.g. an unsequenced base that slipped the pre-check
        job.status = LammpsStatus.failed
        job.error = str(e)
        job.save(ws)
        raise HTTPException(400, str(e)) from e

    job.n_atoms = info["n_atoms"]
    job.n_bonds = info["n_bonds"]
    job.forces = info.get("forces")
    job.save(ws)

    lammps_runner.start_job(job, ws)
    return job.to_dict()


@router.get("/lammps/jobs")
async def list_lammps_jobs() -> list[dict]:
    ws = _workspace()
    return [lammps_runner.reconcile_lammps_status(j, ws).to_dict()
            for j in LammpsJob.list_jobs(ws)]


@router.get("/lammps/jobs/{job_id}")
async def get_lammps_job(job_id: str) -> dict:
    ws = _workspace()
    try:
        job = LammpsJob.load(job_id, ws)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"No LAMMPS job {job_id!r}") from e
    return lammps_runner.reconcile_lammps_status(job, ws).to_dict()


@router.post("/lammps/jobs/{job_id}/stop")
async def stop_lammps_job(job_id: str) -> dict:
    ws = _workspace()
    if not lammps_runner.stop_job(job_id, ws):
        raise HTTPException(404, f"No running LAMMPS job {job_id!r} to stop")
    return LammpsJob.load(job_id, ws).to_dict()


def _ensure_oxdna_dat(job_dir: Path) -> Path | None:
    """Transcode the job's LAMMPS dump → an oxDNA ``.dat`` trajectory (cached by mtime).

    Returns the ``.dat`` path, or None if there is no (non-empty) LAMMPS trajectory yet.
    """
    dump = job_dir / "traj.lammpstrj"
    if not dump.exists() or dump.stat().st_size == 0:
        return None
    dat = job_dir / "traj.oxdna.dat"
    if not dat.exists() or dat.stat().st_mtime < dump.stat().st_mtime:
        L.lammps_dump_to_oxdna_traj(dump.read_text(), dat)
    return dat


def _traj_inputs(job_id: str):
    """Resolve ``(design, dat_path, ref_path)`` for a run's visualization views.

    Shared by the display / rmsf / deviation / trajectory endpoints: loads the job,
    resolves the **active design** (guarding on a nucleotide-count match — a
    different/edited design can't be mapped onto this run's nucleotides), transcodes
    the LAMMPS dump → an oxDNA ``.dat`` (cached), and ensures a design-pose reference.
    Returns ``(inputs, None)`` on success or ``(None, not_ready_dict)``.
    """
    ws = _workspace()
    try:
        job = LammpsJob.load(job_id, ws)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"No LAMMPS job {job_id!r}") from e

    design = design_state.get_or_404()
    n_now = len(topology_rows(design)[0])
    if job.n_atoms and n_now != job.n_atoms:
        return None, {"ready": False, "reason": (
            f"the loaded design has {n_now} nucleotides but this run used {job.n_atoms} "
            "— load the design this run was made from to view it")}

    job_dir = job.job_dir(ws)
    dat = _ensure_oxdna_dat(job_dir)
    if dat is None:
        return None, {"ready": False, "reason": "no trajectory frames yet"}

    ref = job_dir / "design_ref.dat"
    if not ref.exists():
        from backend.api.crud import _geometry_for_design
        write_configuration(design, _geometry_for_design(design, compact_skips=True), ref)
    return (design, str(dat), str(ref)), None


@router.get("/lammps/jobs/{job_id}/trajectory")
async def get_lammps_trajectory(job_id: str) -> dict:
    """Scrub-able trajectory of a LAMMPS run, in the SAME payload shape as the oxDNA
    trajectory (``keys``/``frames``/``stages``/``markers``) so the viewer is reused.
    Each frame is PBC-unwrapped + Kabsch-aligned to the design pose."""
    from backend.core.oxdna_health import composite_trajectory
    inputs, not_ready = _traj_inputs(job_id)
    if inputs is None:
        return not_ready
    design, dat, ref = inputs
    stages = [("lammps", "production", dat)]
    result = await run_in_threadpool(composite_trajectory, design, stages, ref)
    return {"ready": result["n_frames"] > 0, **result}


@router.get("/lammps/jobs/{job_id}/display")
async def get_lammps_display(job_id: str, align: bool = True) -> dict:
    """The run's final structure as an applyFemPositions update list (the "display"
    view) — the last aligned trajectory frame, same payload shape as the oxDNA one."""
    from backend.core.oxdna_health import composite_trajectory
    inputs, not_ready = _traj_inputs(job_id)
    if inputs is None:
        return not_ready
    design, dat, ref = inputs
    result = await run_in_threadpool(composite_trajectory, design, [("lammps", "production", dat)], ref)
    if not result["n_frames"]:
        return {"ready": False, "positions": [], "stage_name": None}
    keys, last = result["keys"], result["frames"][-1]
    positions = [
        {"helix_id": k[0], "bp_index": k[1], "direction": k[2],
         "copy": k[3] if len(k) == 4 else 0,
         "backbone_position": last[j * 6:j * 6 + 3],
         "nx": last[j * 6 + 3], "ny": last[j * 6 + 4], "nz": last[j * 6 + 5]}
        for j, k in enumerate(keys)
    ]
    return {"ready": True, "positions": positions, "n_positions": len(positions),
            "stage_name": "lammps", "align": align}


@router.get("/lammps/jobs/{job_id}/rmsf")
async def get_lammps_rmsf(job_id: str) -> dict:
    """Per-nucleotide average position + RMSF over the run (the flexibility map) —
    reuses oxDNA's ``production_rmsf`` verbatim on the transcoded trajectory."""
    from backend.core.oxdna_health import production_rmsf, rmsf_confidence
    inputs, not_ready = _traj_inputs(job_id)
    if inputs is None:
        return not_ready
    design, dat, ref = inputs
    result = await run_in_threadpool(production_rmsf, design, [dat], ref, copies=True)
    result["confidence"] = rmsf_confidence(result.get("n_frames", 0))
    result["production_running"] = False
    return result


@router.get("/lammps/jobs/{job_id}/deviation")
async def get_lammps_deviation(job_id: str) -> dict:
    """Per-nucleotide deviation (nm) of the mean structure from the design pose —
    reuses oxDNA's ``production_rmsf`` + ``geometry_deviation_map`` verbatim."""
    from backend.api.skip_twist_tuning import core_reference_geometry
    from backend.core.oxdna_health import (
        geometry_deviation_map, production_rmsf, rmsf_confidence,
    )
    inputs, not_ready = _traj_inputs(job_id)
    if inputs is None:
        return not_ready
    design, dat, ref = inputs

    def _compute():
        mean = production_rmsf(design, [dat], ref, copies=True)
        if not mean.get("ready") or not mean.get("positions"):
            return None, mean
        return geometry_deviation_map(mean["positions"], core_reference_geometry(design)), mean

    dev, mean = await run_in_threadpool(_compute)
    if dev is None:
        return {"ready": False, "reason": "no frames yet"}
    dev["confidence"] = rmsf_confidence(mean.get("n_frames", 0))
    dev["production_running"] = False
    return {"ready": True, "n_frames": mean.get("n_frames"), **dev}
