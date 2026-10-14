---
name: project_simulation_runtime
description: Shared UI/headless managed simulation ownership, stop/resume and workspace context
type: project
---

# Managed simulation ownership (2026-10-10)

A headless CanDo runner in the same workspace as the live backend was incorrectly
marked stopped by UI reconciliation: `_RUNNING` existed only in the headless
Python process. Do not use isolated-workspace copies as the fix.

`backend/core/simulation_runtime.py` now provides a same-host kernel lease shared
by CanDo, SNUPI, mrDNA, oxDNA, LAMMPS, NAMD and BLaDE native runners. The lease spans
runner preparation, subprocess gaps and final publication. Request reservations
protect start/resume edits; reconciliation uses the same lock and leaves owned
manifests alone. Detached workers inherit the descriptor and wait for publication
before identifying as killable workers. Idle stop writes hold a lease and detached
post-kill writes check the generation, preserving a concurrent restart. Stop
commands are generation-scoped and
remain active through thread startup. NAMD early-stop controls acknowledge command
IDs. Thread registries are synchronized and workspace-scoped; active PID snapshots
include all workspaces.

Headless oxDNA uses context-local workspace overrides; concurrent job-read
coalescing also keys the effective workspace. Initial new-job package creation
and remote scheduler lifecycles retain their existing mechanisms.

See `docs/simulation_runtime.md`, `tests/test_simulation_runtime.py` and
`tests/test_simulation_runtime_api.py`. Regression tests include actual independent
process ownership, UI polling, stop/resume, killed-owner recovery, publication
gates, failure cleanup and duplicate starts. No scientific solver settings or
physical output are changed by the lifecycle patch.
