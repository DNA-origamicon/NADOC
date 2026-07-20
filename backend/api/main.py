"""
API layer — FastAPI application entry point.

Serves the REST API for design CRUD and geometry queries.
In development, the Vite frontend runs on a separate port and proxies /api
to this server.  In production, this server also serves the built frontend
from frontend/dist via StaticFiles.
"""

from __future__ import annotations

import asyncio
import logging
import os
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api import library_events, session_cache
from backend.api.assembly import _WORKSPACE_DIR
from backend.api.assembly import router as assembly_router
from backend.api.crud import router as crud_router
from backend.api.doc_context import DocContextMiddleware
from backend.api.documents import router as documents_router
from backend.api.routes import router
from backend.api.routes_animations import router as animations_router
from backend.api.routes_assembly_animations import router as assembly_animations_router
from backend.api.routes_chain_sim import router as chain_sim_router
from backend.api.routes_assembly_belts import router as assembly_belts_router
from backend.api.routes_assembly_configs import router as assembly_configs_router
from backend.api.routes_assembly_connectors import router as assembly_connectors_router
from backend.api.routes_assembly_frames import router as assembly_frames_router
from backend.api.routes_assembly_gears import router as assembly_gears_router
from backend.api.routes_assembly_geometry import router as assembly_geometry_router
from backend.api.routes_assembly_groups import router as assembly_groups_router
from backend.api.routes_assembly_joints import router as assembly_joints_router
from backend.api.routes_assembly_linkers import router as assembly_linkers_router
from backend.api.routes_assembly_loadouts import router as assembly_loadouts_router
from backend.api.routes_assembly_overhangs import router as assembly_overhangs_router
from backend.api.routes_assembly_polymerize import router as assembly_polymerize_router
from backend.api.routes_assembly_validation import router as assembly_validation_router
from backend.api.routes_assembly_workspace import router as assembly_workspace_router
from backend.api.routes_camera_poses import router as camera_poses_router
from backend.api.routes_cluster import router as cluster_router
from backend.api.routes_runpod import router as runpod_router
from backend.api.routes_cluster_joints import router as cluster_joints_router
from backend.api.routes_clusters import router as clusters_router
from backend.api.routes_deformation import router as deformation_router
from backend.api.routes_display_geometry import router as display_geometry_router
from backend.api.routes_display_metadata import router as display_metadata_router
from backend.api.routes_export_3dprint import router as export_3dprint_router
from backend.api.routes_export_md import router as export_md_router
from backend.api.routes_export_structure import router as export_structure_router
from backend.api.routes_extensions import router as extensions_router
from backend.api.routes_feature_log import router as feature_log_router
from backend.api.routes_sequences import router as sequences_router
from backend.api.routes_benchmark import router as benchmark_router
from backend.api.routes_engines import router as engines_router
from backend.api.routes_flexible_segments import router as flexible_segments_router
from backend.api.routes_duplex import router as duplex_router
from backend.api.routes_fs import router as fs_router
from backend.api.routes_loop_skip import router as loop_skip_router
from backend.api.routes_jobs import router as jobs_router
from backend.api.routes_md import router as md_router
from backend.api.routes_cando import router as cando_router
from backend.api.routes_cando_autorefine import router as cando_autorefine_router
from backend.api.routes_snupi import router as snupi_router
from backend.api.routes_blade import router as blade_router
from backend.api.routes_mrdna import router as mrdna_router
from backend.api.routes_md_metrics import router as md_metrics_router
from backend.api.routes_oxdna import router as oxdna_router
from backend.api.routes_lammps import router as lammps_router
from backend.api.routes_oxdna_live import router as oxdna_live_router
from backend.api.routes_autorefine import router as autorefine_router
from backend.api.routes_oxdna_metrics import router as oxdna_metrics_router
from backend.api.routes_shape_metrics import router as shape_metrics_router
from backend.api.routes_system import router as system_router
from backend.api.routes_simulate import router as simulate_router
from backend.api.routes_primitives import router as primitives_router
from backend.api.routes_protein import router as protein_router
from backend.api.routes_assign_sequences import router as assign_sequences_router
from backend.api.routes_scaffold_routing import router as scaffold_routing_router
from backend.api.ws import router as ws_router
from backend.core.namd_runner import resume_interrupted_jobs

logger = logging.getLogger(__name__)

