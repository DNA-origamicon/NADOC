# cadnano → local oxDNA: post-import control clicks

Measured using the real-browser guide recipe on November 15, 2026, with a
NADOC-authored 84 bp honeycomb 6HB exported to cadnano. This measurement is
separate from the user guide.

**16 control clicks from successful import to starting local production:**
15 buttons/menu items plus one radio control for inspecting the relaxed model.
If “after import” means the imported part has already been saved, the same
walkthrough takes **15** subsequent control clicks.

| # | Control |
|---:|---|
| 1 | Save imported part |
| 2 | Tools → Sequencing → Assign Scaffold Sequence |
| 3 | Apply (default M13mp18 reference, single scaffold) |
| 4 | Tools → Sequencing → Assign Staple Sequences |
| 5 | Simulations sidebar |
| 6 | oxDNA engine |
| 7 | + New job — relaxation |
| 8 | Next — Parameters & options |
| 9 | Next — Full configuration |
| 10 | Create job — relaxation |
| 11 | Run — relaxation |
| 12 | OxDNA display — inspect relaxed positions |
| 13 | + New job — Production mode opens automatically |
| 14 | Next — Summary |
| 15 | Create job — production |
| 16 | Run — production |

## Measurement boundary

Start: the cadnano import request has succeeded, before the Save dialog is
confirmed. End: the production Run button is pressed. The imported file has
one scaffold and requires scaffold/staple sequence assignment because cadnano
v2 does not preserve the sequences assigned in the NADOC source.

The recipe records trusted primary `pointerdown` events on controls. Keyboard
activations, synthetic clicks and screenshot numbering do not count. The exact
ordered control IDs/labels are printed as `POST_IMPORT_BUTTON_CLICKS` by
`frontend/guides/cadnano-local-oxdna.spec.js` during regeneration.

This is a **control-click count for the demonstrated route**, not total
interaction effort or the theoretical minimum. It excludes source-model
construction/export, import-menu/file-picker actions, import confirmation,
filename text entry/focus, menu hovers, camera orbit/pan/zoom, F-key framing,
scrolling and simulation waiting time. No shortcuts replace the listed actions.
The optional physical-display inspection contributes one click; omitting that
inspection from this same route gives 15 clicks (14 after Save).

Assumptions: oxDNA is already installed locally with CUDA support, the fresh
profile defaults to Local execution, Visualizations is already expanded,
default force-field/temperature/salt/stage parameters are suitable for the
example, one completed relaxation is selected, and no concurrent-job or disk
warning requires confirmation. Setup, parameter changes, multiple scaffolds,
failures/retries requiring user intervention, and extra dialogs add actions.

## Evidence and limits

The guide directory contains `simulation-verification.json` with the completed
relaxation stages and health samples, production parameters and a nonzero-time
native production frame. `verification.json` independently audits both source
and imported parts and checks the source export against the imported bytes.
Production is stopped during capture cleanup; this is verification of launch
and native output, not a converged production dataset.

The repository's older `6hb_cadnano_native_test1.json` failed default CUDA MD
relaxation twice after all automatic retries with a cell-capacity error. Those
attempts are recorded in `docs/guides/UX_LEDGER.md` (GUIDE-UX-020) and are not
counted as a successful workflow. An intermediate eight-helix specimen also
completed the path; the final demonstration uses the user's requested 84 bp 6HB.

No competing workflow has been measured here. A comparison should use the same
starting prerequisites, sequence-assignment requirements, endpoint, inspection
steps and definition of a click; this count alone does not establish a speedup.
