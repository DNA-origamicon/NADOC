# NADOC dev task runner
# Usage: just <target>

# Start FastAPI backend with hot reload
dev:
    uv run uvicorn backend.api.main:app --reload --reload-dir backend --reload-dir scripts --reload-exclude 'workspace/**' --reload-exclude 'experiments/**' --reload-exclude 'runs/**' --reload-exclude 'bp_health_runs/**' --reload-exclude 'gromacs_run/**' --reload-exclude 'memory/**' --host 0.0.0.0 --port 8000

# Run all tests
test:
    uv run pytest tests/ -v

# Run frontend unit tests (Vitest)
test-frontend:
    cd frontend && npm test

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
