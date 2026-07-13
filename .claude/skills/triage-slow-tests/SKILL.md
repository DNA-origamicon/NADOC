---
name: triage-slow-tests
description: Triage a per-change test suite that blew the 60s budget — find what made it slow and relegate it to the test-dedicated (slow) suite. Use when scripts/test_guard.sh prints "TEST BUDGET EXCEEDED", when `just test-smart` / `just test-fast` takes over a minute, or when the user asks why the fast suite got slow. NOT for fixing failing tests (that's the issues ledger).
---

# Triage slow tests

The per-change loop (`just test-smart`, `just test-fast`) is only useful if it stays
under **60 s**. When it doesn't, something heavy has leaked into the fast suite. Your
job is to find it and move it out — never to raise the budget.

## The law you are enforcing

Heavy tests run **only** inside a test-dedicated session (`just test-session`, opened by
the user in their own terminal). Everything else must be fast. A test that takes minutes
in an ordinary coding session is a bug in the test layout, not a fact of life.

## Inputs

- `.nadoc-slow-candidates.json` (repo root, gitignored) — written by every fast run:
  `violators` = unmarked tests over the per-test budget (default 5 s, `NADOC_PER_TEST_BUDGET_SEC`),
  plus `slowest_25` and `total_test_seconds` for context.
- If it's missing or stale, regenerate:
  `NADOC_TEST_CONFIRM=1 just test-fast` (it rewrites the file), or for a durations table:
  `uv run pytest tests/ -n auto --dist loadfile -m "not slow" --durations=25`

## Procedure

1. **Read the report.** Rank the violators. Note whether the pain is a few fat tests
   (fix: relegate them) or a broad drift of 1–3 s tests (fix: find the shared fixture).
2. **Diagnose each violator — say WHY it is slow.** The usual causes, in order:
   - spawns a real binary (oxDNA/oxpy, NAMD, mrdna, GROMACS) or touches the GPU
   - a numeric solve (CanDo/FEM eigensolve, autorefine) or a big minimisation
   - parses/loads a large real artifact (multi-MB PSF/DCD/PDB, a real job directory)
   - an expensive **module- or class-scoped fixture** every test in the file pays
   - none of the above → it may just be *accidentally* slow (an O(n²) loop, a sleep,
     a network/filesystem stall). Those get **fixed**, not relegated.
3. **Relegate the genuinely heavy ones.** Edit the registry in
   [tests/conftest.py](../../../tests/conftest.py) — do NOT scatter `@pytest.mark.slow`
   decorators:
   - whole file heavy (or setup-dominated by a shared fixture) → `_SLOW_MODULES`
   - a class sharing one expensive class-scoped fixture → `_SLOW_CLASSES`
   - individual heavy tests → `_SLOW_TESTS`
   Collection auto-adds `slow` **plus** the area marker from `_slow_area_for()`
   (`oxdna` / `cando` / `namd` / `mrdna` / `atomistic` / `md` / `headless`). If the
   module name doesn't route to the right area there, extend that function — the area
   marker is what lets `scripts/select_tests.py` re-run only the affected heavy group in
   a later test-dedicated session.
   Check `scripts/select_tests.py`'s `LEAF_RULES` too: the *source* file that the newly
   relegated test covers should route to the same area.
4. **Verify the budget is back.** `NADOC_TEST_CONFIRM=1 just test-fast` — it prints
   `test budget: Ns / 60s ok`. Confirm the relegated tests still *exist* in the slow
   suite: `uv run pytest tests/ -m slow --collect-only -q | tail -3` (collect-only is
   cheap and does not run them).
5. **Report** — for each violator: seconds, why it was slow, relegated (which bucket +
   area) or fixed (what you changed), and the new fast-suite wall time.

## Rules

- **Never** raise `NADOC_TEST_BUDGET_SEC` or weaken `scripts/test_guard.sh` to make the
  banner go away. That is the failure this whole mechanism exists to prevent.
- **Never** open a test-dedicated session yourself (`just test-session` is TTY-only for a
  reason) and never hand-write `.nadoc-test-session` or set `NADOC_TEST_FORCE=1`.
- Relegating a test does **not** delete coverage: it still runs in `just test` /
  `just test-slow` inside a test-dedicated session, and `select_tests.py` records the
  group as owed in `.nadoc-slow-pending`.
- If a violator is fast-suite-critical (it guards a topology/geometry invariant), prefer
  **shrinking** it — smaller design, fewer bp, cached fixture — over relegating it.
