# Refactor 10-F — Extract `crud.py` loop-skip routes to `routes_loop_skip.py`

**Worker prompt. (c) god-file decomposition — first FastAPI sub-router extraction in this codebase.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #6 audit-self-ref exemption, #15, #16 hand-apply threshold)
3. `REFACTOR_AUDIT.md` Findings #24 (Pass 8-B named crud.py as #1 candidate), #19 (`_overhang_junction_bp` chain-link helper — same area), #14 (F401 cleanup precedent)
4. **`backend/api/main.py`** — read FastAPI app + router-include pattern
5. `backend/api/crud.py:1-50` — read the existing `router = APIRouter(...)` instantiation + imports
6. `backend/api/crud.py:8920-9170` — read the 5 loop-skip route handlers in full + their helpers
7. `backend/api/state.py` — `mutate_with_*` wrappers used by route handlers
8. **`memory/feedback_phase_constants_locked.md`** — `_PHASE_*` constants are LOCKED, do not touch

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`crud.py` is 10416 LOC (Finding #24's #1 candidate). Extract the 5 loop-skip route handlers (L8920-L9170) into a new `backend/api/routes_loop_skip.py` sub-router module. This is a **proof-of-concept** for FastAPI sub-router extraction; the same pattern can later extract the remaining 270+ route handlers in subsequent passes.

## In scope

Move these 5 route handlers verbatim from `crud.py` to `routes_loop_skip.py`:
- `insert_loop_skip(body)` (L8921, `POST /design/loop-skip/insert`)
- `apply_twist_loop_skips(body)` (L8964, `POST /design/loop-skip/twist`)
- `apply_bend_loop_skips(body)` (L9017, `POST /design/loop-skip/bend`)
- `get_loop_skip_limits(...)` (L9072, `GET /design/loop-skip/limits`)
- `clear_loop_skip_range(...)` (L9110, `DELETE /design/loop-skip`)

Plus any module-private helpers (request bodies, helper functions) used ONLY by these 5 handlers — verify by `rg`.

The new `routes_loop_skip.py` must:
1. Have its own `router = APIRouter()` (no path prefix; the routes already declare full paths like `/design/loop-skip/insert`)
2. Import shared deps from `state.py`, `models.py`, `lattice.py`, `loop_skip_calculator.py` directly (don't go through crud.py)
3. Re-import only what the routes actually need

`backend/api/main.py` (or `routes.py`) must register the new router via `app.include_router(routes_loop_skip.router)`. Verify the existing pattern by reading `main.py`.

`crud.py` keeps its existing `router` and all OTHER route handlers; only the 5 loop-skip handlers + their private helpers move.

## Out of scope

- The 270+ other crud.py route handlers (separate Pass 11+ candidates — this prompt is single-cluster)
- Touching `state.mutate_with_*` wrappers
- Touching `_PHASE_*` constants (LOCKED)
- Touching `loop_skip_calculator.py` (private constants `_LOOP_SKIP_*` LOCKED per Finding #5)
- Renaming routes (URL paths stay identical)
- Adding a path prefix (changes URLs)

## Verification

3× baseline. Post-state requires:
- `just test` — failure set ⊆ stable_baseline ∪ flakes
- `tests/test_loop_skip.py` (existing; ~700 LOC) — must still pass since it exercises these routes
- `curl localhost:8000/design/loop-skip/...` — manually verify if `just dev` running, OR rely on tests
- Lint Δ ≤ 0
- crud.py LOC reduced by ≈ 250

```bash
for i in 1 2 3; do just test > /tmp/10F_test_pre$i.txt 2>&1; done
just lint > /tmp/10F_lint_pre.txt 2>&1
just test-file tests/test_loop_skip.py 2>&1 | tail -3   # pre
# ... do the work ...
just test-file tests/test_loop_skip.py 2>&1 | tail -3   # post — must pass
```

## Stop conditions

- Step 0 fails → STOP
- A loop-skip route imports a private helper from crud.py NOT used by other routes → move it too; if it uses MULTIPLE crud.py privates that ARE used by other routes → STOP, scope is too tangled, recommend splitting differently
- `tests/test_loop_skip.py` fails post-extract → revert and STOP. The transparency requirement is load-bearing.
- The new router doesn't get registered → URLs return 404 → revert
- Any `_PHASE_*` constant referenced → STOP

## Output (Findings #34)

Required:
- 5 route handlers moved verbatim (or list which couldn't move with reason)
- routes_loop_skip.py LOC + crud.py LOC delta
- main.py / routes.py change to register new router
- Tests preserved: `test_loop_skip.py` baseline-equivalent
- USER TODO: `just dev` + curl one of the loop-skip endpoints to confirm router-include works
- Linked: #24 (parent audit), #14 (precedent), #5 (touches loop_skip_calculator import area but does NOT touch its constants)

## USER TODO template
1. `just dev` and confirm uvicorn boots without errors
2. `curl -X POST http://localhost:8000/design/loop-skip/limits` (or via the app UI) — should return 200 with limits
3. Apply a loop-skip via the UI; confirm undo/redo still works
4. Confirm DevTools console clean

## Do NOT
- Move other route handlers
- Change URLs
- Touch _PHASE_* / _LOOP_SKIP_* constants
- Commit / append to REFACTOR_AUDIT.md
