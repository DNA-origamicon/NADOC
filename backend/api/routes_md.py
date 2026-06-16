"""
MD Job routes — create, inspect, and control NAMD simulation jobs.

All routes are prefixed with /api (set in main.py).

Route summary
─────────────
POST  /md/jobs                      create (and prepare) a new MD job
GET   /md/jobs                      list all jobs
GET   /md/jobs/{job_id}             single job status
POST  /md/jobs/{job_id}/start       start or resume a queued/stopped job
POST  /md/jobs/{job_id}/stop        stop a running job
POST  /md/jobs/{job_id}/production  append an unrestrained production stage
DELETE /md/jobs/{job_id}            delete job and generated files
GET   /md/jobs/{job_id}/health      health.jsonl records
GET   /md/jobs/{job_id}/metrics     metrics.jsonl records
GET   /md/jobs/{job_id}/display     latest displayable NADOC MD trajectory
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.md_protocols import (
    EQUILIBRIUM_AWARE_PROTOCOL,
    SUPPORTED_PROTOCOLS,
    SegmentSpec,
    prepare_mgh_slow_release,
    prepare_equilibrium_aware_namd,
    segments_from_manifest,
)
from backend.core.md_prep_progress import (
    PrepTracker,
    build_prep_phases,
    clear_prep_progress,
    design_size_factor,
    write_prep_progress,
)
from backend.core.namd_runner import default_threads, find_gmx, find_namd, is_running, reconcile_job_status, start_job, stop_job

logger = logging.getLogger(__name__)


router = APIRouter(tags=["md"])

# Background preparation tasks, kept referenced so the event loop doesn't GC them
# mid-run (asyncio only holds weak references to tasks).
_PREP_TASKS: set[asyncio.Task] = set()


# ── Request/response models ────────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    protocol:    str   = Field(EQUILIBRIUM_AWARE_PROTOCOL, description="Protocol preset name")
    threads:     int   = Field(default_factory=default_threads, ge=1,
                               description="NAMD +p thread count; defaults to half the logical CPUs")
    devices:     str   = Field("0", description="CUDA device IDs (e.g. '0' or '0,1')")
    autostart:   bool  = Field(False, description="Start NAMD immediately after preparation")
    salt_mode:   str   = Field("screening", description="'screening' uses validated origami screening defaults; 'custom' uses Mg/NaCl fields")
    # Advanced overrides (all optional)
    ion_conc_mM: float = Field(0.0,  ge=0.0)
    mg_conc_mM:  float = Field(12.5, ge=0.0)
    padding_nm:  float = Field(1.2,  gt=0.0)
    minimize_steps: int = Field(4_800, ge=100)
    declash: bool = Field(
        False,
        description="Force the declash protocol (auto-enabled anyway for designs with crossover extra bases, e.g. 2xT thymines)",
    )
    design_source_path: Optional[str] = Field(
        None,
        description="Workspace path of the part used to create this job",
    )
    oxdna_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed oxDNA job's "
                    "relaxed coordinates (its OWN design.json + latest last_conf) "
                    "instead of ideal B-DNA.",
    )


class ProductionRequest(BaseModel):
    length_ns: Optional[float] = Field(None, gt=0.0, le=100.0)
    steps: Optional[int] = Field(None, ge=100, le=50_000_000)
    autostart: bool = Field(True)
    continue_from_production: bool = Field(False)


class JobSummary(BaseModel):
    job_id:         str
    design_name:    str
    protocol:       str
    status:         str
    created_at:     float
    n_segments:     int
    current_segment_idx: int
    error:          Optional[str]
    latest_health:  Optional[dict]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    return _WORKSPACE_DIR


def _load_job(job_id: str) -> MdJob:
    try:
        return reconcile_job_status(MdJob.load(job_id, _workspace()), _workspace())
    except FileNotFoundError:
        raise HTTPException(404, f"MD job {job_id!r} not found")
    except Exception as exc:
        raise HTTPException(500, f"Failed to load job {job_id}: {exc}")


def _jsonl_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _job_to_summary(job: MdJob) -> JobSummary:
    latest = job.health_samples[-1] if job.health_samples else None
    latest_dict = None
    if latest is not None:
        from dataclasses import asdict
        latest_dict = asdict(latest)
    return JobSummary(
        job_id               = job.job_id,
        design_name          = job.design_name,
        protocol             = job.protocol,
        status               = job.status.value,
        created_at           = job.created_at,
        n_segments           = len(job.segments),
        current_segment_idx  = job.current_segment_idx,
        error                = job.error,
        latest_health        = latest_dict,
    )


def _latest_display_segment(job: MdJob) -> tuple[Optional[str], Optional[Path]]:
    package_dir = job.package_dir(_workspace())
    output_dir = package_dir / "output"
    candidates = []
    if 0 <= job.current_segment_idx < len(job.segments):
        candidates.append(job.segments[job.current_segment_idx])
    candidates.extend(reversed(job.segments))

    seen: set[str] = set()
    for seg in candidates:
        if seg.name in seen:
            continue
        seen.add(seg.name)
        # Prefer the newest trajectory for this segment: a resumed segment writes
        # its continuation frames to <seg>.contN.dcd, leaving the pre-checkpoint
        # <seg>.dcd intact.  Pick whichever was written most recently.
        dcds = [
            d
            for d in (
                *output_dir.glob(f"{seg.name}.cont*.dcd"),
                output_dir / f"{seg.name}.dcd",
                package_dir / f"{seg.name}.dcd",
            )
            if d.exists() and d.stat().st_size > 0
        ]
        if dcds:
            return seg.name, max(dcds, key=lambda d: d.stat().st_mtime)
    return None, None


def _display_dcd_freq(steps: int) -> int:
    return max(100, min(10_000, int(steps) // 50))


def _production_checkpoint_warning(job: MdJob, spec: SegmentSpec, *, fallback_reason: str = "") -> str:
    warnings: list[str] = []
    if fallback_reason:
        warnings.append(fallback_reason)

    sample = next((h for h in reversed(job.health_samples) if h.segment == spec.name), None)
    if sample is None:
        warnings.append("No health metrics were recorded for this checkpoint.")
    else:
        if not sample.passed:
            warnings.append(f"Checkpoint health did not pass: {sample.reason or 'unknown reason'}.")
        if sample.c1_paired_fraction is not None and sample.c1_paired_fraction < 0.95:
            warnings.append(
                f"C1' paired fraction is {sample.c1_paired_fraction * 100:.1f}%, "
                "below the normal 95.0% production qualification target."
            )
        if sample.wc_ref_relative_fraction is not None and sample.wc_ref_relative_fraction < 0.80:
            warnings.append(
                f"WC ref-relative pairing is {sample.wc_ref_relative_fraction * 100:.1f}%, "
                "below the normal 80.0% production qualification target."
            )
    return " ".join(warnings)


def _completed_production_checkpoint(job: MdJob) -> tuple[Optional[int], Optional[SegmentSpec], str]:
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return None, None, "manifest.json not found"
    _, specs = segments_from_manifest(manifest_path)
    done = {s.name for s in job.segments if s.status == "done"}
    output = package_dir / "output"
    for idx in range(min(len(specs), len(job.segments)) - 1, -1, -1):
        spec = specs[idx]
        stage_l = spec.stage.lower()
        name_l = spec.name.lower()
        if "production" not in stage_l and "prod" not in name_l:
            continue
        if spec.name not in done:
            continue
        has_restart = all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "vel", "xsc"))
        if not has_restart:
            continue
        return idx, spec, ""
    return None, None, "No completed production checkpoint is available to continue from."


def _production_ready_checkpoint(job: MdJob) -> tuple[Optional[int], Optional[SegmentSpec], str, str]:
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.exists():
        return None, None, "manifest.json not found", ""
    _, specs = segments_from_manifest(manifest_path)
    done = {s.name for s in job.segments if s.status == "done"}
    passed = {h.segment for h in job.health_samples if h.passed}
    latest_restrained: SegmentSpec | None = None
    latest_restrained_idx: Optional[int] = None
    latest_unqualified: tuple[int, SegmentSpec] | None = None
    for idx in range(min(len(specs), len(job.segments)) - 1, -1, -1):
        spec = specs[idx]
        if spec.name not in done:
            continue
        if passed and spec.name not in passed:
            continue
        output = package_dir / "output"
        has_restart = all((output / f"{spec.name}.{ext}").exists() for ext in ("coor", "vel", "xsc"))
        if not has_restart:
            continue
        stage_l = spec.stage.lower()
        name_l = spec.name.lower()
        if spec.scale is not None:
            if latest_restrained is None:
                latest_restrained = spec
                latest_restrained_idx = idx
            continue
        if "production" in stage_l or "prod" in name_l:
            continue
        if "probe" in stage_l or "probe" in name_l or "qualification" in stage_l or "qual" in name_l:
            return idx, spec, "", _production_checkpoint_warning(job, spec)
        if latest_unqualified is None:
            latest_unqualified = (idx, spec)

    if job.status == MdStatus.completed and latest_unqualified is not None:
        idx, spec = latest_unqualified
        warning = _production_checkpoint_warning(
            job,
            spec,
            fallback_reason=(
                "Production is enabled from a completed relaxation checkpoint, "
                "but no unrestrained qualification/probe stage was run."
            ),
        )
        return idx, spec, "", warning

    if job.status == MdStatus.completed and latest_restrained is not None and latest_restrained_idx is not None:
        warning = _production_checkpoint_warning(
            job,
            latest_restrained,
            fallback_reason=(
                "Production is enabled from a completed relaxation checkpoint that "
                "still had ENM restraints; this is normally blocked unless explicitly allowed."
            ),
        )
        return latest_restrained_idx, latest_restrained, "", warning

    if latest_restrained is not None:
        return (
            None,
            None,
            f"Latest passing checkpoint is still restrained ({latest_restrained.stage}); "
            "run an unrestrained qualification/probe before production.",
            "",
        )
    return None, None, "No passing unrestrained qualification/probe checkpoint is available yet", ""


def _seed_production_available(job: MdJob) -> bool:
    """Always False — an oxDNA-seeded job must run the restrained NAMD relaxation
    ladder before production; it can no longer jump straight to unrestrained
    production from the seed.

    The old shortcut (minimize-then-produce, skipping the ENM ladder) blew up:
    oxDNA relaxes only the COARSE structure, and reconstructing all-atom coords
    from it leaves residual steric strain (sidechains, fresh solvent, the ~10%
    oxDNA-vs-B-DNA duplex-width mismatch).  Jumping to unrestrained 310 K NPT
    exceeded the velocity limit within ~200 steps ("atoms moving too fast").  The
    seed's value is a better *global* starting shape for the SAME restrained ladder
    (00_min ENM → k0.5 → k0.1 → k0.01 → release), which the relaxation start runs
    from the seeded solvated PDB — not skipping atomistic relaxation."""
    return False


def _conservative_production_conf(spec: SegmentSpec, name_stem: str,
                                  box: tuple[float, float, float],
                                  mgh_extrabonds: bool) -> str:
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

seed               54321
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         10.0
cutoff             12.0
pairlistdist       14.0
PME                yes
PMEGridSpacing     1.0
rigidBonds         none
rigidTolerance     1.0e-8
timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
langevin           on
langevinTemp       310
langevinDamping    1.0
langevinHydrogen   off
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  400.0
langevinPistonDecay   200.0
langevinPistonTemp 310
outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
constraints        off
outputName         output/{spec.name}
dcdFile            output/{spec.name}.dcd
dcdFreq            {spec.dcd_freq}
xstFile            output/{spec.name}.xst
binCoordinates     output/{spec.previous}.coor
binVelocities      output/{spec.previous}.vel
extendedSystem     output/{spec.previous}.xsc
run                {spec.steps}
"""


