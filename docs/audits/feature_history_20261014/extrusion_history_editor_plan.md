# Ordinary extrusion history editor — U16 / FH-21

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
S54 and C4 downstream refusal feedback are implemented; the current handoff owns remaining acceptance.

October 16, 2026. Implementation contract and closure assessment; final validation
results belong in the checkpoint evidence. This document does not change the
[fixed milestone ledger](remaining_standard_part_checkpoints.md). Final software acceptance closes FH-21;
the ledger is **19/38 complete**, with desktop/performance acceptance still open.

## Complete ordinary input controls

The native editor supports these seven top-level snapshot families. Cells are
editable row/column pairs; `separate_fresh_extrusions` is an authored control,
not an immutable implementation detail.

| Family | Editable inputs |
|---|---|
| `bundle-create` | Cells, signed length, plane, name, strand filter, lattice type, adjacent ligation, separate fresh extrusions. |
| `extrude-segment` | Cells, signed length, plane, offset, strand filter, adjacent ligation, separate fresh extrusions. |
| `extrude-continuation` | Segment inputs plus source frame and extend-in-place. |
| `extrude-deformed-continuation` | Cells, signed length, plane, source helix, optional source bp, saved grid origin/axis/right/up, separate fresh extrusions. Source-bp mode derives the frame through existing native behavior; saved-frame mode exposes its vectors. |
| `extrude-frame` | Cells, signed length, plane, name, independent translation/quaternion or source-frame/legacy-frame mode, separate fresh extrusions. Source modes require identity local pose. |
| `circle-segment` | Cells and matching positive per-cell lengths, plane, offset, strand filter, adjacent ligation, separate fresh extrusions. |
| `overhang-extrude` | Source helix/bp, direction, end, neighbor row/column, positive length, reuse-existing-helix choice. |

The form edits a private draft and retains it on refused or failed Save. It uses
the existing feature edit endpoint with explicit document, revision and feature
identity. A document reset retires the editor; late responses cannot adopt into
another document. Complete candidate geometry travels with the response, so
adoption does not fetch geometry from a later revision.

## Shared owned transaction

The implementation uses the existing publication and worker lifecycle:

- [Input normalization](../../../backend/api/part_extrusion_edit_inputs.py)
  closes the editable field inventory and uses existing native request schemas.
  `normalize(kind, previous, patch)` returns independent complete inputs.
- [Shared recording](../../../backend/api/part_ordinary_recipe_recording.py)
  serves native pattern operations and extrusion edits; the extrusion wrapper
  and [route adapter](../../../backend/api/part_extrusion_feature_route.py) do
  not create a second session, worker registry or undo system.
- The selected row must be an ordinary top-level native snapshot with strict
  proof version 1 and a stable UUID seed. `_generator` and `_generated_scope`
  rows are excluded. Unknown saved fields refuse rather than being discarded.
- Admission requires compatibility policy, the latest history cursor, exact
  source design/revision/feature identity, supported recipe contracts and an
  independently reproducible source. Protected loadout checks remain in force.
- One bounded owned capture goes to the existing isolated evaluation worker.
  It proves the original source, rebuilds the edited row and downstream recipe,
  and validates the candidate. Missing references or native failures do not
  trigger a legacy fallback or consume undo/redo.
- Final publication rechecks source/session/policy/deadline/cancellation and
  publishes once through the existing transaction. Organized candidates require
  the exact candidate-bound organized-recipe permit. Response formatting uses
  the published candidate without legacy group inference.

`history_seed`, `_proof_version`, existing transport expectations and private
source receipts cannot be changed through form fields. Stable command identity
does not promise that every topology-changing input preserves all output objects;
the unchanged native builders determine output topology from the retained seed.

## Continuation source receipt

Changing cells or source frame must not retain an obsolete `_source_helix_ids`
dependency receipt. The private `bind_prefix(kind, params, prefix)` hook runs
after proof-identity preservation and before regeneration, using the independently
proved design immediately before the selected feature. For the edited
`extrude-continuation` row only, it replaces the receipt with the sorted actual
native continuation sources; fresh cells may correctly produce an empty list.

Untouched rows are not rebound. The pinned identity helper and legacy replay
semantics are unchanged. Frame/source-helix/overhang-helix references receive
typed missing/ambiguous diagnostics at their authored input paths. Native
execution still owns occupancy, endpoint and numerical frame validation.

## Bounds and compatibility

- Existing operation admission: 256 KB, 10,000 nodes and depth 64; strict finite
  numbers and exact integer/boolean fields reject coercible malformed input.
- At most 512 unique cells and 50,000 base-pair-cell work. Circle lengths match
  cells and are positive; overhang length is positive; other supported native
  lengths are signed and nonzero. Source inventory inspection is bounded.
