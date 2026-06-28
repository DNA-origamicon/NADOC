---
name: project_test_parallelization
description: Backend test suite runs in parallel (pytest-xdist); slow-test registry + global-state isolation gotcha
metadata: 
  node_type: memory
  type: project
  originSessionId: 2557a198-2648-4182-8f9b-1f6ff948cb26
---

The backend suite (3410 tests) was ~6 min serial; now runs parallel via pytest-xdist.

**Setup (shipped 2026-06-28):**
- `just test` / `just test-all` use `pytest -n auto --dist loadfile` → ~2.5 min (3348 passed, 63 skipped).
- `just test-fast` adds `-m "not slow"` → ~45s. Use for the tight dev loop; run full `just test` before pushing.
- `--dist loadfile` is REQUIRED (not default `--dist load`): tests share a module-level `TestClient(app)` over global per-doc backend state, so a file's tests must stay in-process and in-order on one worker.
- `pytest-xdist` is in dev deps + uv.lock.

**Slow-test registry lives in `tests/conftest.py`** (`pytest_collection_modifyitems` hook, `_SLOW_MODULES` + `_SLOW_TESTS`), NOT scattered `@pytest.mark.slow` decorators. The heavy tests drive real oxDNA/oxpy/GROMACS/protein-fork binaries or parse MD trajectories (MDAnalysis). To refresh after adding heavy tests: run with `--durations=0`, fold new ≥~2s "call" entries into the sets. (Pre-existing inline `@pytest.mark.slow` decorators are still honored.)

**Isolation gotcha (parallelism exposed a latent bug):** the oxDNA `/run` endpoint's `_assert_job_current` guard compares a job's snapshot fingerprint to the *global active design* (`_current_design_fingerprint()` → `state.get_or_404()`). Tests that don't set the active design pass only when the global store is empty (current_fp→None→guard skipped). Reordering under xdist lets another test's leftover design fire a spurious 409. Fixed in `test_oxdna_surface.py::_run_client` by monkeypatching `routes_oxdna._current_design_fingerprint` → `None` (those tests exercise run COMPOSITION, not staleness — which has its own tests). **NOT a production bug.** When adding new oxDNA/MD tests that hit job-run/staleness endpoints under parallelism, set the active design explicitly or neutralize the guard. Do NOT add a global autouse active-design reset — 68 files share a module-level client and build state across tests within a file.

See [[LESSONS]] (stale-state category).
