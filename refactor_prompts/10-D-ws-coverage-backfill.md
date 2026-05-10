# Refactor 10-D — `ws.py` coverage backfill (helper-function isolation)

**Worker prompt. (test) coverage backfill. No production code changes.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #15, #21 calibrated coverage targets)
3. `REFACTOR_AUDIT.md` Findings #16 (ws.py at 4.2% cov), #24 (Pass 8-B named ws.py as #2 candidate)
4. `backend/api/ws.py:411-988` — read `md_run_ws` body in full to identify pure-ish inner helpers

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`backend/api/ws.py` is 988 LOC at 4.2% coverage. The 578-LOC `md_run_ws` websocket handler is hard to test directly (would need a fake websocket + MDAnalysis fixture), but it contains inner sync helpers that are testable in isolation:

- `_load_sync(topology_str, xtc_str, mode, design)` (L483, ~233 LOC) — loads MDAnalysis Universe, builds atom-meta, returns dict. Pure-ish (file I/O via MDAnalysis but no websocket dep).
- `_seek_sync(frame_idx)` (L717) — seeks Universe to frame, builds positions/atoms list. Stateful but testable with a small fixture trajectory.
- `_try_unwrap(u, logs)` (L451) — adds PBC unwrap transformation. Pure of websocket; touches MDAnalysis Universe.

Write `tests/test_ws_helpers.py` with tests for these 3 inner helpers. **Calibrated target**: 4.2% → 25%+ (calibrated against the share of LOC the 3 helpers represent — verify before claiming).

## Strategy (NO production code change — this is the load-bearing constraint)

The 3 inner helpers are CURRENTLY closure-captured by `md_run_ws` (defined inside it). To test them, you have two options:

**Option A** (simpler): use Python's `unittest.mock.patch` + `inspect.getsource` to extract and exec the helper bodies into a test scope — fragile, not recommended.

**Option B** (recommended): mock the websocket dependency by writing tests that DRIVE `md_run_ws` directly via a fake-websocket protocol. Test the load → seek → get_latest message flow with a small fixture trajectory. Coverage of the inner helpers comes naturally.

**Option C** (lightest scope): Test only the module-level helpers that are NOT inside `md_run_ws`. From a quick read, anything at module scope (utility functions, classes, `_PHYSICS_INTERVAL` constants) is testable. Audit for these first; if too few, fall back to Option B.

Pick the lightest option that hits the target. **Document which option you chose and why.**

## In scope

- New `tests/test_ws_helpers.py` (or `test_ws.py` if more appropriate)
- Pytest-asyncio if needed (likely already a project dep; check `pyproject.toml`)
- Mock objects for websocket (use `unittest.mock.AsyncMock`)
- Synthetic small XTC + GRO fixture if Option B chosen — keep < 50 KB, document source/license

## Out of scope

- Modifying `backend/api/ws.py` source. Read-only target. If you find an apparent bug, document under "Apparent-bug flags".
- Testing `physics_ws`, `physics_fast_ws`, `fem_ws` — separate prompts.
- Testing the actual GROMACS trajectory streaming.

## Verification (3× baseline)
```bash
for i in 1 2 3; do just test > /tmp/10D_test_pre$i.txt 2>&1; done
just lint > /tmp/10D_lint_pre.txt 2>&1
```
Coverage post: `uv run coverage run -m pytest tests/test_ws_helpers.py && uv run coverage report --include='backend/api/ws.py'`

## Stop conditions

- Step 0 fails → STOP
- Option B requires fixture > 50 KB → use a smaller trajectory or fall back to Option C
- Adding pytest-asyncio breaks other tests → revert, STOP
- Test post-failure not in stable_baseline ∪ flakes → revert, STOP
- Apparent bug in ws.py production → document, do NOT fix per `feedback_interrupt_before_doubting_user.md`

## Output (Findings #32)

Required:
- Strategy chosen (A/B/C) with reasoning
- ws.py post-coverage % (calibrated against scope)
- Tests added count
- Lint Δ
- Apparent-bug flags if any
- USER TODO: load `just frontend` + a GROMACS trajectory if available; confirm websocket flow still works

## Do NOT
- Modify ws.py
- Add new dev-deps to pyproject.toml
- Commit / append to REFACTOR_AUDIT.md
