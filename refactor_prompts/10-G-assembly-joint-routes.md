# Refactor 10-G — Extract `assembly.py` joint routes to `routes_assembly_joints.py`

**Worker prompt. Same pattern as 10-F (FastAPI sub-router extraction).**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions"
3. `REFACTOR_AUDIT.md` Findings #24 (Pass 8-B named assembly.py as #3 candidate)
4. `refactor_prompts/10-F-crud-loop-skip-routes.md` — sibling extraction; same pattern
5. `backend/api/main.py` — sub-router include pattern
6. `backend/api/assembly.py:1117-1293` — read the 3 joint routes in full + helpers
7. `backend/api/assembly_state.py` — sibling pattern (state-only extraction precedent)

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Extract the 3 assembly-joint routes (`POST /assembly/joints`, `PATCH /assembly/joints/{joint_id}`, `DELETE /assembly/joints/{joint_id}`) from `assembly.py:1117-1293` into a new `backend/api/routes_assembly_joints.py`. Same shape as 10-F.

## In scope

Move:
- `create_assembly_joint(body)` (L1117, `POST /assembly/joints`)
- `patch_assembly_joint(joint_id, body)` (L1200, `PATCH /assembly/joints/{joint_id}`)
- `delete_assembly_joint(joint_id)` (L1282, `DELETE /assembly/joints/{joint_id}`)

Plus module-private helpers used ONLY by these 3.

New file at `backend/api/routes_assembly_joints.py`. Register in main.py / routes.py via `app.include_router(...)`.

`assembly.py` keeps its `router` and all OTHER assembly route handlers (instances, configurations, camera poses, linker helices/strands/geometry, undo/redo, workspace, parts library, animations, validation, flatten, debug). Only the 3 joint handlers + their privates move.

## Out of scope

- Other assembly route clusters (instances, configurations, etc.) — separate Pass 11+ candidates
- Touching `_PHASE_*`, `make_bundle_continuation`, `linker_relax.py` core
- Renaming routes
- Adding path prefix

## Verification

3× baseline. Post:
- `tests/test_joints.py` — must still pass (existing test file, ~1088 LOC, exercises joint routes)
- `tests/test_assembly_*.py` — must still pass
- crud.py LOC unchanged (only assembly.py + new file modified)
- assembly.py LOC reduced by ≈ 180

## Stop conditions

- Step 0 fails → STOP
- Joint routes import private helpers from assembly.py used by other routes → tangled scope, STOP
- `tests/test_joints.py` fails post-extract → revert, STOP
- Sub-router doesn't register → STOP
- Any closure-captured state in assembly.py module body that the routes need → STOP, document; the right pattern is state-via-imports, not closure

## Output (Findings #35)

Same shape as #34. Required:
- 3 routes moved
- routes_assembly_joints.py LOC + assembly.py LOC delta
- Test files preserved
- USER TODO: load app, create + delete a cluster joint
- Linked: #24, sibling 10-F (#34)

## USER TODO template
1. `just dev` + `just frontend`; load any saved assembly
2. Create a cluster joint via Joints panel
3. Patch it (rotate); delete it
4. Confirm undo/redo + DevTools clean

## Do NOT
- Move other assembly routes
- Change URLs
- Commit / append to REFACTOR_AUDIT.md
