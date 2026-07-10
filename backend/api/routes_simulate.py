"""Simulate-tab auto engine recommendation — ``GET /simulate/recommendation``.

Gathers the machine's live resources (GPU occupancy, free CPU cores) plus the active
design's facts (proteins? size) and returns the engine a novice should run, via the
pure :mod:`backend.core.engine_policy`.  Drives the resource status line and the
GPU-busy launch dialog.  Never raises — returns a neutral payload when no design is
loaded or ``nvidia-smi`` is absent.

Note the "busy" semantics differ from ``/md/gpu-status``: there, the app's OWN jobs
are excluded (the concurrent-job guard covers them).  Here, a running NADOC NAMD or
oxDNA-CUDA job *does* count as GPU-busy — because a new GPU run would contend with it,
which is exactly the "a NAMD run is going, use CPU instead" case this endpoint serves.
When the holder is one of our jobs we can also report its ETA (external hogs can't be
timed).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from backend.api import state as design_state
from backend.core.engine_policy import recommend_engine

router = APIRouter(tags=["simulate"])

# Friendly names for whatever NADOC job is holding the GPU.
_ENGINE_LABEL = {"md": "a NAMD run", "oxdna": "an oxDNA run", "mrdna": "an mrDNA run"}


@router.get("/simulate/recommendation")
async def get_recommendation(devices: str = "0") -> dict:
    """Recommend an engine for the active design given live GPU/CPU state.

    → ``{recommendation, gpu, free_cores, has_proteins, n_nucleotides, gpu_eta_seconds}``.
    ``recommendation`` is the :func:`engine_policy.recommend_engine` payload.
    """
    from backend.core.lammps_runner import free_cpu_cores  # noqa: PLC0415
    from backend.core.md_vram import detect_gpu_activity, gpu_contention_summary  # noqa: PLC0415
    from backend.core.namd_runner import active_namd_pids  # noqa: PLC0415
    from backend.core.oxdna_runner import _ACTIVE_PIDS as _OX_PIDS  # noqa: PLC0415
    from backend.physics.oxdna_interface import _strand_nucleotide_order  # noqa: PLC0415
    from backend.physics.oxdna_protein import has_proteins  # noqa: PLC0415

    # ── Design facts (degrade gracefully when nothing is loaded) ──────────────
    proteins, n_nt = False, 0
    try:
        design = design_state.get_or_404()
        proteins = has_proteins(design)
        n_nt = len(_strand_nucleotide_order(design))
    except Exception:  # noqa: BLE001 — no active design → neutral facts
        pass

    # ── Is a NADOC GPU job running? (its ETA is knowable) ─────────────────────
    own_gpu_job = None
    try:
        from backend.api.routes_jobs import _collect_active  # noqa: PLC0415

        own_gpu_job = next(
            (j for j in _collect_active()
             if j.get("resource_class") == "gpu" and j.get("status") == "running"),
            None)
    except Exception:  # noqa: BLE001
        pass

    # ── External GPU contention (someone else's process) ──────────────────────
    own_pids = set(active_namd_pids()) | set(_OX_PIDS.values())
    activity = await run_in_threadpool(detect_gpu_activity, devices)
    external = gpu_contention_summary(activity, own_pids=own_pids)
    free = free_cpu_cores()

    # Combined busy = our own GPU job OR an external hog.
    if own_gpu_job is not None:
        hog = _ENGINE_LABEL.get(own_gpu_job.get("engine"), "another job")
        holder_kind = "nadoc"
        gpu_eta = own_gpu_job.get("eta_seconds")
    elif external.get("busy"):
        procs = external.get("processes") or [{}]
        hog = procs[0].get("name") or "another process"
        holder_kind = "external"
        gpu_eta = None                        # external processes can't be timed
    else:
        hog, holder_kind, gpu_eta = None, None, None
    gpu_busy = own_gpu_job is not None or bool(external.get("busy"))

    gpu = {
        "available": external.get("available", False),
        "busy": gpu_busy,
        "holder_name": hog,
        "holder_kind": holder_kind,
        "free_mb": external.get("free_mb"),
        "total_mb": external.get("total_mb"),
        "util_pct": external.get("util_pct"),
    }

    rec = recommend_engine(
        has_proteins=proteins, gpu_busy=gpu_busy, gpu_hog_name=hog,
        gpu_eta_seconds=gpu_eta, n_nucleotides=n_nt, free_cores=free)

    return {"recommendation": rec, "gpu": gpu, "free_cores": free,
            "has_proteins": proteins, "n_nucleotides": n_nt, "gpu_eta_seconds": gpu_eta}


@router.get("/simulate/jobs")
async def list_simulate_jobs(design_source_path: str | None = None,
                             show_all: bool = False) -> list[dict]:
    """The UNIFIED simulation job list — every oxDNA + LAMMPS run for the active design,
    normalized into one common node shape (see :mod:`backend.core.sim_jobs`) so the
    Simulate panel renders GPU-oxDNA and CPU-LAMMPS runs in the SAME hierarchical list.

    Reuses the exact enrichment ``routes_oxdna.list_oxdna_jobs`` does (reconcile status,
    out-of-date fingerprint, on-disk size) plus the LAMMPS reconcile, then normalizes +
    merges + filters by ``design_source_path`` (parity with the frontend
    ``filterJobsForPart``).  Never raises — a failed engine list degrades to no nodes.
    """
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.api.routes_oxdna import _current_design_fingerprint, _job_is_out_of_date
    from backend.core import sim_jobs
    from backend.core.design_disk_usage import dir_size_bytes_cached
    from backend.core.lammps_job import LammpsJob
    from backend.core.lammps_runner import reconcile_lammps_status
    from backend.core.oxdna_job import OxdnaJob
    from backend.core.oxdna_runner import reconcile_oxdna_status

    ws = _WORKSPACE_DIR  # noqa: F821 — imported lazily just above
    nodes: list[dict] = []
    try:
        current_fp = _current_design_fingerprint()   # computed once for the whole list
        for j in OxdnaJob.list_jobs(ws):
            j = reconcile_oxdna_status(j, ws)
            d = j.to_dict()
            d["out_of_date"] = _job_is_out_of_date(j, current_fp)
            d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
            nodes.append(sim_jobs.normalize_oxdna_job(d))
    except Exception:  # noqa: BLE001 — a broken oxDNA list must not sink the LAMMPS one
        pass
    try:
        for j in LammpsJob.list_jobs(ws):
            j = reconcile_lammps_status(j, ws)
            d = j.to_dict()
            d["size_bytes"] = dir_size_bytes_cached(j.job_dir(ws))
            nodes.append(sim_jobs.normalize_lammps_job(d))
    except Exception:  # noqa: BLE001
        pass
    return sim_jobs.filter_nodes(nodes, design_source_path, show_all)