- Existing capture, worker transport, recovery and publication limits remain.
  The five-second host budget covers capture/proof/publication, **not** subsequent
  response geometry formatting or end-to-end browser latency.
- Existing saved rows keep their meaning. The new owned path is selected by
  explicit editor expectations or active organization; unrelated legacy editors
  retain their existing contracts.
- The organization rollout gate remains **false**. Ordinary legacy sources can
  use the owned editor without enabling organization. Organized acceptance tests
  may enable the gate explicitly; this is not production rollout.
- Organized overhang coverage edits an eligible overhang feature authored before
  conversion. It does not admit new overhang creation after conversion.
- No molecular calculations, pinned source manifests, model schemas or numerical
  policy changes are part of this editor implementation. Assemblies and VR
  validation remain outside this checkpoint.

## Acceptance and remaining work

The ordinary native editor is already reachable for all seven extrusion families; no rollout gate needs changing. **Extrude is complete for ordinary parts under C1–C9.** The full frontend passed9359 with1 skip; backend outcome and scoped legacy incompatibility are recorded below.

| Contract | Running-app evidence |
|---|---|
| C1 Create | Tools, empty-space context, both blunt-end menus and fresh-part Bundle: exact Cancel, one append, native proof and persistence. |
| C2 Edit | Seven-family native parameter editors; Bundle edits through Bend→Sweep and all six other family lifecycles pass. Extrude retains its existing form editor without live history preview. |
| C3 Regenerate | Native cold replay after creation/edit; Frame→nick routing preservation and atomic partial-target refusal; Bundle→Bend→Sweep. |
| C4 Failure | Earliest failing routing child gets its reason; later unregenerated rows show transient Blocked. Refuse-with-reason preserves canonical state; Cancel/retry clears feedback. |
| C5 Dependents | Deleting the Frame source lists the attached posed Extrude before commit; both end-menu workflows verify exact Cancel. Missing source helix refuses native replay. |
| C6 Persistence | One-step undo/redo, save/reopen and native proof pass across the editor family matrix and five creation workflows. Fresh Bundle keeps part identity and records one transaction. |
| C7 Rollback | Seven creation kinds refuse before building; historical edit buttons disable. Real creation requests at F0/mid-log refuse without changing design, geometry or undo/redo. |
| C8 Latency | Small Save1757.6 ms/Cancel117.7 ms; native18×504 Frame plus routing Save3755.0 ms/Cancel285.9 ms (GPU raster excluded). Within existing2× allowances; history form has no preview budget. |
| C9 Legacy | Length-only snapshot history fallback removed; unsupported rows cannot invoke it. Native edit dispatch retains source/revision guards. |

Detailed evidence and limitations remain in the sections below. Parked sealed-host and arbitrary group movement work are not prerequisites for this ordinary-part tool.

FH-18 remains open independently. Arbitrary new named-group movement cannot be
implemented by assigning an existing placement or applying a delta once to each
overlapping placement: placement order, deformation arm/frame selection and
extended-domain handling affect the result. That work requires an explicit
visible motion contract and demonstrated native geometry equivalence before
molecular changes. Remaining generated/branch/section consumers also retain
their declared obligations. This editor neither implements nor removes those
exits, and this plan adds no completion credit for their audit.

## S51 — Bundle history through Bend/Sweep, October 18

S51 qualifies earlier Bundle Extrude history editing through Bend→attached Sweep. Draft controls and exact Cancel, source-bound length/name Save, independent native replay, downstream identity/input preservation and desktop undo/redo/save/reopen pass with clean console. Real-worker oracle1 passed, harness13 passed, focused frontend42 passed, browser1 passed. No production behavior or additional gate changed. S52 remaining six Extrude-family desktop workflows is the sole unstarted successor. No milestone advanced.

See [S51 evidence](bundle_editor_desktop_20261018.md). Bundle's other draft
options were cancelled; only length/name publication is qualified here. MV-50
stays open. S52's fixed six-family matrix is defined in the current handoff.

## S52 — Six-family Extrude desktop matrix, October 18

S52 qualifies the initial six-family Extrude desktop matrix: Segment, Continuation, Deformed Continuation, Frame, Circle and Overhang. Real-worker native replay6 passed, harness19 passed, focused frontend42 passed; final browser7 passed including Bundle regression, with clean consoles. An initial Overhang timeout exposed excessive per-field assertion overhead; aggregate presence checking preserves all exact geometry values and the unchanged deadline. No production behavior changed. S53 Sweep source-variant desktop matrix is the sole unstarted successor. No milestone advanced.

See [S52 evidence](extrude_family_matrix_20261018.md) for the exact committed
control inventory. Initial family lifecycles qualify; alternate modes, failures,
races and resources remain open. S53 is defined in the current handoff.

## Downstream failure attribution — October 19