def _seed_production_conf(spec: SegmentSpec, name_stem: str,
                         box: tuple[float, float, float],
                         mgh_extrabonds: bool, minimize_steps: int) -> str:
    """Production conf that starts DIRECTLY from the oxDNA-seeded solvated
    structure (no relaxation checkpoint): minimize first to clear fresh-solvent
    clashes, assign velocities at 310 K, then run unrestrained.  Used when the
    user skips the NAMD relaxation ladder on a seeded job."""
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    return f"""\
structure          {name_stem}.psf
coordinates        {name_stem}.pdb

seed               54321
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         10.0
cutoff             12.0
pairlistdist       14.0
PME                yes
PMEGridSpacing     1.0
rigidBonds         none
rigidTolerance     1.0e-8
timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
langevin           on
langevinTemp       310
langevinDamping    1.0
langevinHydrogen   off
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  400.0
langevinPistonDecay   200.0
langevinPistonTemp 310
outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
constraints        off
outputName         output/{spec.name}
dcdFile            output/{spec.name}.dcd
dcdFreq            {spec.dcd_freq}
xstFile            output/{spec.name}.xst
temperature        310
minimize           {minimize_steps}
reinitvels         310
run                {spec.steps}
"""


def _production_steps_and_ns(body: ProductionRequest) -> tuple[int, float]:
    if body.steps is not None:
        steps = max(100, int(body.steps))
        return steps, steps / 1_000_000.0
    length_ns = body.length_ns if body.length_ns is not None else 1.0
    steps = max(100, int(round(length_ns * 1_000_000)))  # 1 fs/step
    return steps, steps / 1_000_000.0


