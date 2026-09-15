# Create PEG surfaces directly for NAMD

PEG coating is configured inline under **Simulations → NAMD → Hard surface →
PEG coating → Settings**. The toggle enables coating intent; its settings contain
patch shape and size, graft density, layout seed, representation, chain length,
end groups and optional asset references. **Review coating** checks the inputs in
place. Turning the coating off retains its values. No popup or separately named
surface save is required.

Use the workspace **Setup preset** dropdown above Benchmark to reuse the whole
NAMD sidebar configuration, including PEG, across designs. See
[setup presets](namd_setup_presets.md) for capture scope, overwrite/delete behavior,
and design-specific selection handling.

Valid coating edits persist in `metadata.namd_peg_coating` with an explicit enabled
flag and `spec`; visibility is recorded in `metadata.namd_peg_visible`. Legacy
coating records without the enabled flag remain readable. The scene still renders
surfaces only after explicit selection of a surface-enabled job. Review does not
build PEG conformations or alter DNA topology.

## Legacy surface-library persistence and API

Existing workspace-level drafts live in `workspace/namd_surfaces/<id>.json`, independently
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

Saving through the UI attaches the editable record to `metadata.namd_peg_coating`
in the current document; `metadata.namd_peg_visible` stores visibility. These fields
survive save/reload. This document attachment is setup/display intent: incorporating
the coating into the normal NAMD molecular job package remains unimplemented. It does not create or start a simulation. The outstanding
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

## Unified-card verification (2026-09-13)

The card contains Add/Edit/Remove PEG coating and View PEG, plus Add surface charge.
Salt mode, NaCl, magnesium and temperature are never supplied by the surface card.
Those choices remain in the job wizard; unsupported charged-wall electrolyte choices
are rejected by the existing API instead of silently being changed. A real browser
job-creation test preserves custom NaCl at 175 mM and magnesium at 0 mM.

Validation: 6,285 frontend tests and six dedicated browser checks passed; two focused
backend tests verify persistent attachment/removal and explicit salt preservation.
The backend selector ran FAST: 8,305 passed, 11 pre-existing missing-fixture failures,
109 skipped. Main.js increased by two lines: preview-module import and initialization;
the existing PEG initializer only gains its store dependency.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

The broader smoke run passed 22 tests and failed one assembly-exit console check because mrDNA job reconciliation raised `FileNotFoundError` while replacing a shared temporary job JSON file (HTTP 500). Repository lint still reports the unrelated unused `seq` in `routes_oxdna.py` and unused `Path` import in `test_oxdna_peg.py`; targeted lint for the changed backend persistence files passes. `git diff --check` passes. Browser teardown removed the test documents, coating drafts, and test job.

## Surface selection and settings sections (2026-09-13)

The NAMD card has five matching toggle rows: **Hard surface on**, **Add surface
charge**, **Graphene nanopore**, **Two-electrode system**, and **PEG coating**.
The two-electrode setup is mutually exclusive with the single-support modes; see
[two-electrode scope and barriers](namd_two_electrodes.md). Each has a collapsed **Settings** disclosure.
Hard surface owns placement, clearances, margin and representation; charge owns
density and reservoir depth; nanopore owns pore/material/layer fields; PEG owns
coating layout, representation, chain length and chemistry notes.
Charge and open nanopore are mutually exclusive because the implemented charge
model is a closed wall. Enabling either enables the support; disabling the support
turns charge, nanopore and PEG off. Salt and temperature remain exclusively wizard inputs.

The scene renders only after an explicit job-row selection with a saved surface.
Automatic job selection, document loading and setup edits cannot turn it on.
Deselecting, changing documents or selecting a non-surface job clears surface
visibility in preview, solvent/ion-path and native PEG channels. Cached trajectory
coordinates remain cached. Preview dimensions come from the selected job, not
editable setup inputs. Native PEG review must match the selected job ID, including
after an asynchronous load. No topology or simulation coordinates are modified.

Verification: 6,387 frontend tests passed; all seven dedicated browser checks and
all 23 smoke checks passed. Browser checks cover initial/draft invisibility,
explicit job-row selection and deselection, setup/snapshot independence, collapsed
settings, parameter containment, consistent styles, overflow, and wizard salt.
Screenshots of each expanded section were reviewed; empty-coating Remove button
visibility and truncated dropdown labels were corrected. FAST backend: 8,310
passed, nine missing BigO/smallO fixture failures, 110 skipped, no timing violations.
Repository lint retains two pre-existing unused-symbol errors. The mrDNA job-file
race still appears in backend logs, although the smoke checks passed. No new lines
were added to main.js for this change (the earlier PEG wiring remains +2 lines).
The prepared master merge is applied as 1d893ea6; local work is restored and its
pre-merge stash retained as a backup. No push was performed.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

Latest inline PEG and workspace preset workflow and verification: [NAMD setup presets](namd_setup_presets.md).