Ordinary worker refusals now retain the earliest failing feature ID/reason alongside their assessment; source-bound requests preserve structured rejection and name the routing child. Partial nick-batch invalidation refuses atomically: real browser1, source backend13 and shared-editor frontend33 passed. The modal retains the draft; design/geometry/history/redo remain exact. All-target removal semantics stay unchanged. No completion or gate credit.

## Dependency navigation — October 19

Feature rows and routing groups now expose parent/child inspection using the replay dependency contracts. Conservative ordering edges are identified as such; edit/delete impact still uses actual regeneration. A real Extrude→routing-child browser case checks both directions and exact design/geometry/history/redo preservation. Backend5 and focused UI13 pass; full frontend9346 passed,1 skipped. Dependency inspection never executes geometry or adopts a design response. C4 history-row feedback and remaining failure/race/resource acceptance remain open; no completion credit.

C4 UI follow-up: a real Extrude draft that partially invalidates a nick pair shows the failing child and a later blocked routing child. Cancel clears both markers; canonical design/geometry/history/redo remain exact. Feedback is transient and also clears on retry/reset/source replacement. Shared focused frontend63 passed. Failure policy remains refuse-with-reason, not commit-with-error-state; no completion credit.

Corrected-draft retry also passes in the browser: one revision/undo entry, both routing-child identities retained, native cold replay verified and markers cleared. Full frontend9354 passed,1 skipped; browser scratch roots independently absent. Backend execution semantics unchanged.

## Source replacement and representative resources — October 19

Same-ID reopen during a held real Save response exposed a stale modal: it now subscribes to source validity and retires even while Save is pending. Browser race and normal retry pass; stale reply cannot replace reopened state. The legacy length-only snapshot editor is removed; native input editors remain. Focused frontend49 pass. Native18×504 Frame plus routing: open86.6 ms, Save3755.0 ms, Cancel285.9 ms,18216 nucleotide rows,43745-byte source JSON; cold replay passes. Small Save1757.6 ms and Cancel117.7 ms. GPU raster excluded; all measured durations meet existing allowed limits. Contract-wide creation/control acceptance still needs audit before completion credit.

Full frontend9358 passed,1 skipped. Post-cleanup native Save browser passes again (1772 ms), including refusal correction, one undo entry, stable child identities and cold replay. Owned browser scratch roots independently verified absent.

## Creation and rollback closure — October 19

Tools, empty-space context and posed end-context creation each pass exact Cancel, one append, native cold replay, undo/redo/save/reopen and rollback refusal. Creation previously lacked the history editor's cursor guard; all seven native extrusion kinds now refuse before snapshot/build at rollback (backend transaction62 pass). The posed end workflow exposed duplicate occupancy after nicking: deformed continuation extended every fragment on a helix. It now reuses straight continuation's existing terminus eligibility policy; internal fragments remain exact. Near/far tests nick both directions and assert zero duplicate slots, unchanged source/internal strands and exact added base count; continuation file6 pass. No placement formula, phase, tolerance or occupancy guard changed. Three browser workflows pass; native rendered result inspected. Required frontend/backend regressions are tracked in the handoff; no completion credit pending acceptance audit.

Final entry audit additionally exposed fresh Bundle's pre-transaction reset (extra revisions) and a missing reference guard during attached Extrude replay. Bundle creation now preserves part identity, publishes once, retains exact Undo and an empty F0 recipe without resetting live state first. Missing reference helices raise the existing typed error before frame computation. Focused bundle15, continuation7 and F0 seek1 pass; all five creation entry workflows and both source-delete warning checks now pass.

Final regression: frontend9359 pass/1 skip; backend19020 pass/66 fail/19 skip. Failures comprise13 previously known,51 historical numerical-manifest compatibility expectations (old pins remain rejected; user explicitly excludes legacy compatibility), one old Bundle-reset assertion updated to the new transaction contract (undo-boundaries18 pass), and one parallel verification deadline (whole overhang-proof file8 pass on rerun). No manifest, golden, tolerance or geometry check weakened. Aggregate370s guard triaged:19105 tests, zero individual5s violators, same real-worker-heavy files; no new reclassification. Ruff/JS/diff checks and scratch cleanup pass. Tool count1/4; ordinary editor already reachable, so no new gate flip.

### Source-reference repair — October19
- Existing saved-proposal panel supports continuation/frame source frames, deformed continuation reference helix, and overhang anchor helix; prefix-only typed discovery and full native replay own validity.
- Derived continuation source receipts refresh through the existing binder. Stable feature IDs, downstream replay, atomic rejection and suppression preservation covered by geometry repair12.
- Extrude source-repair app workflow passes proposal/Apply/undo/redo/save/reopen/cold proof; companion Sweep passes. Hidden repair launcher corrected (ISSUE-146); owned scratch w_0rosal absent.
- User-requested stopping point: final regression and commit boundaries in session_handoff.md. No new editor host, molecular constants or legacy compatibility work.