def _append_production_segments(
    job: MdJob,
    total_steps: int,
    *,
    continue_from_production: bool = False,
) -> list[SegmentSpec]:
    from_seed = False
    if continue_from_production:
        checkpoint_idx, checkpoint, reason = _completed_production_checkpoint(job)
        warning = ""
        if checkpoint is None:
            raise HTTPException(400, reason)
        checkpoint_name = checkpoint.name
    else:
        checkpoint_idx, checkpoint, reason, warning = _production_ready_checkpoint(job)
        if checkpoint is None:
            # No relaxation checkpoint — but an oxDNA-seeded job can produce
            # directly from its relaxed solvated structure (minimize-then-produce).
            if _seed_production_available(job):
                from_seed = True
                checkpoint_name = "oxdna_seed"
                warning = ("NAMD relaxation skipped: the oxDNA-seeded structure is "
                           "minimized then produced unrestrained. Watch the first frames.")
            else:
                raise HTTPException(400, reason)
        else:
            checkpoint_name = checkpoint.name
    package_dir = job.package_dir(_workspace())
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    min_steps = int(manifest.get("minimization", {}).get("steps", 4800) or 4800)

    existing = {s["name"] for s in manifest.get("segments", [])}
    stage_idx = len({s["stage"] for s in manifest.get("segments", [])}) + 1
    length_ns = total_steps / 1_000_000.0
    label_ns = f"{length_ns:g}".replace(".", "p")
    previous = "" if from_seed else checkpoint.name
    segments: list[SegmentSpec] = []
    for pct, frac in ((10.0, 0.10), (50.0, 0.40), (100.0, 0.50)):
        steps = max(100, int(round(total_steps * frac)))
        name = f"{name_stem}_{stage_idx:02d}_production_{label_ns}ns_k0_p{int(pct)}"
        if name in existing:
            previous = name
            continue
        spec = SegmentSpec(
            name=name,
            stage=f"{length_ns:g} ns conservative production run",
            percent=pct,
            steps=steps,
            temp=310.0,
            damping=1.0,
            scale=None,
            npt=True,
            previous=previous,
            reinit=False,
            dcd_freq=_display_dcd_freq(steps),
            min_c1_paired=0.90,
            min_wc_ref_relative=0.25,
        )
        # The FIRST from-seed segment starts from the solvated PDB (minimize +
        # heat); every later split-segment continues from the prior restart.
        if from_seed and not previous:
            conf = _seed_production_conf(spec, name_stem, box, mgh_extrabonds, min_steps)
        else:
            conf = _conservative_production_conf(spec, name_stem, box, mgh_extrabonds)
        (package_dir / f"{spec.name}.conf").write_text(conf)
        segments.append(spec)
        previous = name

    if not segments:
        raise HTTPException(400, "A production stage with this length already exists")

    start_idx = len(manifest["segments"])
    manifest["segments"].extend(asdict(s) for s in segments)
    manifest["production_extension"] = {
        "length_ns": length_ns,
        "steps": total_steps,
        "previous": checkpoint_name,
        "from_seed": from_seed,
        "continue_from_production": continue_from_production,
        "first_new_segment": segments[0].name,
        "last_new_segment": segments[-1].name,
        "timestep_fs": 1.0,
        "settings": "conservative_unrestrained",
        "health_gate": {"min_c1_paired": 0.90, "min_wc_ref_relative": 0.25},
        "advisory_gate": {"wc_ref_relative": 0.75},
        "warning": warning,
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    job.segments.extend(
        MdSegmentStatus(
            name=s.name,
            stage=s.stage,
            percent=s.percent,
            steps=s.steps,
            status="pending",
        )
        for s in segments
    )
    job.current_segment_idx = start_idx
    job.status = MdStatus.queued
    job.error = None
    job.user_stopped = False  # new work to do — allow auto-resume again
    job.save(_workspace())
    return segments


# ── Routes ─────────────────────────────────────────────────────────────────────

def _sequenced_base_count(design) -> int:
    return sum(
        sum(1 for c in (s.sequence or "") if c.upper() in "ACGT")
        for s in design.strands
    )


_NO_SEQUENCE_MSG = (
    "Design has no sequence assigned — every nucleotide would be written as "
    "thymine (THY), making the topology physically meaningless. "
    "Assign a scaffold sequence (e.g. M13mp18) and staple sequences before "
    "starting an MD run."
)


@router.post("/md/jobs")
async def create_md_job(body: CreateJobRequest) -> dict:
    """Create a new MD job and prepare it (solvation + config gen) in the background.

    Returns immediately with status=``preparing`` and a ``job_id``.  The caller
    subscribes to ``/ws/md-jobs/{job_id}`` to watch a live, ETA-bearing progress
    bar (the ``prep_progress`` field) while solvation runs, and to learn whether
    prep ended in ``queued`` (success) or ``failed``.  Previously this endpoint
    blocked for the whole 60-120 s+ preparation, so the UI could only show an
    indeterminate spinner with no ETA and no way to detect a hung run.
    """
    if body.protocol not in SUPPORTED_PROTOCOLS:
        raise HTTPException(400, f"Unknown protocol: {body.protocol!r}")
    if body.salt_mode not in {"screening", "custom"}:
        raise HTTPException(400, f"Unknown salt_mode: {body.salt_mode!r}")

    ion_conc_mM = body.ion_conc_mM
    mg_conc_mM = body.mg_conc_mM
    if body.salt_mode == "screening":
        # Validated one-button default for DNA origami: neutralizing Na+ plus
        # 12.5 mM MgCl2/MGH screening, no extra bulk NaCl.  The neutralizing
        # counterions are computed from the audited topology charge downstream.
        ion_conc_mM = 0.0
        mg_conc_mM = 12.5

    # Engine availability is cheap — fail fast (synchronously) so the user gets a
    # 400 instead of a job that immediately fails in the background.
    try:
        logger.info("create_md_job: NAMD=%s", find_namd())
        logger.info("create_md_job: GROMACS=%s", find_gmx())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    seeded = bool(body.oxdna_job_id)
    if seeded:
        # The seed's design lives on disk (oxDNA job snapshot); it is resolved in
        # the background worker so its (slow) reconstruction shows on the progress
        # bar.  A cheap up-front existence check still rejects a bad oxdna_job_id
        # with a fast 400 before any work is queued.
        from backend.core.oxdna_runner import assert_namd_seed_available  # noqa: PLC0415
        try:
            await run_in_threadpool(assert_namd_seed_available, body.oxdna_job_id, _workspace())
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))
        design = None
        name = "design"               # provisional; replaced once the seed builds
        size_factor = 1.0
    else:
        # The active design is request-scoped (doc session contextvar), so it must
        # be captured here on the request thread, not in the background worker.
        design = design_state.get_or_404()
        if _sequenced_base_count(design) == 0:
            raise HTTPException(400, _NO_SEQUENCE_MSG)
        name = (design.metadata.name or "design").replace(" ", "_")
        size_factor = design_size_factor(design)

    job = new_job(
        design_name    = name,
        protocol       = body.protocol,
        name_stem      = "",       # filled in after prep
        package_subdir = "",       # filled in after prep
        threads        = body.threads,
        devices        = body.devices,
        design_source_path = body.design_source_path,
        seed_oxdna_job_id  = body.oxdna_job_id if seeded else None,
    )
    job.status = MdStatus.preparing
    job.save(_workspace())
    logger.info("create_md_job: job_id=%s design=%s protocol=%s seeded=%s",
                job.job_id, name, body.protocol, seeded)

    tracker = PrepTracker(
        build_prep_phases(seeded=seeded, size_factor=size_factor),
        clock=time.monotonic,
    )
    write_prep_progress(job.job_dir(_workspace()), tracker.snapshot())

    task = asyncio.create_task(_prepare_job_bg(
        job_id      = job.job_id,
        body        = body,
        design      = design,
        seeded      = seeded,
        ion_conc_mM = ion_conc_mM,
        mg_conc_mM  = mg_conc_mM,
        tracker     = tracker,
    ))
    _PREP_TASKS.add(task)
    task.add_done_callback(_PREP_TASKS.discard)

    return job.to_dict()


