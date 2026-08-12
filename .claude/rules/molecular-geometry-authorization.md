---
name: molecular-geometry-authorization
description: Hard stop for molecular placement changes; requires an isolated A/B audit artifact and explicit user authorization before production promotion or golden regeneration
paths:
  - "backend/core/atomistic.py"
  - "backend/core/atomistic_helpers.py"
  - "backend/core/atomistic_minimisers.py"
  - "backend/core/geometry.py"
  - "backend/core/design_geometry.py"
  - "backend/core/measured_atomistic.py"
  - "backend/core/junction_topology.py"
  - "backend/core/ring_piercing.py"
  - "frontend/src/scene/crossover_extra_placement.js"
  - "frontend/src/scene/crossover_connections.js"
  - "tests/test_atomistic*.py"
  - "tests/test_junction*.py"
  - "tests/test_ring_piercing.py"
---
# Molecular geometry authorization

Changing code in these paths can move atoms or alter the verdict that permits a model to reach a
simulation. The user requires inspectable evidence before authorizing such a change.

## Hard stop

- Diagnosis, measurements, and an isolated candidate provider are allowed.
- Do not change the production placement, ring-piercing gate, detector thresholds, locked phases, or
  production call sites until the user explicitly authorizes a candidate they have seen in an A/B
  artifact.
- Do not weaken, skip, rebaseline, or regenerate a failing geometry/topology/visual oracle while
  developing a candidate.
- A request to investigate, visualize, or build a diagnostic is not authorization to promote its
  molecular geometry.

Before asking for authorization, follow `docs/molecular_placement_audit.md` and
`memory/feedback_geometry_change_authorization.md`. The evidence must identify actual atoms,
bonds, and rings; prose names and aggregate pass counts are insufficient.
