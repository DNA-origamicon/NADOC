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

from backend.api import library_events
from backend.api import state as design_state
from backend.api.assembly import _WORKSPACE_DIR
from backend.api.assembly import router as assembly_router
from backend.api.crud import router as crud_router
from backend.api.routes import router
from backend.api.ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server startup/shutdown hook."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    library_events.start(_WORKSPACE_DIR)
    yield
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

# Allow Vite dev server (port 5173) to call the API in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router,          prefix="/api")
app.include_router(crud_router,     prefix="/api")
app.include_router(assembly_router, prefix="/api")
app.include_router(ws_router)       # WebSocket routes have no /api prefix


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