async def _prepare_job_bg(
    *,
    job_id: str,
    body: CreateJobRequest,
    design,
    seeded: bool,
    ion_conc_mM: float,
    mg_conc_mM: float,
    tracker: PrepTracker,
) -> None:
    """Background preparation: build seed (if any) → solvate → ENM → configs.

    Streams progress into ``{job_dir}/prep_progress.json`` via a 1 Hz heartbeat
    so the status websocket can render a live bar + ETA.  On any failure the job
    is marked ``failed`` with the error; on success ``queued`` (+ autostart).
    """
    ws = _workspace()
    job_dir = MdJob.load(job_id, ws).job_dir(ws)

    async def _heartbeat() -> None:
        try:
            while not tracker.is_done():
                write_prep_progress(job_dir, tracker.snapshot())
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    hb = asyncio.create_task(_heartbeat())

    try:
        seed_model = None
        if seeded:
            from backend.core.oxdna_runner import build_namd_seed  # noqa: PLC0415
            tracker.report("seed", None, "Reconstructing relaxed atomic model…")
            seed = await run_in_threadpool(build_namd_seed, body.oxdna_job_id, ws)
            local_design = seed.design
            seed_model = seed.atomistic_model
            seed_name = (local_design.metadata.name or "design").replace(" ", "_")
            job = MdJob.load(job_id, ws)
            job.design_name = seed_name
            job.save(ws)
            logger.info("prep %s: seeded from oxDNA job %s (stage %s)",
                        job_id, body.oxdna_job_id, seed.stage_name)
        else:
            local_design = design

        if _sequenced_base_count(local_design) == 0:
            raise RuntimeError(_NO_SEQUENCE_MSG)

        prepare = (
            prepare_equilibrium_aware_namd
            if body.protocol == EQUILIBRIUM_AWARE_PROTOCOL
            else prepare_mgh_slow_release
        )
        package_subdir, name_stem, segments = await run_in_threadpool(
            prepare,
            local_design,
            job_dir,
            ion_conc_mM     = ion_conc_mM,
            mg_conc_mM      = mg_conc_mM,
            salt_mode       = body.salt_mode,
            padding_nm      = body.padding_nm,
            minimize_steps  = body.minimize_steps,
            atomistic_model = seed_model,
            declash         = body.declash,
            progress        = tracker.report,
        )
        logger.info("prep %s: done; package=%s name_stem=%s segments=%d",
                    job_id, package_subdir, name_stem, len(segments))
    except Exception as exc:
        logger.error("prep %s: FAILED: %s", job_id, exc, exc_info=True)
        tracker.fail(str(exc))
        hb.cancel()
        job = MdJob.load(job_id, ws)
        job.status = MdStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(ws)
        clear_prep_progress(job_dir)
        return

    tracker.finish()
    hb.cancel()

    job = MdJob.load(job_id, ws)
    job.package_subdir = package_subdir
    job.name_stem      = name_stem
    job.segments       = [
        MdSegmentStatus(
            name    = s.name,
            stage   = s.stage,
            percent = s.percent,
            steps   = s.steps,
            status  = "pending",
        )
        for s in segments
    ]
    job.status = MdStatus.queued
    job.save(ws)
    clear_prep_progress(job_dir)

    if body.autostart:
        logger.info("prep %s: autostart=True, launching", job_id)
        start_job(job, ws)


