# NADOC dev task runner
# Usage: just <target>

# One-time full setup: install tools + all deps (see setup.sh)
setup:
    ./setup.sh

# Start backend + frontend together (Ctrl-C to stop). Run `just setup` first.
start:
    ./start.sh

# Start FastAPI backend with hot reload
dev:
    uv run uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
test:
    uv run pytest tests/ -v

# Run frontend unit tests (Vitest), single pass
test-frontend:
    cd frontend && npm test

# Tight loop: Vitest in watch mode — re-runs affected tests on save (sub-second)
test-frontend-watch:
    cd frontend && npx vitest

# Run backend + frontend unit tests together ("is everything green?")
test-all:
    uv run pytest tests/
    cd frontend && npm test

# Commit gate for main.js refactor work: the full smoke suite — app boot, the
# File>New dialog flow, command palette, API, the console-error render gate, and
# the teardown gate (design close-session in smoke.spec.js + assembly-mode exit
# in assembly_exit_cleanup.spec.js — teardown is where #34's const-reassignment
# bug escaped, so it's now in the gate) (~1.5 min, NOT per-iteration).
smoke:
    cd frontend && npx playwright test smoke.spec.js assembly_exit_cleanup.spec.js

# Start Vite frontend dev server (requires FastAPI running separately)
frontend:
    cd frontend && npm run dev -- --host 0.0.0.0

# Build frontend for production (output to frontend/dist)
build-frontend:
    cd frontend && npm run build

# Run a specific test file
test-file FILE:
    uv run pytest {{FILE}} -v

# Format code
fmt:
    uv run ruff format backend/ tests/

# Lint code
lint:
    uv run ruff check backend/ tests/
