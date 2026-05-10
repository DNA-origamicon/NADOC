# Refactor 09-C — `fem_solver.py` pure-math test backfill

You are a **worker session** in a git worktree. **(test) coverage backfill** — additive (new test file only). No production code changes expected.

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)**, **#15 (CWD-safety)**
3. `REFACTOR_AUDIT.md` § "Findings" #16 (audit naming `fem_solver.py` at 22% coverage as testable physics math), #24 (Pass 8-B tagged it `high` for radon C)
4. `backend/physics/fem_solver.py:200-260` — read the 2 target pure-math helpers in full
5. `backend/physics/fem_solver.py` — skim the rest to understand context
6. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`backend/physics/fem_solver.py` is at 22% coverage / 503 LOC. The matrix-assembly helpers `_beam_stiffness_local` and `_transform_to_global` are pure-math (numpy in / numpy out) and trivially testable in isolation. Write `tests/test_fem_solver_math.py` with focused tests on these helpers + any other deterministic pure-math fragments you find in the module.

Target: lift `fem_solver.py` coverage from 22% to ≥ 50% (no need to test the actual `solve_equilibrium` or RMSF eigsh — those are integration tests for a future pass).

## In scope — function targets

Top priority (pure-math, 0 fixture cost):

- `_beam_stiffness_local(L: float) -> np.ndarray` (L202): returns a 12×12 local-frame Euler-Bernoulli beam stiffness matrix. Pure function of element length L. Test:
  - returned matrix shape == (12, 12)
  - symmetry: `K == K.T`
  - axial-stiffness block (rows/cols 0 and 6): `K[0,0] = K[6,6] = EA/L`, `K[0,6] = -EA/L` (sign matches Bernoulli convention)
  - bending blocks: `K[1,1] = K[7,7] = 12 EI / L^3` (or whatever the body actually computes — read the body to know exact constants)
  - rank: 6 (rigid-body modes account for 6 zero eigenvalues)

- `_transform_to_global(K_local: np.ndarray, R: np.ndarray) -> np.ndarray` (L245): rotates a local stiffness matrix to global frame via `R^T K R`. Pure function. Test:
  - identity rotation → output equals input
  - 90° rotation around z-axis → expected block-permutation pattern
  - orthogonality: if `R` is orthogonal then `K_global` is symmetric (assuming `K_local` was symmetric)
  - shape preservation: 12×12 in → 12×12 out

Second priority (if straightforward):

- Any other pure-math helper you find while reading. Examples: a `_rotation_matrix_from_axis(axis: np.ndarray, angle: float)` if present; a stiffness-coefficient calculator; an RMSF normalization step.

Skip:

- `build_fem_mesh` (L105) — touches `Design` topology; integration test; future pass
- `assemble_global_stiffness` (L264) — orchestrator; needs an FEMMesh fixture
- `apply_boundary_conditions` (L320) — same
- `solve_equilibrium` (L353) — calls `scipy.sparse.linalg.spsolve`; integration test
- `compute_rmsf` (L388) — calls `scipy.sparse.linalg.eigsh`; integration test
- `deformed_positions` (L442) — orchestrator
- `normalize_rmsf` (L488) — pure but trivial; include if helpful, optional

## Out of scope

- Modifying `backend/physics/fem_solver.py`. Read-only target.
- Testing the integration flow.
- Adding `pytest-cov` to dev-deps.
- Other coverage-low modules.

## Verification plan

### Pre-state (3× baseline)
```bash
git status > /tmp/09C_dirty_pre.txt
just lint > /tmp/09C_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/09C_lint_pre.txt
for i in 1 2 3; do just test > /tmp/09C_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/09C_test_pre$i.txt | sort > /tmp/09C_baseline$i.txt; done
comm -12 /tmp/09C_baseline1.txt /tmp/09C_baseline2.txt | comm -12 - /tmp/09C_baseline3.txt > /tmp/09C_stable_failures.txt
```

### Implementation
1. Read `_beam_stiffness_local` (L202-244) end to end. Note exact EA / EI / GJ constants and matrix layout.
2. Read `_transform_to_global` (L245-263).
3. Write `tests/test_fem_solver_math.py` with 6-10 tests covering the helpers + any 1-2 additional deterministic pieces you find.
4. Run `just test-file tests/test_fem_solver_math.py` — all should pass.
5. Run full `just test` — failure set ⊆ stable_baseline ∪ flakes.

### Post-state
```bash
just lint > /tmp/09C_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/09C_lint_post.txt
just test > /tmp/09C_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/09C_test_post.txt | sort > /tmp/09C_post_failures.txt
diff /tmp/09C_stable_failures.txt /tmp/09C_post_failures.txt   # ⊆ stable_baseline ∪ flakes

uv run coverage run -m pytest tests/test_fem_solver_math.py
uv run coverage report --include='backend/physics/fem_solver.py' > /tmp/09C_cov_post.txt
```

## Stop conditions

- Step 0 fails: STOP.
- A test surfaces what looks like a bug in fem_solver math: STOP, document under "Apparent-bug flags", do NOT fix the production code. Per `feedback_interrupt_before_doubting_user.md`, the math is calibrated — verify before assuming.
- A test requires SciPy / NumPy that isn't installed: should not happen (project depends on both); if it does, document.

## Output

```markdown
## 09-C fem_solver pure-math tests — <REFACTORED|UNSUCCESSFUL>

### CWD-safety check
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 28. `fem_solver.py` pure-math test backfill — `low` ✓ REFACTORED (test category)
- **Category**: (test) coverage backfill
- **Move type**: additive (new test file only)
- **Where**: `tests/test_fem_solver_math.py` (new, ~150 LOC, N tests)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 1; other-files: none
- **Transparency check**: not applicable (additive tests)
- **API surface added**: none
- **Visibility changes**: none
- **Pre-metric → Post-metric**:
  - `fem_solver.py` coverage: 22% → <X%>
  - Tests: <pre> → <pre + N>
  - Lint Δ: 0
- **Raw evidence**: `/tmp/09C_*.txt`, `/tmp/09C_cov_post.txt`
- **Linked Findings**: #16 (Tier-2 testable physics math), #18 (PDB pure-math precedent), #24 (audit tag)
- **Apparent-bug flags**: <none | list>
- **Skipped functions**: build_fem_mesh / orchestrators (integration tests; future pass)
```

## Success criteria

- [ ] Step 0 passed
- [ ] `tests/test_fem_solver_math.py` exists with ≥ 6 tests
- [ ] `fem_solver.py` post-coverage ≥ 50%
- [ ] No production code modified
- [ ] Test post-failure ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0

## Do NOT
- Modify `backend/physics/fem_solver.py`.
- Test integration paths (`build_fem_mesh`, `assemble_global_stiffness`, `solve_equilibrium`, `compute_rmsf`).
- Mock SciPy. Use the real numpy/scipy installed.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
