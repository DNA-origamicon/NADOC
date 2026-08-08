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
import os
import time as _time
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

# A remote (RunPod) job's status in our local index is only a launch RECORD — the local
# app has no lifecycle poller for CLI-launched pod jobs (unlike Alpine's Slurm poll), so a
# killed launcher leaves the job wedged at "running" forever. The authoritative liveness
# signal is RunPod itself: pods are named ``nadoc-<design>-<job_id>``, so a job is genuinely
# running iff its id is a substring of a live pod's name. Cache it briefly so a
# frequently-polled /jobs/active doesn't hammer the API.
_REMOTE_POD_CACHE: dict = {"t": -1e9, "names": None}
_REMOTE_POD_TTL_S = 30.0


def _live_remote_pod_names() -> "set[str] | None":
    """Best-effort names of live RunPod pods. ``None`` when undeterminable (no API key /
    RunPod unreachable) — callers MUST fail-open and leave the job's status untouched then,
    never hide a job we simply couldn't verify."""
    now = _time.monotonic()
    if (
        _REMOTE_POD_CACHE["names"] is not None
        and now - _REMOTE_POD_CACHE["t"] < _REMOTE_POD_TTL_S
    ):
        return _REMOTE_POD_CACHE["names"]
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        kp = Path.home() / ".runpod_key"
        key = kp.read_text().strip() if kp.exists() else None
    if not key:
        return None
    try:
        import asyncio  # noqa: PLC0415
        from backend.core.runpod_api import RunpodClient  # noqa: PLC0415

        async def _names() -> set[str]:
            client = RunpodClient(key)
            try:
                pods = await asyncio.wait_for(client.list_pods(), timeout=10)
            finally:
                await client.aclose()
            # The persisted pod id is authoritative.  Names are only a compatibility
            # fallback for old job records created before the id was saved reliably.
            # Matching names alone falsely orphaned live jobs when RunPod omitted or
            # truncated a display name in a list response.
            identifiers: set[str] = set()
            for p in pods:
                if p.is_destroyed:
                    continue
                identifiers.add(p.id)
                name = str((p.raw or {}).get("name") or "")
                if name:
                    identifiers.add(name)
            return identifiers

        names = asyncio.run(_names())
    except Exception:  # noqa: BLE001 — any failure → undeterminable → fail-open
        return None
    _REMOTE_POD_CACHE.update(t=now, names=names)
    return names


