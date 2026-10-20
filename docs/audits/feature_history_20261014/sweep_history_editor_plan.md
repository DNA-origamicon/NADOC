# Sweep history editor — FH-22

**User priority — October 18, 2026:** Complete Bend, Twist, Sweep and Extrude
before moving to other areas. Completion includes their applicable creation and
history-edit controls, isolated preview/Cancel/Apply, dependency and downstream
replay correctness, undo/redo/save/reload, and desktop/latency qualification under
the existing fixed exits. FH-21/FH-22 implementation completion alone does not
establish fully qualified Extrude/Sweep tools; their FH-27 acceptance remains.
Select each bounded successor from the remaining work for these four tools.
Shared infrastructure work must identify a demonstrated blocker to one of these
tool requirements and stay narrowly bounded. Other areas remain deferred;
simulation relevance remains saved-source freshness only. Preserve scientific
authorization and rollout qualification; do not weaken assertions or fixed exits.
S54 downstream routing is complete; the current handoff owns remaining Sweep creation/control/resource acceptance.

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
that suffix and reports missing or invalid dependencies. Desktop history editing
no longer falls back to the legacy recovery editor; unsupported rows refuse explicitly.

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
representative performance acceptance require verified machine-local scratch
under the current artifact policy. The old universal Archive prerequisite is
superseded; missing qualification remains acceptance debt. Client and backend rollout remain disabled until
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

## S48 — Bend with downstream attached Sweep, October 18

S48 qualifies one tiny ordinary Bend→attached Sweep chain through the existing history owner. Exact Cancel/redo preservation, independent native replay, downstream identity/parameter preservation, changed Sweep geometry and app save/undo/redo/reload pass. Final focused host test:1 passed; harness boundary:10 passed; strengthened browser case:1 passed with clean console. No production behavior changed. Sealed startup and full tool/resource acceptance remain open. S49 Twist→Sweep replay qualification is the sole unstarted successor. No gate or milestone advanced.

See [S48 evidence](bend_sweep_replay_20261018.md). This verifies editing Bend with
a later Sweep, not the complete Sweep editor or sealed-host acceptance. S49's
exact bounded contract is in the current handoff. Fixed exits remain unchanged.

## S49 — Twist with downstream attached Sweep, October 18

S49 qualifies the tiny ordinary Twist→attached Sweep chain and preserves Bend coverage. Independent native replay, exact Cancel/source/history/redo, stable downstream inputs/identities, full geometry and desktop Apply/save/undo/redo/reload pass. Twist changes the inherited radial frame while preserving this straight fixture's attachment origin and axial direction. Focused host2 passed, harness11 passed, browser2 passed with clean consoles. No production behavior changed. S50 attached Sweep history-editor desktop qualification is the sole unstarted successor. No gate or milestone advanced.

See [S49 evidence](twist_sweep_replay_20261018.md). Tiny ordinary chains do not
qualify all controls, sealed-host or resource acceptance. The current handoff
selects S50 for the Sweep editor itself; fixed exits remain unchanged.

## S50 — Attached Sweep editor desktop workflow, October 18

S50 qualifies one tiny ordinary attached Sweep history-editor workflow through a later Extrude. Numeric path edit/add/remove, automatic/explicit orientation, Previous/Next, preview toggles, exact Cancel, Apply and undo/redo/save/reopen pass with native geometry/proof and clean console. Native oracle1 passed, harness12 passed, focused frontend23 passed, final browser1 passed. Test-only paired gates restore; production behavior is unchanged. S51 Bundle Extrude history editing through Bend→Sweep is the sole unstarted successor. No gate or milestone advanced.

See [S50 evidence](sweep_editor_desktop_20261018.md). MV-51 remains open for
other source/control variants, canvas gestures, failures and resource acceptance.
S51 targets the earlier Bundle Extrude row; the handoff owns its exact bound.

## S53 — Sweep source-mode desktop matrix, October 18

S53 qualifies independent, attached-start and sticky-detached Sweep history editing with later Extrude. Native fixture4 and source-contract40 passed, harness22 passed, focused frontend23 passed; final three-case browser matrix passed with clean consoles. Prefix source inventory, ligation draft controls, fixed-origin orientation, saved source/detach identity, exact Cancel, full native geometry, Apply and persistence are covered. Test synchronization corrections required no production change. S54 Sweep downstream-nick success/refusal desktop workflow is the sole unstarted successor. No milestone advanced.

See [S53 evidence](sweep_source_matrix_20261018.md). Source inventory/plane state and ligation toggles are exercised; source switching, alternate planes/strands and canvas picking are not claimed. MV-51 and fixed FH-27 remain open. S54 is defined only in the current handoff and is unstarted.

## S54 completion — Downstream routing and dependency guards, October 19

