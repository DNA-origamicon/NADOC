"""
API layer — FastAPI application entry point.

Serves the REST API for design CRUD and geometry queries.
In development, the Vite frontend runs on a separate port and proxies /api
to this server.  In production, this server also serves the built frontend
from frontend/dist via StaticFiles.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from backend.api.routes_cluster_joints import router as cluster_joints_router
from backend.api.routes_clusters import router as clusters_router
from backend.api.routes_deformation import router as deformation_router
from backend.api.routes_export_md import router as export_md_router
from backend.api.routes_export_structure import router as export_structure_router
from backend.api.routes_extensions import router as extensions_router
from backend.api.routes_sequences import router as sequences_router
from backend.api.routes_flexible_segments import router as flexible_segments_router
from backend.api.routes_loop_skip import router as loop_skip_router
from backend.api.routes_md import router as md_router
from backend.api.routes_oxdna import router as oxdna_router
from backend.api.routes_primitives import router as primitives_router
from backend.api.routes_scaffold_routing import router as scaffold_routing_router
from backend.api.ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server startup/shutdown hook."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    library_events.start(_WORKSPACE_DIR)
    # Restore any cached in-progress document, then start the autosave thread.
    session_cache.start(_WORKSPACE_DIR)
    yield
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
app.include_router(cluster_joints_router, prefix="/api")
app.include_router(animations_router,  prefix="/api")
app.include_router(extensions_router,  prefix="/api")
app.include_router(deformation_router, prefix="/api")
app.include_router(flexible_segments_router, prefix="/api")
app.include_router(export_md_router,   prefix="/api")
app.include_router(export_structure_router, prefix="/api")
app.include_router(sequences_router,   prefix="/api")
app.include_router(scaffold_routing_router, prefix="/api")
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
app.include_router(md_router,          prefix="/api")
app.include_router(oxdna_router,       prefix="/api")
app.include_router(primitives_router,  prefix="/api")
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