@router.get("/md/jobs")
async def list_md_jobs() -> list[dict]:
    jobs = MdJob.list_jobs(_workspace())
    jobs = [reconcile_job_status(j, _workspace()) for j in jobs]
    return [j.to_dict() for j in jobs]


@router.get("/md/jobs/{job_id}")
async def get_md_job(job_id: str) -> dict:
    job = _load_job(job_id)
    return job.to_dict()


@router.get("/md/jobs/{job_id}/display")
async def get_md_job_display(job_id: str) -> dict:
    """Return the manifest and latest segment suitable for DNA-only display."""
    job = _load_job(job_id)
    package_dir = job.package_dir(_workspace())
    manifest = package_dir / "nadoc_md_run.json"
    if not manifest.exists():
        manifest = package_dir / "manifest.json"

    segment_name, dcd_path = _latest_display_segment(job)
    ready_idx, ready_spec, ready_reason, ready_warning = _production_ready_checkpoint(job)
    continue_idx, continue_spec, continue_reason = _completed_production_checkpoint(job)
    ready = manifest.exists() and dcd_path is not None
    busy = job.status in {MdStatus.running, MdStatus.preparing}

    # Seeded jobs no longer skip relaxation — they run the restrained ladder from
    # the seed, then produce from its checkpoint like any job (from_seed removed).
    from_seed = False
    production_ready = ready_spec is not None and not busy
    if ready_spec is not None:
        production_checkpoint = ready_spec.name
        production_warning = ready_warning
    else:
        production_checkpoint = None
        production_warning = ""

    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "ready": ready,
        "config_path": str(manifest.resolve()) if manifest.exists() else None,
        "package_dir": str(package_dir.resolve()) if package_dir.exists() else None,
        "segment_name": segment_name,
        "trajectory_path": str(dcd_path.resolve()) if dcd_path else None,
        "production_ready": production_ready,
        "production_from_seed": from_seed,
        "production_checkpoint": production_checkpoint,
        "production_ready_reason": "" if production_ready else ready_reason,
        "production_warning": production_warning if production_ready else "",
        "production_continue_available": continue_spec is not None,
        "production_continue_checkpoint": continue_spec.name if continue_spec else None,
        "production_continue_reason": "" if continue_spec else continue_reason,
    }


