# P5 UI-2: private candidate comparison

2026-10-15. Design proposal only. No projection endpoint or renderer implemented;
no browser, native build or scientific check run. Assemblies remain deferred.

## Ownership and contract

`backend/api/part_evaluation_jobs.py` owns the only evaluated candidate, its
admitted operation, source identity, document session incarnation, policy generation,
creation/expiry time and cancellation. Its job/admission weak references point to
the mutable live source; captured worker input is released after evaluation and
is not a retained immutable comparison input. `inspect()` deliberately excludes
candidate bytes. A comparison must obtain a private read lease through this owner; it must
not read `_jobs` from a route, decode feature recovery, re-execute a command, create
a second candidate catalog, or turn a saved draft into a ready result.

Proposed `POST /design/features/evaluation/jobs/{id}/comparison` is explicit and
nonpublishing. Require current expected design/revision and draft ID/generation
for this UI. The job owner admits only a completed, uncommitted repair with a
matching private host admission and retained candidate; reject verify/selection,
cancelled, expired, stale-session/source/policy and busy-source states. Capture
owned references briefly, perform decoding/projection outside state/job locks,
then recheck the same guards and `_jobs[id] is admitted_job` before releasing any
response. Holding the shared work slot alone does not prevent cancellation,
expiry or catalog removal. Cancellation/expiry
may remove a catalog pointer while a private read is running; a lease must keep
its input alive only until that bounded read finishes, without reviving the job.
The first route remains compatibility-only; strict HTTP continues refusing it
until its read admission is separately reviewed.

Keep comparison transport separate from ordinary design responses. Suggested
envelope: `projection_version`, job/design/source-revision/draft-generation IDs,
`comparison_basis`, explicit representation, complete/omitted coverage, bounds,
and two display-only projections. Never send a `design` field or a candidate
publication permit. The view can consume this envelope; `_syncFromDesignResponse`,
normal `currentDesign`/`currentGeometry`, export and simulation cannot.

The first pane is **published authored geometry, not verified** unless an exact
matching proof actually exists. The second is **evaluated proposed geometry**.
Old failed definitions need not regenerate to display the published materialized
reference. Do not label that reference “last good” or use the recovery timeline
as a regenerated candidate. Physical/FEM/simulation positions are excluded from
both panes; make that comparison basis visible if the normal viewport uses them.

## Reuse and bounded work

Use the existing native geometry derivation (`core.design_geometry._geometry_for_helices`,
deformed axes and established placement helpers) through a cohesive pure display
adapter. Preserve current formulae, polarity and constants. Review the complete
allowed output closure before rendering: a successful DNA-only projection must
not silently omit proteins, particles or attached strands. Return an explicit
unsupported/over-budget diagnostic when complete comparison cannot be provided.
No atomistic/surface calculation is needed for initial coarse authored geometry.

Decode candidate transport with the same no-authoring-drift checks as commit,
without copying source presentation/recovery into it. Capture the published
source afresh under its state lock, checking the job's source/session/revision
identity before bounded copying. Do not derive geometry outside the lock from
the live weak-referenced model. A separately budgeted immutable source retained
during evaluation is an alternative only after explicit memory qualification.
Ordinary 25 ms/2 MB capture and existing job/result limits stay unchanged; any
extended capture needs the same reviewed family profile, never caller-selected
limits. Projection has a separate measured output/work allowance and uses the
existing single nonqueued work slot. Prefer one disposable read-only process using
the established spawn/shared-memory/terminate-and-join supervisor for native
derivation; this is a rendering task, not another numerical evaluation. Share
admission with other part work initially so preview cannot compete with an edit
or solver. Keep input/output in memory and release it on every error/timeout.

