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
            (
                j
                for j in _collect_active()
                if j.get("resource_class") == "gpu"
                and j.get("status") == "running"
                # A remote (runpod/alpine) job runs on a pod/cluster and holds NO local GPU —
                # it must never gate a LOCAL run. Only local jobs contend for this machine.
                and j.get("execution_target", "local") == "local"
            ),
            None,
        )
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
        gpu_eta = None  # external processes can't be timed
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
        has_proteins=proteins,
        gpu_busy=gpu_busy,
        gpu_hog_name=hog,
        gpu_eta_seconds=gpu_eta,
        n_nucleotides=n_nt,
        free_cores=free,
    )

    return {
        "recommendation": rec,
        "gpu": gpu,
        "free_cores": free,
        "has_proteins": proteins,
        "n_nucleotides": n_nt,
        "gpu_eta_seconds": gpu_eta,
    }


@router.get("/simulate/jobs")
async def list_simulate_jobs(
    design_source_path: str | None = None, show_all: bool = False
) -> list[dict]:
    """The UNIFIED simulation job list — every oxDNA + LAMMPS run for the active design,
    normalized into one common node shape (see :mod:`backend.core.sim_jobs`) so the
    Simulate panel renders GPU-oxDNA and CPU-LAMMPS runs in the SAME hierarchical list.

    Reuses the exact enrichment ``routes_oxdna.list_oxdna_jobs`` does (reconcile status,
    out-of-date fingerprint, on-disk size) plus the LAMMPS reconcile, then normalizes +
    merges + filters by ``design_source_path`` (parity with the frontend
    ``filterJobsForPart``).  Never raises — a failed engine list degrades to no nodes.
    """
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.core import sim_jobs

    ws = _WORKSPACE_DIR
    import asyncio
    from backend.api import (
        routes_oxdna, routes_lammps, routes_mrdna, routes_cando,
        routes_snupi, routes_blade, routes_md,
    )

    sources = [
        (routes_oxdna.list_oxdna_jobs, sim_jobs.normalize_oxdna_job),
        (routes_lammps.list_lammps_jobs, sim_jobs.normalize_lammps_job),
        (routes_mrdna.list_mrdna_jobs, sim_jobs.normalize_mrdna_job),
        (routes_cando.list_cando_jobs, sim_jobs.normalize_cando_job),
        (routes_snupi.list_snupi_jobs, sim_jobs.normalize_snupi_job),
        (routes_blade.list_blade_jobs, sim_jobs.normalize_blade_job),
        (routes_md.list_md_jobs, sim_jobs.normalize_md_job),
    ]
    # Same in-flight reads as engine panels; no second scan or serial chain.
    results = await asyncio.gather(*(read() for read, _ in sources), return_exceptions=True)
    nodes = []
    for (_, normalize), rows in zip(sources, results):
        if isinstance(rows, Exception):
            continue
        try:
            nodes.extend(normalize(row) for row in rows)
        except Exception:
            continue  # Malformed data from one engine must not hide other engines.
    return await run_in_threadpool(
        _finish_simulate_nodes, nodes, ws, design_source_path, show_all
    )


def _finish_simulate_nodes(nodes, ws, design_source_path, show_all):
    from backend.core import sim_jobs

    # Simulation metadata is synchronized with project history even when its heavy
    # artifact directory remains on another machine.  Surface those remote-only NAMD
    # and oxDNA records in the same list so users can deliberately bring one local.
    try:
        from backend.core.collaboration_peers import PeerRegistry
        from backend.core.project_artifacts import ProjectArtifactCatalog

        design = design_state.get_or_404()
        project_id = design.id
        identity = PeerRegistry(ws).server_identity()
        local_keys = {
            (
                ("md" if node.get("engine") == "namd" else node.get("engine")),
                node.get("job_id"),
            )
            for node in nodes
        }
        by_key = {
            (
                ("md" if node.get("engine") == "namd" else node.get("engine")),
                node.get("job_id"),
            ): node
            for node in nodes
        }
        for record in ProjectArtifactCatalog(ws).project_metadata(project_id):
            engine = record.get("engine")
            if engine not in {"md", "oxdna"}:
                continue
            locations = record.get("locations") or []
            remote = next(
                (
                    location
                    for location in locations
                    if location.get("available")
                    and location.get("server_id") != identity["id"]
                ),
                None,
            )
            if remote is None:
                continue
            key = (engine, record.get("job_id"))
            if key in by_key:
                by_key[key]["artifact_locations"] = locations
                continue
            raw = {
                **record,
                "design_source_path": design_source_path,
                "artifact_locations": locations,
                "remote_only": True,
                "source_peer_id": remote.get("server_id"),
                "source_peer_name": remote.get("server_name"),
                "size_bytes": record.get("size_bytes", 0),
            }
            node = (
                sim_jobs.normalize_md_job(raw)
                if engine == "md"
                else sim_jobs.normalize_oxdna_job(raw)
            )
            node["viewable"] = False
            nodes.append(node)
            local_keys.add(key)
    except Exception:  # noqa: BLE001 — collaboration metadata is advisory
        pass
    if not show_all and not design_source_path:
        # Assembly projections intentionally have no part-file path. Their stable
        # identity is the flattened Design/project id; filtering on a missing path
        # made a newly launched job disappear as soon as its optimistic row was
        # replaced by the persisted backend record.
        try:
            project_id = design_state.get_or_404().id
            if str(project_id).startswith("flat_"):
                return [n for n in nodes if n.get("project_id") == project_id]
        except Exception:  # noqa: BLE001 — list filtering must remain advisory
            pass
    return sim_jobs.filter_nodes(nodes, design_source_path, show_all)