@router.delete("/md/jobs/{job_id}")
async def delete_md_job(job_id: str) -> dict:
    """Delete an MD job and every generated file/folder beneath its job dir."""
    job = _load_job(job_id)
    if is_running(job_id) or job.status == MdStatus.running:
        raise HTTPException(400, "Stop the MD job before deleting it")
    job_dir = job.job_dir(_workspace())
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"ok": True, "job_id": job_id, "deleted": str(job_dir)}


@router.post("/md/jobs/{job_id}/production")
async def append_md_production(job_id: str, body: ProductionRequest) -> dict:
    """Append a final production stage after the restraint-release ladder passes."""
    job = _load_job(job_id)
    if is_running(job_id) or job.status in (MdStatus.running, MdStatus.preparing):
        raise HTTPException(400, "Cannot append production while the job is running")
    total_steps, length_ns = _production_steps_and_ns(body)
    segments = _append_production_segments(
        job,
        total_steps,
        continue_from_production=body.continue_from_production,
    )
    job = _load_job(job_id)
    if body.autostart:
        job.status = MdStatus.running
        job.save(_workspace())
        start_job(job, _workspace())
    return {
        "ok": True,
        "job": job.to_dict(),
        "segments_added": [s.name for s in segments],
        "steps": total_steps,
        "length_ns": length_ns,
        "autostart": body.autostart,
    }