Four browser cases pass: nick regeneration, reported all-target removal, atomic partial-target refusal, and dependency-dialog cancellation/rollback editing guards. Successful routing edits pass native cold replay, undo/redo/save/reopen. Receipt recovery preserves removal notice; failures identify routing children. Backend84 and focused frontend132 passed across updated preview/Sweep checks. Ordinary Sweep already shares the preview-session host. Production gates remain OFF pending remaining acceptance; no milestone advanced.

Large-part check: stale frontend16-cell/1024-bp caps fixed to existing backend bounds. Native18-helix Sweep plus downstream nick now edits/Applies/Cancels; focused frontend39 passed. Browser p95 1360.2 ms, Apply2435 ms, Cancel35 ms; GPU raster excluded. Strict1000 ms preview assertion fails, so C8 remains open and gate OFF. Scratch cleanup verified; no old designs migrated.

## Desktop cleanup and dependency inspection — October 19

Removed Sweep's legacy history-edit branch; disabled/unsupported history refuses rather than opening creation controls. Focused frontend36 passed. Existing attached Sweep Apply/downstream Extrude persistence and rollback/dependency browser cases pass after removal. Added revision-bound parent/child inspection from replay contracts, explicitly labeled conservative; routing groups aggregate child relationships. Backend5, focused UI13 and real Extrude/routing dependency browser1 passed. Full frontend9346 passed,1 skipped. No gate or milestone advanced; C8 gap remains. Next C4 step is transient attempted-edit error/blocked row feedback, preserving atomic refusal and saved-design validity.

C4 UI follow-up: first failing feature now shows “Edit failed”; the remaining unregenerated suffix shows “Blocked” for the attempted edit. Refusal is atomic; saved design data is unchanged, and UI feedback clears on retry/Cancel/reset/source replacement. Shared focused frontend63 and the real Sweep routing-refusal case pass. No gate credit or change to routing-removal semantics.

## Creation and rollback acceptance — October 19

Three isolated browser workflows pass: independent XZ creation, attached-end creation through Tools, and actual end-context creation. Each covers exact Cancel, native history edit, cold proof, undo/redo/save/reopen. Review found creation could start at a historical cursor: UI and backend now refuse explicitly before building. Backend26 and focused frontend31 pass; browser rollback refusal preserves state and emits no mutation. C8 preview gap remains, gate OFF. No new preview host or geometry semantics.

Full frontend9358 passed,1 skipped; required backend regression is tracked in the current handoff. Third focus review selects profiling/fixing the existing Sweep evaluation/display path to address C8 and enable history, without another qualification matrix or host.

## Bounded C8 investigation — October 19

Reuse of validated native display panes removes a redundant finite-value traversal; native coordinate, slab registration, inventory and payload bounds remain enforced. New nonfinite coordinate/metadata refusal tests pass; focused backend13 passed. Committed field changes now flush queued previews immediately while typing/dragging retains debounce; focused panel25 passed. Real18-helix p95 remains1224.8 ms, Apply2427 ms, Cancel38 ms (GPU raster excluded), so the strict1000 ms limit still fails and gate remains OFF. CPU profiles identify existing native evaluation/projection and browser construction costs; no molecular algorithm or new host introduced. Further micro-optimization is deferred while closing Extrude creation/rollback acceptance. Required broad regressions follow this change batch.

Exact transport reuse follow-up: last tangent-pair byte key reuses only the existing rotation result; every matrix product is retained. Straight/curved/attached uncached-reference parity is bit-exact; Sweep39 passed. Existing GC pause now includes response encoding; route14 passed including exception restoration. Removed duplicate initial candidate layer construction; focused frontend20 passed. Real small C8 passes (preview p9563.4 ms, Apply179 ms, Cancel47 ms); large still fails (1192.1/2375/37 ms). Strict1000 ms preview limit and OFF gates retained. Scratch3xh4vd1d independently absent. Broad regression pending; no geometry oracle or legacy manifests changed.

Follow-up batch: projection reuses its fully validated coordinate list for packing (66 backend checks, including eight exact standalone-wire parity cases); renderer omits connection indexing only when no authored crossover/ligation exists (41 frontend checks). Small C8 p9568.5 ms/Apply186 ms/Cancel46 ms passes; large first905.7 ms but p951081.4 ms/Apply2367 ms/Cancel40 ms still fails. All samples remain counted, strict1000 ms unchanged, gates OFF; scratchb3nt7kfp independently absent. Prior batch frontend9359 pass/1skip; backend19030 pass/64 known failures/19skip. Three real-worker slow parametrizations classified as headless; collection confirms coverage. Final batch: frontend9359 pass/1skip; backend19032 pass/67 failures/19skip. Worker recheck30 pass; comparison recheck30 pass/1 expiry-boundary failure in unchanged lifetime code. The64 documented baseline failures remain; no numerical manifests/goldens changed. Goal paused per user away-policy pending Sweep latency-budget decision.