Do not select generous new limits without evidence. Qualify tiny DNA, uncoated
gold/QD, free protein and mixed supported models near the existing capture limit;
measure lock time, process/serialization time, bytes, renderer allocations and
concurrent lightweight requests. Refuse before rendering if output exceeds its
allowance. Polling readiness never starts projection work. An optional one-job
bounded cached projection can be considered only after measurements show repeat
Compare cost; no persistent geometry cache is necessary initially.

## Frontend surface

Reuse `ui/primitives/modal.js` and the lifecycle pattern of
`scene/t_junction_preview.js`: independent scene/camera/OrbitControls, bounded
pixel ratio, resize observer, keyboard controls, explicit frame lifecycle and
complete GPU/context disposal. Do not copy its T-junction geometry routines.

`initDesignRenderer` is not currently a disposable preview owner: it drops its
store unsubscribe handle, and `dispose()` removes roots without releasing all
GPU resources/timers. Use an explicitly owned static builder or harden that
lifecycle with focused tests before reuse. Shared helix geometry templates are
tagged `userData.shared`; disposal must preserve them, as the existing assembly
renderer does, rather than copying the live renderer's traversal wholesale. Existing
`protein_trace_renderer.js` already takes explicit atom arrays and a scene.
`nanoparticle_subsystem.js` mixes drawing with API edits/gizmos and must not be
installed wholesale; extract/reuse a pure particle display builder instead.
`assembly_visualization.js` demonstrates private display stores, but assembly
logic itself is outside this work. Do not use the normal renderer's external
geometry/simulation swap: it shares the main viewport and consumers.

Add a cohesive `part_repair_comparison` view/controller, invoked by the existing
repair controller's explicit Compare action. Keep the normal store and `main.js`
flat. Two panes share a camera frame/orbit and reset-to-fit action, with published
and proposed visibility controls and unambiguous labels. Optional overlay colors
may highlight positional/resource changes; stable IDs supply correspondence.
Never infer correspondence by nearest geometry. No screenshots, projections or
readiness go into browser storage. Closing the pane, changing doc/loadout/revision,
new proposal edits, cancellation, expiry or reset disposes all private resources.

This coarse comparison does **not** satisfy the molecular-geometry authorization
gate for numerical-engine upgrades. That requires the separate same-frame atom,
bond/ring/junction evidence and deltas; UI-1's evaluation/Apply block for those
proposals remains until that review exists.

## Completion gates

- Owner/transport tests: exact source/session/policy/draft generation; cancellation,
  expiry and close/reopen ABA during projection; no candidate publication or new
  feature row; fail-closed unsupported output families and byte/work bounds.
- Geometry oracle: compare coordinates/IDs against unchanged native display
  helpers for the same two inputs, including moved gold, free protein pose and a
  small DNA edit. No geometry lock or visual golden regeneration.
- UI tests: no normal store, simulation or export mutation; matching camera frame;
  old projection cannot appear after context change; deterministic disposal of
  observer, RAF, controls, buffers/materials, renderer and canvas.
- App exercise: explicit Compare before Apply, visible old/new difference, normal
  geometry/export unchanged, close/reopen, cancellation/expiry while displayed,
  then one Apply and ordinary refresh. Root's Archive/artifact inventory and
  cleanup gate apply. Until executed, report `NOT VERIFIED IN APP`.

## Established CAD behavior

Onshape separates a written change list from graphical comparison of workspace,
version and history states. This supports offering both compact changes and a
separately invoked visual comparison; it does not make a preview a validity
certificate. [Official Onshape Compare documentation](https://cad.onshape.com/help/Content/Document/compare.htm).
SOLIDWORKS compares reference and modified document geometry explicitly, with
distinct volume and face comparisons. NADOC needs molecular/topological display
correspondence instead of borrowing a solid-volume metric.
[Official SOLIDWORKS Compare utility](https://help.solidworks.com/2023/English/SolidWorks/sldworks/t_running_the_compare_utility.htm).
Job leases, bounded admission and private renderer ownership above are NADOC
architecture choices, not claims about those products' internal implementations.