@router.post("/md/jobs/{job_id}/start")
async def start_md_job(job_id: str) -> dict:
    """Start or resume a queued/stopped/failed job."""
    job = _load_job(job_id)

    if is_running(job_id):
        return {"ok": True, "message": "Job already running"}

    if job.status in (MdStatus.running, MdStatus.completed):
        raise HTTPException(400, f"Job is {job.status.value} — cannot start")

    # Re-check NAMD available
    try:
        find_namd()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))

    job.status = MdStatus.running
    job.error = None
    job.user_stopped = False  # explicit (re)start clears the no-auto-resume flag
    job.save(_workspace())

    start_job(job, _workspace())
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.post("/md/jobs/{job_id}/stop")
async def stop_md_job(job_id: str) -> dict:
    """Cancel a running job."""
    job = _load_job(job_id)

    # Mark as user-stopped so the startup/supervisor auto-resume leaves it alone.
    job.user_stopped = True
    job.save(_workspace())

    cancelled = stop_job(job_id, _workspace())
    if not cancelled:
        # Not in our task registry — job may have completed or never started
        if job.status == MdStatus.running:
            job.status = MdStatus.stopped
            job.save(_workspace())
        return {"ok": True, "message": "Job was not actively running"}

    return {"ok": True, "job_id": job_id, "status": "stopping"}


