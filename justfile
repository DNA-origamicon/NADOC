# NADOC dev task runner
# Usage: just <target>

# One-time full setup: install tools + all deps (see setup.sh)
setup:
    ./setup.sh

# Start backend + frontend together (Ctrl-C to stop). Run `just setup` first.
start:
    ./start.sh

# Start FastAPI backend with hot reload.
# --timeout-graceful-shutdown: the status websockets (/ws/md-jobs) are long-lived
# and never close on their own, so a --reload or stop used to wedge uvicorn forever
# in "Waiting for connections to close" — freezing every job (prep heartbeat dies,
# HTTP hangs). Cap the wait so a reload always force-closes within a few seconds.
dev:
    uv run uvicorn backend.api.main:app --reload --timeout-graceful-shutdown 5 --reload-dir backend --reload-dir scripts --reload-exclude 'workspace/**' --reload-exclude 'experiments/**' --reload-exclude 'runs/**' --reload-exclude 'bp_health_runs/**' --reload-exclude 'gromacs_run/**' --reload-exclude 'memory/**' --host 0.0.0.0 --port 8000

# Run all tests, parallel across cores (~2.5x faster than serial).
# --dist loadfile keeps each file's tests on one worker: tests share a
# module-level TestClient(app) over global per-doc backend state, so a file's
# tests must stay in-process and in-order. Dropped -v (printed all 3410 names
# for no signal); failures still print full tracebacks.
test:
    uv run pytest tests/ -n auto --dist loadfile

# Fast dev loop: skip the heavy real-binary sims AND the CanDo-FEM/autorefine
# numeric solves (all carry the `slow` marker via tests/conftest.py). Parallel.
# Keep the slow registry current: if this creeps back up, run
#   uv run pytest tests/ -n auto --dist loadfile -m "not slow" --durations=25
# and fold any new >=~2s "call"/"setup" entries into conftest's _SLOW_* sets.
# Run plain `just test` before pushing.
test-fast:
    uv run pytest tests/ -n auto --dist loadfile -m "not slow"

# Change-based selection: run the fast suite (always) + only the HEAVY test
# groups affected by your uncommitted changes. Foundational/unknown changes ->
# full suite; a leaf change (oxDNA, CanDo/FEM, NAMD, ...) -> just that group.
# `just test-smart --dry-run` shows the decision without running. Forward pytest
# args after `--`, or diff against a ref with `--base origin/master`.
test-smart *ARGS:
    uv run python scripts/select_tests.py {{ARGS}}

# Tightest inner loop: point pytest at the area you're editing. Pass file paths
# and/or `-k pattern`; heavy solves are dropped (`-m 'not slow'`) so it stays
# snappy. Examples:
#   just test-affected tests/test_cando_deviation.py
#   just test-affected tests/test_fem_solver.py -k rmsf
#   just test-affected tests/test_overhang_geometry.py --lf   # only last failures
# (True change-based impact analysis — pytest-testmon — is currently broken
#  against pytest 9.x; see memory/project_test_parallelization.md.)
test-affected *ARGS:
    uv run pytest -m "not slow" {{ARGS}}

# Run frontend unit tests (Vitest), single pass
test-frontend:
    cd frontend && npm test

# Tight loop: Vitest in watch mode — re-runs affected tests on save (sub-second)
test-frontend-watch:
    cd frontend && npx vitest

# Run backend + frontend unit tests together ("is everything green?")
test-all:
    uv run pytest tests/ -n auto --dist loadfile
    cd frontend && npm test

# Commit gate for main.js refactor work: the full smoke suite — app boot, the
# File>New dialog flow, command palette, API, the console-error render gate, and
# the teardown gate (design close-session in smoke.spec.js + assembly-mode exit
# in assembly_exit_cleanup.spec.js — teardown is where #34's const-reassignment
# bug escaped, so it's now in the gate) (~1.5 min, NOT per-iteration).
smoke:
    cd frontend && npx playwright test --config playwright.smoke.config.js smoke.spec.js assembly_exit_cleanup.spec.js

# Diagnose oxDNA GPU setup (add --fix to auto-build a CUDA-enabled oxDNA)
oxdna-doctor *ARGS:
    uv run python scripts/oxdna_doctor.py {{ARGS}}

# mrdna round-trip benchmarks: forward-translation traceability + back-map +
# no-explosion guards across a few designs. --fast = Phase A only (no GPU).
# Run ./scripts/setup-mrdna.sh first. (e.g. `just bench-mrdna --fast`)
bench-mrdna *ARGS:
    uv run python scripts/benchmark_mrdna_roundtrip.py {{ARGS}}

# Audit the atomistic ball-and-stick display of an oxDNA job's relaxed frame (default 6hb_sim_tests, latest job)
audit-atomistic *ARGS:
    uv run python scripts/audit_atomistic.py {{ARGS}}

# Audit a sampling of the View-trajectory frames (whole lineage) — per-frame invariants, not just frame 0
audit-trajectory *ARGS:
    uv run python scripts/audit_atomistic.py --trajectory {{ARGS}}

# Start Vite frontend dev server (requires FastAPI running separately)
frontend:
    cd frontend && npm run dev -- --host 0.0.0.0

# Build frontend for production (output to frontend/dist)
build-frontend:
    cd frontend && npm run build

# Bake hover-preview GIFs + posters for workspace/Primitives/*.nadoc (needs `just dev` + `just frontend` running)
build-primitives:
    cd frontend && node scripts/build-primitives.mjs

# Run a specific test file
test-file FILE:
    uv run pytest {{FILE}} -v

# Format code
fmt:
    uv run ruff format backend/ tests/

# Lint code
lint:
    uv run ruff check backend/ tests/
