# Refactor 13-B — Extract `crud.py` camera-poses routes to `routes_camera_poses.py`

**Worker prompt. Same pattern as 10-F (loop-skip sub-router extraction).**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15, #24 tangled-scope pre-pass pattern)
3. `REFACTOR_AUDIT.md` Findings #34 (Pass 10-F crud loop-skip extract — the template)
4. `refactor_prompts/10-F-crud-loop-skip-routes.md` — sibling template
5. `backend/api/crud.py` — grep for camera-poses routes
6. `backend/api/main.py` — sub-router include pattern (`prefix="/api"` is established convention)

## Step 0 — CWD safety (precondition #15 HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

Extract the camera-poses route cluster from `crud.py` into a new `backend/api/routes_camera_poses.py` sub-router module. Same template as 10-F.

Per CLAUDE.md routes index (api-and-state.md):
- `POST /design/camera-poses` — add camera pose
- `PATCH /design/camera-poses/{id}` — update pose
- `PUT /design/camera-poses/reorder` — reorder list
- `DELETE /design/camera-poses/{id}` — remove

Grep `crud.py` for these exact paths to find the route definitions. Verify there's a contiguous block (typical 4-route cluster size).

## In scope

Move:
- The 4 camera-poses route handlers + their request/response Pydantic models if module-private
- Module-private helpers used ONLY by these 4 routes (verify by `rg`)

Apply preconditions #19, #20, #24 (tangled-scope check):
- **Before extracting**: identify all module-private symbols the 4 routes use. If any are shared with non-target routes in crud.py, this is tangled scope — STOP and report (per #24, recommend a pre-pass kernel extraction).

New file at `backend/api/routes_camera_poses.py`. Register in main.py via `app.include_router(camera_poses_router, prefix="/api")` (matching the loop-skip pattern).

`crud.py` keeps `router` + all other routes.

## Out of scope

- Other route clusters
- Touching `_PHASE_*`, `_LOOP_SKIP_*`, `state.mutate_*` wrappers
- Renaming routes (URL paths stay identical)
- Adding/changing path prefix beyond the existing `/api`

## Verification

3× baseline + lint:

```bash
for i in 1 2 3; do just test > /tmp/13B_test_pre$i.txt 2>&1; done
just lint > /tmp/13B_lint_pre.txt 2>&1
just test-file tests/test_camera_poses.py 2>&1 | tail -3 2>/dev/null  # may not exist
just test-file tests/test_animation.py 2>&1 | tail -3  # animation uses camera poses
```

Post:
- crud.py LOC reduced by ≈ moved-route total
- routes_camera_poses.py exists + LOC matches expected
- `tests/test_animation.py` + any camera-pose-specific tests still pass
- URL paths identical pre/post (10-F pattern: `prefix="/api"` preserves `/api/design/camera-poses/...`)
- Lint Δ ≤ 0

## Stop conditions

- Step 0 fails → STOP
- Camera-poses routes import module-private helpers shared with other routes → STOP, recommend pre-pass extraction (per #24)
- Animation or camera-pose tests fail post-extract → revert, STOP
- Sub-router doesn't register → URLs 404 → revert

## Output (Findings #45)

Required:
- N routes moved (likely 4 per CLAUDE.md routes index)
- routes_camera_poses.py LOC + crud.py LOC delta
- main.py registration line shown
- Tests preserved: test_animation.py baseline-equivalent
- USER TODO: `just dev` + create + reorder + delete a camera pose
- Linked: #34 (sibling 10-F), #24 (tangled-scope precondition)

## USER TODO template

1. `just dev` + `just frontend`; load any saved assembly
2. Add a camera pose via the camera-poses panel
3. Reorder the pose list; verify
4. Delete a pose
5. Confirm undo/redo + DevTools clean

## Do NOT

- Move other crud.py routes
- Change URLs
- Touch _PHASE_* / _LOOP_SKIP_* constants
- Commit / append to REFACTOR_AUDIT.md
