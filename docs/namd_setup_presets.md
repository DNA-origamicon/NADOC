# NAMD setup presets

The **Setup preset** dropdown sits immediately above Benchmark in the NAMD tab.
Use **Create** to name and save the current settings. Selecting a preset restores
its settings. **Overwrite** replaces the selected preset with the current values;
**Delete** removes the saved preset and leaves the current setup unchanged.
Changes after applying a preset are labelled “Modified from …”. They do not alter
the saved preset until Overwrite is clicked.

Preset definitions are stored separately from every `.nadoc` file in
`workspace/namd_setup_presets/`. Creating, overwriting or deleting a preset does
not edit a document. Applying one can persist ordinary document settings (such
as PEG coating intent), but never embeds the preset library. All parts using the
same backend workspace see the same library; separate computers/workspaces need
explicit library synchronization.

Presets are workspace-wide, so the same dropdown works across different designs
and browser reloads. Select explicitly for each design; opening a document does
not automatically apply a preset. Saved records contain exact values rather than
references to mutable defaults. Overwrites increment the revision and reject stale
updates; reload the page/list if another client has changed a record.

## Covered settings

All identified configuration inputs in the cards below the dropdown are captured:
cluster execution-target choices, anchors and hold/stiffness settings, electric
field and conversion inputs, hard-surface geometry, charge and reservoir depth,
graphene pore/layer settings, two-electrode intent, PEG coating, visualization preferences, analysis
parameters, occupancy scope, and trajectory-export settings. Benchmark has actions
and results but no editable configuration fields to capture.

The preset does not press buttons, connect to a cluster, start a benchmark/run,
activate a live/trajectory visualization, select a job or restore its playback
position. Credentials are excluded. Box sizing, water margin, salt and surface-control temperature in **Box and solvent**
are included in sidebar presets. The job wizard uses this shared preparation state;
protocol settings remain in the wizard. Ordinary DNA stage temperatures remain protocol-controlled. Existing job snapshots are unchanged.

Structure anchors, surface anchors and occupancy scope retain their exact
references when applied to the same design ID. Across designs those selections
are cleared and a message asks for reselection, since identical IDs are not a
physical correspondence between two DNA structures. Their scalar configuration
and all other settings still apply. No topology or molecular coordinates change.

## Inline PEG coating

PEG has its own **PEG coating** toggle and collapsible **Settings** within Hard
surface. The section contains patch shape/size, graft density, layout seed,
representation, chemical repeat units or statistical segments, end groups and
optional asset references. Both representation parameter sets are retained; no
conversion is inferred. **Review coating** validates the parameters inline.

Valid edits persist as coating intent in the current document. Disabling the
coating retains its values. No new surface-library record or popup is needed;
existing legacy library files are left intact. The preset captures the complete
coating settings and View PEG preference. A coating remains an editable intent,
not a built atomistic package: arbitrary coating incorporation into NAMD jobs is
still a separate preparation gap. Single-surface and PEG rendering still require explicit
selection of a surface-enabled job. The two-electrode toggle additionally displays
a schematic setup preview with external charge markers, independent of jobs.

## Persistence/API

Records live in `workspace/namd_setup_presets/<uuid>.json`, with `name`, `revision`,
`updated_at`, and a `settings` snapshot using `nadoc.namd_setup.v1`. Writes use an
atomic temporary-file replacement. They require neither DNA nor a flattened
assembly simulation projection.

| API | Operation |
| --- | --- |
| `GET /api/md/setup-presets` | List workspace presets |
| `POST /api/md/setup-presets` | Create `{name, settings}` |
| `PUT /api/md/setup-presets/{id}` | Overwrite `{name, settings, revision}` |
| `DELETE /api/md/setup-presets/{id}?revision=N` | Delete a known revision |

Duplicate names return 409; stale overwrites/deletions also return 409. Invalid
names, IDs, schemas or oversized records return 422. Deleting a preset never
removes a document, job or legacy surface-library record.

## Verification (2026-09-13)

All 6,392 frontend tests passed. Seven focused Playwright checks passed, covering
inline PEG editing and review, preset creation and application across designs,
overwrite and deletion, section containment/style, job-gated visibility and wizard
salt. Screenshots of the preset controls and expanded PEG section were inspected.
All 23 smoke checks also passed; the existing mrDNA job-file rename race still
appears in backend logs. The two new API tests passed, including persistence, stale revisions, duplicate
names, invalid inputs and deletion. Test-created presets and documents were
removed by failure-safe cleanup and their absence verified.

`just test-smart` selected FAST: 8,312 passed, 110 skipped, nine existing failures
from missing BigO/smallO workspace fixtures; no timing violations. Repository lint
retains the existing unused `seq` in `routes_oxdna.py` and `Path` import in
`test_oxdna_peg.py`; the new API and tests pass targeted lint. `git diff --check`
passes. New behavior lives in dedicated modules; main.js adds only an import and
initializer (+3 lines including spacing for this task). No native simulations ran.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