## Guide-only Sweep preview — user correction October 19, 2026
The edited Sweep displays axes, nodes and cross-sections, never nucleotide geometry; its prefix is static context. Apply retains full native rebuild/validation. Both production gates are ON; the harness now verifies them without overriding them.
| Core item | Evidence |
|---|---|
| C1 | Independent, attached-end and end-context creation, exact Cancel and one Apply pass in app. |
| C2 | Native guide renderer, saved controls, independent/start/end/detached history editing pass; fixed prefix is never rebuilt during updates. |
| C3 | Full Apply matches independent cold replay, including downstream Extrude and nick routing. |
| C4 | Atomic earliest-child refusal and blocked feedback remain; partial routing targets refuse, all-target removal is reported. |
| C5 | Upstream deletion lists dependents before commit; cancellation preserves exact state. |
| C6 | One-step undo/redo and save/reopen pass across source modes. |
| C7 | Mid-history creation/editing explicitly refuse. |
| C8 | Corrected completion observer waits for numeric extent and enabled Apply, with12 completed requests/12 samples: small p9541.5ms/Apply186ms/Cancel38ms; large173ms/2244ms/54ms. GPU raster excluded. |
| C9 | Obsolete mutating history branch remains removed; full Sweep nucleotide preview is unreachable. |
Focused DTO15/routes14/frontend47+26 pass; production browser16 pass, corrected latency2 pass and wider visual/history check1 pass. Scratch roots independently absent. Full frontend9360 pass/1skip; backend19030 pass/71 failures/19skip. Six obsolete expectations corrected (wire4/harness32 pass); routing capture timeout passed whole-file recheck9;64 baseline failures remain. Main.js delta0. Earlier latency measurements used the wrong preview requirement and are superseded.

### History ordering follow-on — October19
- Whole-row Move uses existing evaluation jobs, native proposed-order replay, source-bound commit and undo.
- Shared resources do not prohibit ordering; valid moves may change geometry. Initial bundle remains first.
- Source proof and final cold replay validate each command's structure; missing producers name the failing child.
- Fine Routing child identity/order stays intact; existing all-target-removal parameter-edit semantics unchanged.
- Focused backend26/UI5 pass; four app workflows cover move/undo/redo/save/reopen and exact refusal.
- Prior full frontend9365 pass/1skip and smoke23 retained; current UI change is explanatory text only.
- Backend FAST:19061 pass/64 baseline failures/19skip; FULL deferred. Final379s, zero per-test violators.
- Three measured background-worker parametrizations classified headless; all four classified cases collect.
- No molecular formulas/constants, manifests, goldens, legacy migration or new transaction host. Main.js delta0.
- User clarification: interactive host now calls native guide planning without building/validating candidate topology.
- Apply retains complete native command validation and independent full-history regeneration.
- Focused43 and session16 pass; guides equal native planner output for independent, attached and posed sources.
- App3 pass: attached lifecycle/persistence and latency p95 small36ms/large88ms (GPU raster excluded); scratch ydmfjcfe absent.
- Sweep backend FAST19063 pass/65 failures/19skip,389s, no individual timing violators;64 baseline plus generated-proof timeout (whole-file recheck4 pass). FULL deferred.

### Persistent suppression — October19
- Whole-row Suppress/Unsuppress uses existing jobs, atomic commit and undo; definitions/IDs and Fine Routing child order remain saved.
- Disabled definitions remain fingerprinted no-op recipe steps; capture, prefix reuse and rollback preserve stage positions. Repair draft fingerprints bind suppression too.
- Missing actual producers refuse atomically with failing-feature attribution; no child auto-removal on suppression.
- Focused backend20/repair-capture11/UI7 pass; exact restoration covers Bend/Twist/Sweep/Extrude, persistence, rollback, edit-preview prefix and reorder.
- App6 pass: four tool suppression lifecycles, Move and atomic missing-producer refusal; scratch6ehu2rrw absent. Full frontend779 files/9367 pass/1skip; smoke23 pass, scratch1p2r9ls4 absent; backend results superseded by stopping-point handoff.
- No formulas/constants, manifests, goldens or legacy compatibility work.

### Source repair and stopping point — October19
- Existing repair panel discovers Sweep/Extrude source references from the actual prefix and evaluates the complete proposed history. Derived continuation bindings use the existing native binder.
- Repeated proposals execute every tracking callback; suppression remains explicit through repair. Focused geometry12, existing selection62/repair58 pass.
- ISSUE-146 restores the hidden part launcher by separating it from the configuration-only toolbar. Two real app workflows pass selection/Apply/undo/redo/reopen/cold proof; scratch w_0rosal absent.
- Current archive schema retains suppression; archive capture45/routes28 and exact capture accounting31 pass. No simulation or old-manifest migration.
- User requested a local commit and stopping point. Final regression counts and remaining Bend/Twist C8 debt are in the handoff; no added milestone credit.
- Final FAST19078 pass/83fail/19skip:64 baseline plus19 old-schema expectations; zero per-test timing violations. Full frontend9367 pass/1skip; broad slow groups remain deferred.
