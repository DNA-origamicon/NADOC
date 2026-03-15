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
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api import state as design_state
from backend.api.crud import router as crud_router
from backend.api.routes import router, _demo_design
from backend.api.ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the active design with the demo seed on server startup."""
    design_state.set_design(_demo_design())
    yield


app = FastAPI(
    title="NADOC API",
    description="Not Another DNA Origami CAD — backend API",
    version="0.2.0",
    lifespan=lifespan,
)

# Allow Vite dev server (port 5173) to call the API in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router,      prefix="/api")
app.include_router(crud_router, prefix="/api")
app.include_router(ws_router)   # WebSocket routes have no /api prefix


@app.get("/", include_in_schema=False)
def root():
    """In dev mode redirect to the Vite dev server; in production this is
    shadowed by the StaticFiles mount below."""
    return RedirectResponse("http://localhost:5173")


# Serve the built Vite frontend if present (production mode).
_frontend_dist = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist"
)
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