# How often the MD supervisor scans for interrupted NAMD jobs to (re)launch.
# NAMD segments run for minutes-to-hours, so a coarse cadence is plenty and keeps
# /proc + reconciliation overhead negligible.
_MD_SUPERVISOR_INTERVAL_S = 30.0


async def _md_supervisor_loop() -> None:
    """Periodically relaunch MD jobs interrupted by a server/runner death.

    Runs the (blocking) supervisor pass in a worker thread so health-check I/O
    never stalls the event loop.  Resilient to per-pass errors.
    """
    while True:
        try:
            resumed = await asyncio.to_thread(resume_interrupted_jobs, _WORKSPACE_DIR)
            if resumed:
                logger.info("MD supervisor resumed jobs: %s", ", ".join(resumed))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MD supervisor pass failed")
        # Remote (Alpine/SLURM) jobs: poll squeue/sacct + fetch on completion.  Runs
        # on this (main) loop because the asyncssh session is bound to it; a no-op
        # when disconnected.
        try:
            from backend.core.md_executor import poll_remote_jobs
            touched = await poll_remote_jobs(_WORKSPACE_DIR)
            if touched:
                logger.info("MD supervisor polled remote jobs: %s", ", ".join(touched))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MD remote poll pass failed")
        # Chain executor (P2): advance any queued multi-stage MdPipeline chain — spawn
        # stage N when stage N-1 completes; a halted chain waits for a manual resume.
        try:
            from backend.api.routes_md import advance_chains
            advanced = await advance_chains(_WORKSPACE_DIR)
            if advanced:
                logger.info("MD supervisor advanced chains: %s", ", ".join(advanced))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MD chain advance pass failed")
        await asyncio.sleep(_MD_SUPERVISOR_INTERVAL_S)


async def _terminate_runpod_pods() -> None:
    """Destroy every pod this process still owns.  Best-effort; never blocks shutdown."""
    try:
        from backend.api import routes_runpod
        from backend.core import runpod_supervisor

        session = routes_runpod._SESSION  # noqa: SLF001
        if not session.is_connected():
            return
        for job_id in runpod_supervisor.running_job_ids():
            with contextlib.suppress(Exception):
                await runpod_supervisor.stop_job(job_id, client=session.client)
    except Exception:  # noqa: BLE001 — shutdown must not raise
        logger.warning("runpod: pod cleanup on shutdown failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server startup/shutdown hook."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    library_events.start(_WORKSPACE_DIR)
    # Restore any cached in-progress document, then start the autosave thread.
    session_cache.start(_WORKSPACE_DIR)
    # Resume any NAMD jobs interrupted by a previous shutdown, then keep watching.
    md_supervisor = asyncio.create_task(_md_supervisor_loop())
    yield
    # A RunPod pod bills from creation to termination.  On a CLEAN shutdown we still
    # hold the API key in memory, so this is the last moment we can kill anything we
    # started.  (On an UNCLEAN death the key dies with us and we cannot — which is why
    # POST /runpod/connect reaps orphans the instant you reconnect.)
    await _terminate_runpod_pods()
    md_supervisor.cancel()
    try:
        await md_supervisor
    except asyncio.CancelledError:
        pass
    session_cache.stop()
    library_events.stop()


app = FastAPI(
    title="NADOC API",
    description="Not Another DNA Origami CAD — backend API",
    version="0.2.0",
    lifespan=lifespan,
    # orjson is ~3-5× faster than the stdlib json encoder on geometry-heavy
    # responses (50K+ nucleotide dicts → multi-MB JSON). All endpoints that
    # return a dict get this default — endpoints that explicitly construct
    # JSONResponse / ORJSONResponse pick their own encoder.
    default_response_class=ORJSONResponse,
)

# Bind each request's document (X-NADOC-Doc header / ?doc=) to a ContextVar so
# state.py / assembly_state.py resolve the right per-document session.  Pure-ASGI
# middleware (not BaseHTTPMiddleware) so the value propagates to the endpoint.
app.add_middleware(DocContextMiddleware)

# Structural exports and geometry payloads are highly compressible text. A
# Voltron-scale PDB is ~34 MB uncompressed but ~8.5 MB at gzip level 3; browsers
# transparently decode Content-Encoding while preserving the downloaded .pdb.
# Level 3 captures almost all of the transfer reduction without adding meaningful
# delay to an already CPU-heavy export (~0.45 s in the Voltron benchmark).
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=3)

