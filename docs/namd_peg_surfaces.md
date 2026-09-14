# Create PEG surfaces directly for NAMD

Open **File → NAMD PEG Surfaces…**, including from an empty workspace. When a
DNA part or assembly is open, the same setup is available under **Dynamics → NAMD
→ PEG surfaces → New PEG surface…**. No oxDNA import or source job is needed.

## Workflow

1. Name the surface and select a hard barrier or graphene support.
2. Set the allowed-side normal, absolute plane position, square/circular patch size,
   graft density and layout seed. Graphene supports an optional pore and layer count.
3. Select atomistic or coarse-grained PEG. Enter chemical repeat units for atomistic
   PEG, or statistical segments for coarse-grained PEG. These are separate inputs;
   changing the selection does not convert one model into the other.
4. Record the grafted/free end groups and optional topology/force-field references.
   References are draft notes; entering a path does not validate or load an asset.
5. **Review surface** displays the requested chain count, coating area, a reproducible
   top-view graft sample and the outstanding preparation requirements.
6. **Create surface draft** saves the definition. Reopen it through **Open saved
   surface** in the dialog or the NAMD sidebar library; use **Save changes** to update
   the same draft. Closing an edited dialog retains its unsaved inputs for continuing.

The preview shows at most 256 sites. The requested chain count is graftable patch
area × density, rounded to the nearest integer (halves round up). Graphene pores
are excluded from both the area and preview sites. Circle layouts use uniform
annulus sampling; square layouts reject sites inside the pore. The preview is
schematic and does not represent built PEG conformations or atomistic placement.

## Persistence and API

Workspace-level drafts live in `workspace/namd_surfaces/<id>.json`, independently
of DNA documents, assemblies and simulation jobs. The stored record includes the
surface/coating specification, the shared plane frame, review data, a stable ID and
update timestamp. Writes replace the record atomically. Editing does not create a
new ID. Multiple documents can open these shared surface definitions; saving edits
currently uses last-write-wins semantics.

| Request | Behavior |
| --- | --- |
| `POST /api/md/peg-surfaces/review` | Validate and preview; no files written |
| `POST /api/md/peg-surfaces` | Create a surface draft |
| `GET /api/md/peg-surfaces` | List saved surfaces and recompute readiness |
| `PUT /api/md/peg-surfaces/{id}` | Update an existing draft |

All responses identify `engine: NAMD`, `origin: direct`, `status: draft` and
`launch_ready: false`. Invalid names, dimensions, counts and geometry combinations
are rejected before persistence. No engine process, molecular backmapper or job
preparation is invoked. API calls bypass DNA/assembly simulation-snapshot creation
because the surface library is independent of a particular molecular system.

## Remaining preparation barriers

An isolated [atomistic PEG wall qualification](namd_peg_wall_validation.md) now
provides pinned methyl-capped PEG assets, native harmonic point tethers and a
GPU-resident-compatible repulsive-wall candidate. It has its own guarded experiment
runner and does not change the draft API's `launch_ready: false` contract.

Saving a surface draft does **not** attach it to an existing DNA system or to the
normal NAMD job wizard. It does not create or start a simulation. The outstanding
work is explicit in the review:

- Select and validate PEG topology/coordinates and force-field assets.
- Specify graft chemistry, end groups and DNA/PEG/surface cross interactions.
- Build molecular chain conformations, attachment mappings and solvent.
- Select the NAMD wall-force implementation for hard barriers, or validate the
  selected graphene/PEG model.
- Validate coarse-grained/atomistic hybrid interactions when using coarse-grained PEG.
- Integrate the complete surface package with job preparation and run the guarded
  molecular/engine validation before enabling launch.

This keeps direct surface design usable while engine preparation remains incomplete.
It reuses [shared surface geometry](surface_transforms.md) and is independent of
[oxDNA checkpoint seeding](peg_namd_seed_plan.md).

## Implementation and validation

Pure draft/layout logic: `backend/core/namd_peg_surface.py`. Persistence API:
`backend/api/routes_namd_peg_surfaces.py`. UI model and dialog:
`frontend/src/ui/namd_peg_surface_model.js` and `namd_peg_surfaces.js`.
The composition root gains one import and one initialization (`main.js` LOC delta: +2).

Focused coverage includes create/list/update, validation failures, immutable source
independence, pore exclusion, deterministic layout and readiness recomputation.
Frontend tests cover review/save, reopening the same ID, failed-review retry,
representation semantics, invalid raw numbers and unsaved-edit continuation.

Playwright exercised actual API persistence from a blank workspace: create, review,
save, reload, reopen and edit, plus an invalid layout. Form and review screens were
visually inspected and numeric colors checked against the sidebar palette. No
simulation-launch requests occurred. The test-created
`__e2e__namd-peg-direct*.json` files were removed by failure-safe teardown; no
surface test artifacts or Playwright output remained after the run. Session-cache
writes were disabled on the throwaway backend.

Validation results (2026-09-11):

- Focused backend: **15 passed**; focused frontend: **7 passed**; Playwright:
  **2 passed**. Coverage also includes failed-save retry, duplicate-save prevention,
  and invalid inactive representation fields.
- `just test-frontend`: **6262 passed**, but exits unsuccessfully because an existing
  `atom_surface_display.test.js` debounce fires after jsdom teardown
  (`ReferenceError: window is not defined`). No surface-display code was changed.
- `just test-smart` selected **FAST**: **8230 passed, 109 skipped, 11 failed**.
  Failures concern unavailable BigO/smallO workspace fixtures in assembly flattening
  and CanDo tests, outside this feature. Engine validation remains deferred:

  ```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  Ask the user to run `just test-session` (their terminal), then `just test-slow`.
  ```

- `just smoke` refused to run while a production oxDNA simulation was active;
  the guard was respected. The dedicated PEG browser checks above ran separately.
- Ruff passes for the new backend files. Repository-wide `just lint` still reports
  existing unused imports/variables in `tests/test_oxdna_peg.py` and
  `backend/api/routes_oxdna.py`. `git diff --check` passes.
