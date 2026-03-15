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
from backend.physics.cg_xpbd import (
    CGSimState,
    build_cg_simulation,
    cg_xpbd_step,
    cg_positions_to_updates,
)

router = APIRouter()

# Approximate target frame interval (seconds).
_FRAME_INTERVAL: float = 1.0 / 10.0  # 10 fps

# XPBD substeps per frame.
_SUBSTEPS_PER_FRAME: int = 20


@router.websocket("/ws/physics")
async def physics_ws(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time physics streaming.

    Supports two modes via the 'mode' field in start_physics messages:
      mode='full' (default) — per-nucleotide XPBD simulation.
      mode='cg'             — coarse-grained helix-axis simulation; loop/skip
                              strain encoded in backbone rest lengths drives
                              convergence from straight toward deformed shape.

    Accepts connections from any origin (CORS is handled at the HTTP layer;
    WebSocket CORS is enforced in production via the allowed-origins setting
    on the server).
    """
    await websocket.accept()

    sim: SimState | CGSimState | None = None
    _mode: str = "full"           # "full" | "cg"
    stream_task: asyncio.Task | None = None

    async def _start_stream(use_straight: bool = False, mode: str = "full") -> None:
        """Build SimState from current design and start streaming.

        Parameters
        ----------
        use_straight : if True and the design has deformations, initialise
                       particle positions from the straight (undeformed) geometry
                       while keeping bond rest lengths from the deformed geometry.
                       This lets the simulation relax from straight toward the
                       designed shape via the strain encoded in loop/skip bonds.
                       Ignored for mode='cg' (CG always starts from straight).
        mode : 'full' for per-nucleotide XPBD, 'cg' for helix-level CG-XPBD.
        """
        nonlocal sim, _mode
        _mode = mode
        design = design_state.get_design()
        if design is None:
            await websocket.send_json({"type": "error", "message": "No design loaded."})
            return

        if mode == "cg":
            # CG model: always starts from straight axis positions; loop/skip
            # strain is encoded in backbone rest lengths, not geometry.
            sim = build_cg_simulation(design)
            await websocket.send_json({
                "type": "status",
                "message": f"CG physics started ({len(sim.particles)} CPs, "
                           f"{len(sim.crossover_ij)} crossovers).",
            })
        else:
            # Full XPBD: deformed geometry for rest lengths, optional straight init.
            geometry = _geometry_for_design(design)
            straight_geometry = None
            if use_straight and design.deformations:
                straight_design = design.model_copy(update={"deformations": []})
                straight_geometry = _geometry_for_design(straight_design)
            sim = build_simulation(design, geometry, straight_geometry=straight_geometry)
            await websocket.send_json({"type": "status", "message": "Physics started."})

    async def _stream_loop() -> None:
        """Continuously run physics and send position updates."""
        while True:
            if sim is None:
                await asyncio.sleep(_FRAME_INTERVAL)
                continue
            # Run the CPU-bound physics step in a thread so the event loop
            # remains responsive regardless of substep count.
            if _mode == "cg":
                await asyncio.to_thread(cg_xpbd_step, sim, sim.substeps_per_frame)
                updates = cg_positions_to_updates(sim)
            else:
                await asyncio.to_thread(xpbd_step, sim, sim.substeps_per_frame)
                updates = positions_to_updates(sim)
            try:
                await websocket.send_json({
                    "type": "positions",
                    "step": sim.step,
                    "data": updates,
                    "mode": _mode,
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
                await _start_stream(
                    use_straight=bool(msg.get("use_straight", False)),
                    mode=str(msg.get("mode", "full")),
                )

            elif action == "stop_physics":
                sim = None
                await websocket.send_json({"type": "status", "message": "Physics stopped."})

            elif action == "reset_physics":
                # Rebuild SimState from current design and continue streaming.
                await _start_stream(
                    use_straight=bool(msg.get("use_straight", False)),
                    mode=str(msg.get("mode", _mode)),
                )

            elif action == "update_params":
                # Live-update simulation parameters from UI sliders.
                if sim is not None:
                    if "noise_amplitude" in msg:
                        sim.noise_amplitude = float(msg["noise_amplitude"])
                    if "substeps_per_frame" in msg:
                        sim.substeps_per_frame = max(1, min(400, int(msg["substeps_per_frame"])))
                    if _mode == "cg":
                        if "crossover_weight" in msg:
                            sim.crossover_weight = max(1.0, float(msg["crossover_weight"]))
                        if "backbone_stiffness" in msg:
                            sim.backbone_stiffness = float(msg["backbone_stiffness"])
                        if "bending_stiffness" in msg:
                            sim.bending_stiffness = float(msg["bending_stiffness"])
                    else:
                        if "bond_stiffness" in msg:
                            sim.bond_stiffness = float(msg["bond_stiffness"])
                        if "bend_stiffness" in msg:
                            sim.bend_stiffness = float(msg["bend_stiffness"])
                        if "bp_stiffness" in msg:
                            sim.bp_stiffness = float(msg["bp_stiffness"])
                        if "stacking_stiffness" in msg:
                            sim.stacking_stiffness = float(msg["stacking_stiffness"])
                        if "elec_amplitude" in msg:
                            sim.elec_amplitude = float(msg["elec_amplitude"])
                        if "debye_length" in msg:
                            sim.debye_length = max(0.1, float(msg["debye_length"]))

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
