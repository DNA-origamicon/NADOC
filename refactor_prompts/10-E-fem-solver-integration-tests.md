# Refactor 10-E — `fem_solver.py` integration tests (FEMMesh fixture + orchestrators)

**Worker prompt. (test) coverage backfill. No production code changes.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #15, #21 calibrated coverage targets)
3. `REFACTOR_AUDIT.md` Findings #16 (Tier-2 fem_solver.py), #28 (Pass 9-C pure-math tests; baseline established at 37%), #24 (audit naming)
4. `backend/physics/fem_solver.py:105-485` — read `build_fem_mesh`, `assemble_global_stiffness`, `apply_boundary_conditions`, `solve_equilibrium`, `compute_rmsf`, `deformed_positions`
5. `tests/test_fem_solver_math.py` (Pass 9-C reference) — see how the pure helpers were tested
6. `tests/conftest.py::make_minimal_design()` — fixture starting point

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`fem_solver.py` is at 37% coverage post-Pass-9-C. The 6 integration orchestrators (`build_fem_mesh`, `assemble_global_stiffness`, `apply_boundary_conditions`, `solve_equilibrium`, `compute_rmsf`, `deformed_positions`) need a real FEMMesh fixture + scipy invocation to exercise. Goal: write `tests/test_fem_solver_integration.py` that covers the pipeline end-to-end against a small synthetic Design.

**Calibrated target**: 37% → 70%+ (build_fem_mesh + assemble + apply_BC together = ~70 stmts; solve + rmsf + deformed = ~50 stmts; together those plus existing 37% should reach 70-85%).

## Fixture strategy

Use `make_minimal_design(n_helices=2, helix_length_bp=42)` as the starting Design. Build FEMMesh from it via `build_fem_mesh(design)` — this is the integration-test entry point. Then test downstream orchestrators against the resulting mesh.

The eigsh / RMSF computation uses scipy.sparse — slow but tested. Mark the slowest test with `@pytest.mark.slow` if there's a marker convention; otherwise just keep it tight.

## In scope

`tests/test_fem_solver_integration.py` with:

- `TestBuildFemMesh` (3-4 tests):
  - n_helices=1, helix_length=21 → mesh has expected node/element counts
  - n_helices=2 → inter-helix springs present where expected
  - empty Design → raises or returns empty mesh
- `TestAssembleGlobalStiffness` (2-3 tests):
  - shape matches `(6N, 6N)` where N = node count
  - symmetric
  - all element-type contributions present (beam + spring blocks)
- `TestApplyBoundaryConditions` (2 tests):
  - centroid-pinned BC zeroes the right rows/cols
  - returns a smaller positive-definite reduced K
- `TestSolveEquilibrium` (2 tests):
  - zero applied force → solution is zero displacement
  - non-zero force → finite displacement, no NaNs
- `TestComputeRmsf` (1-2 tests, slowest):
  - returns dict with `helix_id:bp:dir` keys, values in [0, 1]
  - small mesh → completes in < 5s

## Out of scope

- Modifying fem_solver.py source. If you spot an apparent bug, flag it but do NOT fix.
- Testing the FEM physics correctness (force/displacement values are calibration territory; just check shape, finiteness, sanity bounds).
- Adding scipy as a new dep (already present).

## Verification (3× baseline)
Standard. Plus: `uv run coverage report --include='backend/physics/fem_solver.py'` post-state.

## Stop conditions
- Step 0 fails → STOP
- A test consistently exceeds 30s wall-clock → mark `pytest.skip` with TODO; document
- Apparent bug → document, do NOT fix
- Test post-failure not in baseline ∪ flakes → revert offending test, ship rest

## Output (Findings #33)

Required:
- Tests added count + classes
- Coverage 37% → ?%
- Slowest test wall-clock
- Apparent-bug flags
- Calibration check: did target match scope?
- Linked: #16, #28, #24

## Do NOT
- Modify fem_solver.py
- Add new dev-deps
- Commit / append to REFACTOR_AUDIT.md
