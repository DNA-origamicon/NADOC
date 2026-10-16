# Sweep history editor — FH-22

October 16, 2026. The fixed exit is input-based isolated preview,
recovery-independent Apply/Cancel, and downstream rebuild. Work starts at
19/38 milestones complete. U17 closes the fixed implementation exit at 20/38,
with no estimate change. Desktop/latency acceptance remains FH-27.

## Complete control and lifecycle boundary

| Area | Required behavior |
|---|---|
| Footprint | Historical-prefix source helix and start/end or independent bundle; plane; exact cells; scaffold/staples/both; adjacent ligation. |
| Path | Ordered XYZ controls, add/remove, per-point automatic or tilt/twist orientation, native point picking and translation/rotation handles. |
| Attachment | Native fixed attached-origin orientation and explicit/sticky detachment semantics; saved source identity must not silently become a new bundle. |
| Navigation | Previous/Next retains inputs; native length/base-pair and feasibility feedback; matching evaluated inputs precede Apply. |
| Ownership | Exact part/session/revision/feature identity, latest cursor, cancellation, expiration, supersession, same-ID reset, protected-loadout and policy checks. |
| Publication | Independently prove the full source, rebuild selected and later native commands, validate, publish once, one undo, save/reload/cold proof. Failed Apply retains the source and draft. |

The existing snapshot-based Sweep editor intentionally proportionally relocates
routing addresses and rebases attachments. Native history uses the saved command
inputs. Its preview must show the selected feature stage; it cannot claim to
have validated the suffix or silently rewrite later routing inputs. Apply runs
that suffix and reports missing or invalid dependencies. The legacy recovery
editor remains for its actual callers and existing compatibility contracts.

## Shared implementation

Use the existing preview lease catalog, work slot, sequencing, cancellation,
publication receipts and source-bound frontend controller. The host admits two
closed internal families, deformation and Sweep, selected by separate HTTP
routes. Every operation, receipt lookup and cancellation tombstone retains that
family binding. No caller supplies an executor or publication callback.

The pure Sweep adapter reconstructs and retains one owned pre-feature prefix,
normalizes complete native inputs, and invokes the unchanged native command
pipeline for local candidates. `sweep_id`, proof metadata and transport receipts
remain protected. A separate bounded Sweep display contract carries native path
manipulation metadata, prefix controls and independently owned DNA components.
The picker and manipulators use a private display layer and that prefix context;
they never install preview geometry or modify the active design.

Prepare executes the prefix once. Input changes evaluate only the selected Sweep.
Apply independently proves and regenerates the complete source once. Existing
private preview limits remain explicit: 128 commands, 16 helices, 1,024 sites,
bounded path work and response transport, a 60-second lease and cooperative
native deadlines. These limits do not establish interactive latency or acceptance
for representative larger designs. FH-27 retains that qualification work.

## Acceptance and rollout

Pin recovery independence and native geometry parity with tiny explicit-root
fixtures. Exercise attached/detached sources, changing source/footprint/path/
orientation, missing inputs and downstream nick dependencies, stable identities,
undo/redo and cold reload. Reuse existing shared-host race tests and add only
Sweep-specific family/transport/lifecycle cases. Check actual backend packets
against the frontend validator, not only separately maintained mock packets.

Retain the legacy Sweep tests as compatibility evidence. No molecular builder,
phase constant, numerical manifest or golden changes are proposed. Browser and
representative performance acceptance require the unavailable Archive mount;
record this debt explicitly. Client and backend rollout remain disabled until
qualification. Assemblies and machine-specific VR remain deferred.

## CAD evidence and the NADOC decision

[SOLIDWORKS PropertyManager controls](https://help.solidworks.com/2022/english/SolidWorks/sldworks/r_pm_overview.htm)
separate Preview, accepting a feature, and cancelling it.
[Onshape Sweep](https://cad.onshape.com/help/Content/PartStudio/sweep.htm)
exposes profile, path and orientation inputs and reports missing required
selections. Its [feature list documentation](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)
describes regeneration failures and missing-selection indicators. These are
workflow precedents, not evidence about proprietary transaction internals.

NADOC's implementation decision is to show a clearly labelled temporary feature
stage, then prove the source and rebuild the suffix at Apply. The sources do not
justify changing DNA spline, feasibility, loop/skip or routing-address formulas.
The owned editor therefore retains native fixed-address inputs; the legacy
snapshot editor's proportional address rebasing remains an explicit separate
compatibility behavior until its callers can be retired.

## Implemented boundary and validation

The implementation reuses the shared lease host, strict bounded HTTP reader,
native command pipeline, DNA display projection and frontend lifecycle. A closed
family selector binds Sweep separately from deformation through cancellation,
status and publication. There is no second job catalog or general executor hook.
The actual app mounts the disabled Sweep router; client and host flags remain
false. Ordinary creation and legacy recovery retain their callers and tests.

Native input tests compare complete geometry for free, attached start/end,
posed and organized sources. Apply tests poison/evict recovery, retain exact
later nick inputs, compare independently rebuilt geometry, and verify undo,
reload and cold proof. Missing single-nick helices now receive typed reference
diagnostics plus the failing feature ID. Existing untyped error mapping remains.
Publication rechecks deadline/source/lease after preserving document state.

The actual Python DTOs are validated by the JavaScript consumer over stdin;
fixture agreement alone is not the contract test. Actual panel, feature-log,
picker and TransformControls cases cover full controls and source context,
cancelled openings, unknown Apply outcomes, private layers and raycasters,
hidden legacy commit refusal and newer camera/view ownership. The renderer and
picker restore only state owned by the closing editor.

The 554 distinct backend checks pass across 24 files. The final frontend suite passed 8,918 tests with one existing skip
across 753 files (323.55 seconds), as recorded in [U17 evidence](validation_sweep_history_editor.json). Two partial
full frontend runs were deliberately stopped for concrete isolation corrections;
they are not claimed as full passes. No native algorithms, numerical manifests,
goldens or `main.js` changed. Desktop/latency remains FH-27/MV-51.