def _md_eta_seconds(job, ws: Path) -> Optional[float]:
    """Best-effort seconds-remaining for a running NAMD job: the steps left in this
    segment plus every later segment, at the log's measured step cost.  ``None`` when the
    run has not timed any steps yet.

    Shares :mod:`backend.core.namd_metrics` with the master progress bar
    (``routes_md._namd_live_progress``) so the two never quote different numbers.  It
    used to derive the rate from ns/day + the conf's ``timestep`` and take the step from
    ``parse_namd_log``, which read the WHOLE growing log and — on a production conf that
    prints ~400 ENERGY frames — reported nothing for the first ~8 minutes and a stale
    step thereafter.
    """
    try:
        if not (0 <= job.current_segment_idx < len(job.segments)):
            return None
        from backend.core.namd_metrics import (
            benchmark_s_per_step,
            eta_seconds,
            live_segment_step,
        )

        pkg = job.package_dir(ws)
        seg = job.segments[job.current_segment_idx]
        remaining = max(0, int(seg.steps) - int(live_segment_step(pkg, seg.name) or 0))
        remaining += sum(
            int(s.steps or 0) for s in job.segments[job.current_segment_idx + 1 :]
        )
        return eta_seconds(remaining, benchmark_s_per_step(pkg / f"{seg.name}.log"))
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
            # reconcile_job_status leaves REMOTE jobs untouched.  Alpine jobs have the Slurm
            # poller (md_executor.poll_remote_jobs); RUNPOD jobs launched from the CLI have NO
            # local lifecycle poller, so a killed launcher wedges them at "running" forever.
            # Verify a runpod job against RunPod itself: it is live only if the in-server
            # supervisor is running it OR a live pod carries its id — else it is orphaned →
            # mark terminal so the detector stops claiming a phantom job.  (Alpine untouched.)
            if getattr(j, "execution_target", "local") == "runpod":
                pod_names = _live_remote_pod_names()
                if pod_names is not None:  # None => can't verify → keep
                    try:
                        from backend.core.runpod_supervisor import (
                            is_running as _rp_running,
                        )

                        supervised = _rp_running(j.job_id)
                    except Exception:  # noqa: BLE001
                        supervised = False
                    recorded_pod_live = bool(
                        getattr(j, "runpod_pod_id", None) in pod_names
                    )
                    legacy_name_live = any(j.job_id in ident for ident in pod_names)
                    if not supervised and not recorded_pod_live and not legacy_name_live:
                        try:
                            from backend.core.md_job import MdStatus

                            # A missing pod is not evidence that NAMD failed.  Ordinary
                            # causes include the dollar kill-switch, a spot reclaim, and
                            # a server restart in the narrow window before the supervisor
                            # persisted PAUSED.  The network-volume checkpoint survives
                            # all three, so preserve the truthful, recoverable state.
                            j.status = MdStatus.paused
                            j.resumable = True
                            j.error = (
                                "Remote pod is gone; progress on the network volume is "
                                "safe. Resume to continue from the checkpoint."
                            )
                            j.runpod_pod_id = None
                            j.runpod_pid = None
                            j.save(ws)
                        except Exception:  # noqa: BLE001
                            pass
                        continue
            out.append(
                {
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
                    "eta_seconds": _md_eta_seconds(j, ws)
                    if j.status.value == "running"
                    else None,
                }
            )
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
            out.append(
                {
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
                    "resource_class": "gpu"
                    if getattr(j, "backend", "CUDA") == "CUDA"
                    else "cpu",
                    "eta_seconds": _oxdna_eta_seconds(j, ws)
                    if j.status.value == "running"
                    else None,
                }
            )
    except Exception:  # noqa: BLE001
        logger.exception("active-jobs: failed to scan oxDNA jobs")

    # ── LAMMPS · mrDNA · CanDo ────────────────────────────────────────────────
    # The three newer engines share the same job model (list_jobs + a status enum
    # + reconcile_*), so one loop covers them.  Resource class: LAMMPS (CPU-parallel
    # oxDNA) and CanDo (in-process FEM) run on the CPU; mrDNA drives ARBD on the GPU.
    # None has a remote backend (all local) and none reports a live ETA yet, so the
    # welcome spinner shows a bare "running…" for these.
    for engine, mod_job, mod_runner, cls_name, recon_name, res in (
        (
            "lammps",
            "lammps_job",
            "lammps_runner",
            "LammpsJob",
            "reconcile_lammps_status",
            "cpu",
        ),
        (
            "mrdna",
            "mrdna_job",
            "mrdna_runner",
            "MrdnaJob",
            "reconcile_mrdna_status",
            "gpu",
        ),
        (
            "cando",
            "cando_job",
            "cando_runner",
            "CandoJob",
            "reconcile_cando_status",
            "cpu",
        ),
        (
            "snupi",
            "snupi_job",
            "snupi_runner",
            "SnupiJob",
            "reconcile_snupi_status",
            "cpu",
        ),
    ):
        try:
            JobCls = getattr(
                importlib.import_module(f"backend.core.{mod_job}"), cls_name
            )
            reconcile = getattr(
                importlib.import_module(f"backend.core.{mod_runner}"), recon_name
            )
            for j in JobCls.list_jobs(ws):
                try:
                    j = reconcile(j, ws)
                except Exception:  # noqa: BLE001
                    pass
                if j.status.value not in _BUSY:
                    continue
                out.append(
                    {
                        "engine": engine,
                        "job_id": j.job_id,
                        "design_name": j.design_name,
                        "design_source_path": j.design_source_path,
                        "status": j.status.value,
                        "created_at": getattr(j, "created_at", None),
                        "execution_target": "local",
                        "resource_class": res,
                        "eta_seconds": None,
                    }
                )
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
