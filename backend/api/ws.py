"""
API layer — WebSocket handler for XPBD physics streaming.

Protocol
────────
  Client → Server  {"action": "start_physics"}
    Builds a SimState from the current active design + geometry and starts
    streaming relaxed backbone positions at ~10 fps.

  Server → Client  {"type": "positions", "step": <int>, "data": [{...}, ...]}
    Backbone position update for each nucleotide.  Format matches the
    backbone_position field in GET /api/design/geometry responses so the
    frontend can apply overrides directly.

  Client → Server  {"action": "stop_physics"}
    Stops streaming.  Physics state is discarded.

  Client → Server  {"action": "reset_physics"}
    Rebuilds SimState from current design (picks up any topology changes)
    and restarts streaming.

Architecture notes
──────────────────
  - Physics state never writes back to Design.
  - Each WebSocket connection gets its own independent SimState.
  - XPBD runs in the asyncio event loop (fast enough for small designs);
    large designs (>EV_MAX_PARTICLES) should move to asyncio.to_thread.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api import state as design_state
from backend.api.crud import _geometry_for_design
from backend.physics.xpbd import (
    SimState,
    build_simulation,
    positions_to_updates,
    xpbd_step,
)

router = APIRouter()

# Approximate target frame interval (seconds).
_FRAME_INTERVAL: float = 1.0 / 10.0  # 10 fps

# XPBD substeps per frame.
_SUBSTEPS_PER_FRAME: int = 20


@router.websocket("/ws/physics")
async def physics_ws(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time XPBD physics streaming.

    Accepts connections from any origin (CORS is handled at the HTTP layer;
    WebSocket CORS is enforced in production via the allowed-origins setting
    on the server).
    """
    await websocket.accept()

    sim: SimState | None = None
    stream_task: asyncio.Task | None = None

    async def _start_stream() -> None:
        """Build SimState from current design and start streaming."""
        nonlocal sim
        design = design_state.get_design()
        if design is None:
            await websocket.send_json({"type": "error", "message": "No design loaded."})
            return

        # Build geometry from current design (same as GET /api/design/geometry).
        geometry = _geometry_for_design(design)
        sim = build_simulation(design, geometry)
        await websocket.send_json({"type": "status", "message": "Physics started."})

    async def _stream_loop() -> None:
        """Continuously run XPBD and send position updates."""
        while True:
            if sim is None:
                await asyncio.sleep(_FRAME_INTERVAL)
                continue
            xpbd_step(sim, n_substeps=_SUBSTEPS_PER_FRAME)
            updates = positions_to_updates(sim)
            try:
                await websocket.send_json({
                    "type": "positions",
                    "step": sim.step,
                    "data": updates,
                })
            except Exception:
                break
            await asyncio.sleep(_FRAME_INTERVAL)

    try:
        # Start the background streaming task immediately.
        stream_task = asyncio.create_task(_stream_loop())

        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")

            if action == "start_physics":
                await _start_stream()

            elif action == "stop_physics":
                sim = None
                await websocket.send_json({"type": "status", "message": "Physics stopped."})

            elif action == "reset_physics":
                # Rebuild SimState from current design and continue streaming.
                await _start_stream()

            elif action == "update_params":
                # Live-update simulation parameters from UI sliders.
                if sim is not None:
                    if "noise_amplitude" in msg:
                        sim.noise_amplitude = float(msg["noise_amplitude"])
                    if "bond_stiffness" in msg:
                        sim.bond_stiffness = float(msg["bond_stiffness"])
                    if "bend_stiffness" in msg:
                        sim.bend_stiffness = float(msg["bend_stiffness"])
                    if "bp_stiffness" in msg:
                        sim.bp_stiffness = float(msg["bp_stiffness"])
                    if "stacking_stiffness" in msg:
                        sim.stacking_stiffness = float(msg["stacking_stiffness"])

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if stream_task is not None:
            stream_task.cancel()
            try:
                await stream_task
            except (asyncio.CancelledError, Exception):
                pass
