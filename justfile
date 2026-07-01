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

# Fast dev loop: skip the heavy real-binary sims (oxDNA/MD/GROMACS/atomistic),
# parallel. ~30s vs ~2.5min full. Run plain `just test` before pushing.
test-fast:
    uv run pytest tests/ -n auto --dist loadfile -m "not slow"

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