# Allow Vite dev server (port 5173) to call the API in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router,             prefix="/api")
app.include_router(documents_router,   prefix="/api")
app.include_router(crud_router,        prefix="/api")
app.include_router(loop_skip_router,   prefix="/api")
app.include_router(camera_poses_router, prefix="/api")
app.include_router(clusters_router,    prefix="/api")
app.include_router(cluster_router,     prefix="/api")
app.include_router(runpod_router,      prefix="/api")
app.include_router(cluster_joints_router, prefix="/api")
app.include_router(animations_router,  prefix="/api")
app.include_router(chain_sim_router,    prefix="/api")
app.include_router(simulate_router,     prefix="/api")
app.include_router(extensions_router,  prefix="/api")
app.include_router(feature_log_router, prefix="/api")
app.include_router(deformation_router, prefix="/api")
app.include_router(display_geometry_router, prefix="/api")
app.include_router(display_metadata_router, prefix="/api")
app.include_router(flexible_segments_router, prefix="/api")
app.include_router(duplex_router,      prefix="/api")
app.include_router(export_3dprint_router, prefix="/api")
app.include_router(export_md_router,   prefix="/api")
app.include_router(export_structure_router, prefix="/api")
app.include_router(sequences_router,   prefix="/api")
app.include_router(scaffold_routing_router, prefix="/api")
app.include_router(assign_sequences_router, prefix="/api")
app.include_router(assembly_router,    prefix="/api")
app.include_router(assembly_animations_router, prefix="/api")
app.include_router(assembly_belts_router, prefix="/api")
app.include_router(assembly_configs_router, prefix="/api")
app.include_router(assembly_connectors_router, prefix="/api")
app.include_router(assembly_frames_router, prefix="/api")
app.include_router(assembly_gears_router, prefix="/api")
app.include_router(assembly_geometry_router, prefix="/api")
app.include_router(assembly_groups_router, prefix="/api")
app.include_router(assembly_joints_router, prefix="/api")
app.include_router(assembly_linkers_router, prefix="/api")
app.include_router(assembly_loadouts_router, prefix="/api")
app.include_router(assembly_overhangs_router, prefix="/api")
app.include_router(assembly_polymerize_router, prefix="/api")
app.include_router(assembly_validation_router, prefix="/api")
app.include_router(assembly_workspace_router, prefix="/api")
app.include_router(jobs_router,        prefix="/api")
app.include_router(md_router,          prefix="/api")
app.include_router(md_metrics_router,  prefix="/api")
app.include_router(oxdna_router,       prefix="/api")
app.include_router(lammps_router,      prefix="/api")
app.include_router(mrdna_router,       prefix="/api")
app.include_router(cando_router,       prefix="/api")
app.include_router(cando_autorefine_router, prefix="/api")
app.include_router(snupi_router,       prefix="/api")
app.include_router(blade_router,       prefix="/api")
app.include_router(oxdna_live_router,  prefix="/api")
app.include_router(autorefine_router,  prefix="/api")
app.include_router(oxdna_metrics_router, prefix="/api")
app.include_router(shape_metrics_router, prefix="/api")
app.include_router(system_router,      prefix="/api")
app.include_router(benchmark_router,   prefix="/api")
app.include_router(engines_router,     prefix="/api")
app.include_router(primitives_router,  prefix="/api")
app.include_router(fs_router,          prefix="/api")
app.include_router(protein_router,     prefix="/api")
app.include_router(ws_router)          # WebSocket routes have no /api prefix


@app.get("/", include_in_schema=False)
def root():
    """In dev mode redirect to the Vite dev server; in production this is
    shadowed by the StaticFiles mount below."""
    return RedirectResponse("http://localhost:5173")


@app.get("/cadnano", include_in_schema=False)
def cadnano_editor():
    """Serve the cadnano 2D editor.

    In production, serves the built cadnano-editor.html from the Vite dist.
    In dev mode, redirects to the Vite dev server URL.
    """
    editor_html = os.path.join(_frontend_dist, "cadnano-editor.html")
    if os.path.isfile(editor_html):
        return FileResponse(editor_html)
    # Dev mode — Vite serves multi-page entries by filename
    return RedirectResponse("http://localhost:5173/cadnano-editor.html")


# Serve the built Vite frontend if present (production mode).
_frontend_dist = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist"
)
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
