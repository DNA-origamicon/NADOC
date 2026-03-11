"""
API layer — WebSocket handler (stub, Phase 4).

In Phase 4 this module will stream XPBD-relaxed nucleotide positions to the
frontend at ~30 fps.  The physics layer never writes to Design.

Protocol (to be implemented):
  client → server: {"action": "start_physics", "design_id": "..."}
  server → client: {"type": "positions", "data": [[x,y,z], ...]}  (streaming)
  client → server: {"action": "stop_physics"}
  client → server: {"action": "reset_physics"}  (on design edit)
"""
