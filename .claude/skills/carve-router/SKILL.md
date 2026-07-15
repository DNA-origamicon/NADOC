---
name: carve-router
description: Run one iteration of the backend router carve-up loop on a named god-file. Use when the user invokes `/carve-router crud` or `/carve-router assembly` (or asks to "carve up crud.py / assembly.py" / "run a backend router carve-up"). Decomposes backend/api/crud.py or assembly.py into FastAPI sub-routers + backend/core service helpers, one cohesive cluster per session, measured against the anti-shovel coupling contract. NOT for frontend main.js (that's its own loop).
---

# carve-router

Run **one iteration** of the backend god-file decomposition loop. The single argument selects the target:
`crud` → `backend/api/crud.py`, `assembly` → `backend/api/assembly.py`. That argument is the only required
input.

The full protocol, target shapes, improvement metrics, and per-file backlog live in
**`backend_router_carveup.md`** (repo root). This skill is the thin driver that loads it and executes one pass.

## The bright line (read first)

This loop's entire reason to exist is to **stop LOC-shoveling.** Moving 400 lines from crud.py into a new
file is worthless if that file imports 25 private helpers back — coupling didn't drop, you just lengthened
the umbilical cord. So:

- **LOC is never the pass criterion.** It's narrative only.
- The pass criterion is **back-import surface `B` down, OR business logic moved into a tested `backend/core`
  function.** Every extraction logs `B before→after` and ends with a one-sentence justification naming which
  metric moved. No honest justification → it was a shovel → revert.

## Steps

1. **Resolve the target.** Argument `crud` or `assembly` → the god-file and its backlog section in
   `backend_router_carveup.md`. If no argument, ask which file.
2. **Load context:** read `backend_router_carveup.md` (protocol + backlog + the living `## Next-session
   handoff`) and `backend_router_extraction_log.md` (conventions + coupling probe + lessons + last metrics
   rows). Skim `.claude/rules/api-and-state.md` (the mutation contract you must not break).
   **Context economy:** the god-file scan in steps 3–5 (locate the region's `# ──` banner, still-used gate, coupling probe)
   is file-heavy — delegate it to a read-only, no-git `general-purpose` subagent that returns only the region range,
   before-`B`, and the still-used verdict (per `CLAUDE.md` → Workflow conventions). Do the protocol/handoff reasoning and
   the extraction itself here.
3. **Pick the region:** the handoff's `▶ NEXT` for this file, or the topmost unchecked backlog entry with the
   cleanest probed `B`, or one the user names. **Locate it by its `# ──` banner, not the printed line number**
   (they drift) — `grep -n "# ──" backend/api/<file>.py`.
4. **Still-used gate:** confirm the routes are still called — `rg "<url-fragment>" frontend/src/api/client.js`.
   Dead cluster → propose deleting it, don't extract it.
5. **Run the coupling probe** (the bash snippet in the log's "Coupling probe" section) on the region's range.
   Record before-`B`. If `B > 3`, apply the high-B playbook (co-extract helpers to `backend/core`, or pick a
   cleaner cluster) before proceeding.
6. **Decide the move type** and extract ONE cohesive block:
   - **Router** → new `backend/api/routes_<area>.py` mirroring `routes_loop_skip.py` / `routes_camera_poses.py`
     **exactly**: `router = APIRouter()`, move the `BaseModel`s + handlers **verbatim** (byte-identical bodies
     — preserves behavior and the mutation contract), import shared kernel helpers back. Add
     `app.include_router(<area>_router, prefix="/api")` in `backend/api/main.py`. Delete the moved code from
     the god-file. **URLs do not change.**
   - **Service** → pure HTTP-free fn in new/existing `backend/core/<area>.py` (core must NOT import api) + a
     **direct input→output unit test** in `tests/`. The handler keeps its decorator and shrinks to
     parse→delegate→respond.
   - Both? Do the service push first (separate commit).
7. **Gate:** `just test-smart` green — cite its decision + pass count, flag any *drop*. `just lint` clean on touched files. (Full `just test` is the pre-push gate, not this loop.) A
   service extraction without a new unit test does not ship.
8. **Commit** (one region): `<area>: extract <cluster> router/service from <file>.py`. Only when the user has
   asked to commit, per CLAUDE.md git rules.
9. **Update the ledgers:** check the box in the backlog, add a metrics row to the log **with the mandatory
   justification sentence**, and **overwrite** the `## Next-session handoff` block with the next recommended
   region per file + its probed before-B + any gotcha found.
10. **Route findings:** bug found → `issues_ledger.md` (+ `issues_fix_log.md` if fixed). Stuck region →
    the log's difficulties ledger with *why*. Un-hand-checked behavior shipped → `manual_validation_debt.md`.
    Those ledgers are now lean *heads* with a `*_archive.md` sibling holding closed items — **append to the
    head, never read the archive in a routine loop.** See `memory/project_context_economy_split.md`.

## Don't

- Don't parallelize edits to one god-file (serial — worktrees collide on the shared import block).
- Don't change any route URL, touch `_PHASE_*`, or alter a handler's `mutate_and_validate` /
  `set_design_silent` / `snapshot` usage (silently breaks undo/redo).
- Don't let `backend/core` import from `backend/api`.
- Don't chase LOC. Chase `B` and testable-core delegation.