@router.get("/md/jobs/{job_id}/health")
async def get_md_job_health(job_id: str) -> list[dict]:
    """Return all health.jsonl records for the job."""
    job = _load_job(job_id)
    health_path = job.package_dir(_workspace()) / "output" / "health.jsonl"
    return _jsonl_records(health_path)


@router.get("/md/jobs/{job_id}/metrics")
async def get_md_job_metrics(job_id: str) -> list[dict]:
    """Return all metrics.jsonl records for the job."""
    job = _load_job(job_id)
    metrics_path = job.package_dir(_workspace()) / "output" / "metrics.jsonl"
    return _jsonl_records(metrics_path)


@router.get("/md/namd-available")
async def namd_available() -> dict:
    """Check whether NAMD3 and GROMACS are accessible."""
    try:
        namd_path = find_namd()
        namd_ok = True
    except RuntimeError:
        namd_path = None
        namd_ok = False

    try:
        gmx_path = find_gmx()
        gmx_ok = True
    except RuntimeError:
        gmx_path = None
        gmx_ok = False

    return {
        "available":      namd_ok and gmx_ok,
        "namd_available": namd_ok,
        "namd_path":      namd_path,
        "gmx_available":  gmx_ok,
        "gmx_path":       gmx_path,
        "recommended_threads": default_threads(),
    }


# ── Molecular Dynamics load ────────────────────────────────────────────────────


@router.get("/md/browse")
def md_browse(dir: str = "", ext: str = "") -> dict:
    """
    List server-side filesystem entries for the MD file picker.

    Parameters
    ----------
    dir : absolute directory path to list (empty → user home directory)
    ext : comma-separated extensions to filter files (e.g. ".gro,.tpr")
          Empty = show all non-hidden files
    """
    from pathlib import Path

    base = Path(dir).resolve() if dir else Path.home()
    exts = {e.strip().lower() for e in ext.split(",") if e.strip()} if ext else set()

    entries: list[dict] = []

    # Parent navigation
    parent = base.parent
    if parent != base:
        entries.append({"name": "..", "path": str(parent), "type": "dir", "size": 0})

    try:
        items = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return {"path": str(base), "entries": entries}

    for p in items:
        if p.name.startswith("."):
            continue
        try:
            if p.is_dir():
                entries.append({"name": p.name, "path": str(p), "type": "dir", "size": 0})
            elif not exts or p.suffix.lower() in exts:
                entries.append({
                    "name": p.name,
                    "path": str(p),
                    "type": "file",
                    "size": p.stat().st_size,
                })
        except (PermissionError, OSError):
            continue

    return {"path": str(base), "entries": entries}
