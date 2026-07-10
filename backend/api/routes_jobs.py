"""Cross-engine job summary routes (MD + oxDNA) for the welcome screen.

The welcome / library panel lists design files but is not tied to either the MD
(NAMD) or oxDNA job panels (those live in the editor).  To show a per-file
"this design is simulating" spinner + ETA, and to warn before launching a
second job, it needs ONE cheap query spanning both engines.

Route summary
─────────────
GET /api/jobs/active   every currently-busy (running/preparing) MD or oxDNA job,
                       with its design source path + a best-effort ETA in seconds.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from backend.api.assembly import _WORKSPACE_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

# "Busy" = actively consuming the machine (the spinner / concurrency-guard states).
# Queued jobs are waiting their turn and are intentionally NOT counted as running.
_BUSY = {"running", "preparing"}


def _conf_timestep_fs(conf_path: Path) -> Optional[float]:
    """Femtoseconds per step from a NAMD .conf ``timestep`` line (default unknown)."""
    try:
        for line in conf_path.read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() == "timestep":
                return float(parts[1])
    except (OSError, ValueError):
        pass
    return None


def _md_eta_seconds(job, ws: Path) -> Optional[float]:
    """Best-effort seconds-remaining for a running NAMD job: the current segment's
    live ns/day (from its log) converted to a step rate via the conf's fs/step, then
    applied to the steps left in this segment plus every later segment.  None when any
    ingredient is missing (e.g. the log has not printed an energy line yet)."""
    try:
        if not (0 <= job.current_segment_idx < len(job.segments)):
            return None
        from backend.core.namd_metrics import parse_namd_log

        pkg = job.package_dir(ws)
        seg = job.segments[job.current_segment_idx]
        log = pkg / f"{seg.name}.log"
        if not log.exists():
            return None
        m = parse_namd_log(log)
        fs = _conf_timestep_fs(pkg / f"{seg.name}.conf")
        if not m.ns_per_day or m.timestep is None or not fs:
            return None
        steps_per_s = m.ns_per_day * 1e6 / fs / 86_400.0
        if steps_per_s <= 0:
            return None
        remaining = max(0, seg.steps - int(m.timestep))
        remaining += sum(s.steps for s in job.segments[job.current_segment_idx + 1:])
        return remaining / steps_per_s
    except Exception:  # noqa: BLE001 — ETA is advisory; never fail the listing
        return None


def _oxdna_eta_seconds(job, ws: Path) -> Optional[float]:
    try:
        from backend.core.oxdna_runner import job_progress, load_stage_specs

        specs = load_stage_specs(job.job_dir(ws))
        return job_progress(job, ws, specs).get("eta_seconds")
    except Exception:  # noqa: BLE001
        return None


def _collect_active() -> list[dict]:
    ws = _WORKSPACE_DIR
    out: list[dict] = []

    # ── MD (NAMD) ────────────────────────────────────────────────────────────
    try:
        from backend.core.md_job import MdJob
        from backend.core.namd_runner import reconcile_job_status

        for j in MdJob.list_jobs(ws):
            try:
                j = reconcile_job_status(j, ws)
            except Exception:  # noqa: BLE001
                pass
            if j.status.value not in _BUSY:
                continue
            out.append({
                "engine": "md",
                "job_id": j.job_id,
                "design_name": j.design_name,
                "design_source_path": j.design_source_path,
                "status": j.status.value,
                # Epoch seconds — lets the frontend break ties by most-recent job
                # (e.g. defaulting the Simulate engine dropdown to the newest run).
                "created_at": getattr(j, "created_at", None),
                # "local" runs on this machine's GPU/CPU; "alpine" runs on the remote
                # cluster and consumes no local resources — the concurrent-launch guard
                # ignores remote jobs (they can't contend for the local GPU/disk).
                "execution_target": getattr(j, "execution_target", "local"),
                # NAMD always runs GPU-resident here, so a local MD job holds the GPU.
                # The frontend guard only makes two GPU jobs block each other; a CPU-only
                # run (a CPU-backend oxDNA job) may launch alongside it.
                "resource_class": "gpu",
                "eta_seconds": _md_eta_seconds(j, ws) if j.status.value == "running" else None,
            })
    except Exception:  # noqa: BLE001
        logger.exception("active-jobs: failed to scan MD jobs")

    # ── oxDNA ────────────────────────────────────────────────────────────────
    try:
        from backend.core.oxdna_job import OxdnaJob
        from backend.core.oxdna_runner import reconcile_oxdna_status

        for j in OxdnaJob.list_jobs(ws):
            try:
                j = reconcile_oxdna_status(j, ws)
            except Exception:  # noqa: BLE001
                pass
            if j.status.value not in _BUSY:
                continue
            out.append({
                "engine": "oxdna",
                "job_id": j.job_id,
                "design_name": j.design_name,
                "design_source_path": j.design_source_path,
                "status": j.status.value,
                "created_at": getattr(j, "created_at", None),
                # oxDNA has no remote backend — every oxDNA job runs locally.
                "execution_target": "local",
                # A CUDA-backend oxDNA run holds the GPU; a CPU-backend run (e.g. an
                # E-field study) uses only spare cores and can share the machine with a
                # GPU job. The guard keys off this to decide what actually contends.
                "resource_class": "gpu" if getattr(j, "backend", "CUDA") == "CUDA" else "cpu",
                "eta_seconds": _oxdna_eta_seconds(j, ws) if j.status.value == "running" else None,
            })
    except Exception:  # noqa: BLE001
        logger.exception("active-jobs: failed to scan oxDNA jobs")

    # ── LAMMPS · mrDNA · CanDo ────────────────────────────────────────────────
    # The three newer engines share the same job model (list_jobs + a status enum
    # + reconcile_*), so one loop covers them.  Resource class: LAMMPS (CPU-parallel
    # oxDNA) and CanDo (in-process FEM) run on the CPU; mrDNA drives ARBD on the GPU.
    # None has a remote backend (all local) and none reports a live ETA yet, so the
    # welcome spinner shows a bare "running…" for these.
    for engine, mod_job, mod_runner, cls_name, recon_name, res in (
        ("lammps", "lammps_job", "lammps_runner", "LammpsJob", "reconcile_lammps_status", "cpu"),
        ("mrdna",  "mrdna_job",  "mrdna_runner",  "MrdnaJob",  "reconcile_mrdna_status",  "gpu"),
        ("cando",  "cando_job",  "cando_runner",  "CandoJob",  "reconcile_cando_status",  "cpu"),
    ):
        try:
            JobCls = getattr(importlib.import_module(f"backend.core.{mod_job}"), cls_name)
            reconcile = getattr(importlib.import_module(f"backend.core.{mod_runner}"), recon_name)
            for j in JobCls.list_jobs(ws):
                try:
                    j = reconcile(j, ws)
                except Exception:  # noqa: BLE001
                    pass
                if j.status.value not in _BUSY:
                    continue
                out.append({
                    "engine": engine,
                    "job_id": j.job_id,
                    "design_name": j.design_name,
                    "design_source_path": j.design_source_path,
                    "status": j.status.value,
                    "created_at": getattr(j, "created_at", None),
                    "execution_target": "local",
                    "resource_class": res,
                    "eta_seconds": None,
                })
        except Exception:  # noqa: BLE001
            logger.exception("active-jobs: failed to scan %s jobs", engine)

    return out


@router.get("/jobs/active")
async def list_active_jobs() -> dict:
    """Every currently busy (running/preparing) MD or oxDNA job across the workspace.

    Used by the welcome screen to draw a per-design activity spinner + ETA tooltip
    and to warn before launching a concurrent run.  Cheap enough to poll a few
    times a minute: it reconciles each job's status and reads at most one log per
    running job for the ETA.
    """
    jobs = await run_in_threadpool(_collect_active)
    return {
        "jobs": jobs,
        "count": len(jobs),
        "any_running": any(j["status"] == "running" for j in jobs),
    }
