# ScryWrite VR troubleshooting — supporting detail

[Topic head](../../project_scrywrite.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

# ScryWrite VR troubleshooting

**Active persistent goal (2026-09-22):** [two VR authoring workflows](../../../docs/vr_authoring_workflows.md).
Latest checkpoint2026-09-23: all four presets pass VR-first diagnostics with noisy
30cm normal approach to menu controls AND each paint cell (NADOC_VR_APPROACH_CELLS=1).
Native wheel now30mm travel per detent at default scale, formerly10.5mm; honeycomb
still7bp. Variable presets paint with retained retries and correct49→42with7fine
clicks.35focused,36native,23smoke pass. Combined steady-profile diagnostic passes
3.3m through desktop6HB→default→blunt→freeform→native Undo→cadnano/save/reload;
blunt-end selection/activation/buttons and freeform placement remain ideal.
Both verified review outputs published in workspace/VR Testing (desktop-then-vr:
19helices/2frames/1554positions; vr-first:7helices/504positions, each includes one
empty editor cell). Never read review outputs as test oracles.
Next: ISSUE-41 visual review weakness: native whole-design eye image is tiny/end-on
(82x64authored-pixel bounds); presence>=100pixels passes but is not useful review.
Desktop reload image is useful. Improve ordinary view orientation/zoom and require
meaningful projected coverage; actual desktop-window delivery remains pending.
Then finish profiled end/freeform/setup and run fixed80trial cohorts (still zero
credit). Evidence: .development-artifacts/vr-workflows/cell-approach-validation.md,
cell-approach-policy.json and combined-review-publication.json. Keep serial caution.
Editable review parts: `workspace/VR Testing/` (Archive-backed). Retests delete all
.nadoc parts there even after user edits; never use these as validation fixtures.
Start steady_fast, final all four; completion requires ≥18/20 whole-workflow passes
in each workflow × variable_fast/variable_deliberate group, independent oracles and
all default/blunt-end/freeform modes implemented. Painted footprint transport now carries bounded cell arrays and lattice type
through native events, backend parsing and browser reduction; paints/resets advance
configuration sequence. Explicit persisted frame identity and independent-bundle candidate builder now exist;
frame-aware membership and collision-free cadnano export added. HC/SQ and
XY/XZ/YZ candidate pose/file-roundtrip checks pass; two-frame desktop import/render
and export reviewed. Evidence: `.development-artifacts/vr-workflows/frames-validation.md`. Cadnano slice frame selection and cell add/remove now pass a real browser check;
far-cell cluster membership and undo are covered. Rendered-bound centering keeps
occupied cells visible on frame switching. Evidence:
`.development-artifacts/vr-workflows/frame-editor-validation.md`. Remaining:
frame-aware continuation/crossover neighbors and native-to-browser commit adapter.
Independent-frame API now has design/revision guards, read-only preflight and
snapshot commit/undo/redo; browser addFrameExtrusion synchronizes real geometry.
An empty-part plus oblique-frame API-driven browser check passed (3D/cadnano).
Evidence: `.development-artifacts/vr-workflows/frame-commit-synced/`.
Empty-part painted drafts now resolve to revision-pinned initial-frame plans and
run real read-only backend preflight; browser check verifies no mutation before
commit. Evidence: `.development-artifacts/vr-workflows/painted-preflight-browser.log`.
Native actions now snapshot their config sequence, backend/browser preserve it,
and preflight retains a copied one-shot plan, invalidated on new draft/cancel.
Late feedback cannot restore a canceled plan. Native build/36 CTests and browser
plan-retention check pass (`action-binding-*` evidence). Browser Confirm/Undo handler and targetless feedback are now connected and pass
the actual app event-dispatch/mutation/render/undo check. Pending feedback must
publish before mutation; lost terminal feedback never replays the edit. Native
extrusion acknowledgements skip Move/Rotate GL transforms. Evidence:
`painted-commit-*`. Native Confirm now gates on current painted preflight. First physical browser-
launched empty-part paint/Confirm committed two one-bp helices and native acknowledged
COMMITTED. Canonical topology refresh now publishes a revision-checked snapshot,
then atomically replaces native GL scene while preserving normalization/view/input.
Physical refresh run reached revision 3; after panel exit/recenter, actual authored
objects covered only 5/9 pixels in the eyes. This proves presence, not legibility.
RECENTER now fits authored bounds without changing normalization/topology. Physical
repeat showed 3774/3724 canonical pixels (previous 5/9); reviewed eye/mirror show bases.
Commit/Undo physical check passes: revisions 3→4, authored pixels disappear in both
eyes and browser helices return to zero. Probe lives in tools/vr_workflows, not
Archive fixtures. Evidence: fit-validation.md and fit-undo-atomic/.
Repeated runs fixed null-draft crash (ISSUE-33) and state-publication/status-reader
race (ISSUE-34). Next: 6HB/profile-driven paths, target toasts/commit diagnostics,
source-frame/blunt/freeform placement, real desktop-window and round-trip checks.
Ideal aim/semantic entry only; no profile-cohort pass yet.
Physical initial 6HB baseline now passes (six cells,42bp, exact browser cells and
lengths, cadnano export+viewer, native Undo). Snapshot took12.185s; bounded same-
design revision retry fixes autosave invalidation (ISSUE-35). Retained failure
artifacts distinguish stale snapshot from the old10s tiny-part observation limit.
Mirror remains end-on; ideal input only, no noisy-profile acceptance. See
vr-workflows/sixhb-validation.md and sixhb-timed/.
Cell aiming now uses profile_input.py with actual noisy reaches and119-pose
measurement evidence for steady_fast seed0. One initial neighboring-cell mistake
exposed acquisition sensitivity. Declared hover-feedback correction (max3 reaches,
all misses retained) achieved6 correct cells after7 reaches, then passed baseline
6HB/cadnano-read/Undo. Menus/length remain ideal-input; no full profile acceptance.
See profile-corrected/, profile-motion-summary.json and docs/vr_authoring_workflows.md.
Latest zoom/approach diagnostics:4x existing scene grip enlarges paint radius
6.48→25.92mm. Baseline wrist ray was66–71degrees oblique; normal approach25cm
from panel allowed first three variable_fast cells, but next cell(2,1) is clipped
out of viewport. Need production lattice pan/recenter; no change to noise or
three-reach limit. Evidence zoom-acquisition-validation.md / profile-normal4/.
CENTER PAINT now implemented in native lattice footer; view-only midpoint of
painted cell bounds, exported bounds/view_origin. Physical variable_fast seed0
with4x zoom+normal approach now passes6HB/cadnano-read/Undo:8 reaches,6 clicks;
centering[0,0]→[1,1] preserved cells.36 CTests pass. Evidence center-paint-validation.md
and profile-centered/. General pan, all-control noisy input and desktop text
legibility remain open; no cohort success.
No whole-workflow success yet. Empty documents now have an explicit v14
`Q empty_authoring` snapshot contract; native physical-runtime XY draft painting
verified, no committed geometry. Evidence: `.development-artifacts/vr-workflows/empty-live-check.json`.


Fast visual metrics (2026-09-22): MCP `scrywrite_measure`, authenticated inspector
`POST /api/measure`, and `python -m tools.scrywrite_inspector.visual_metrics` read
final stencil masks directly, with normalized ROI and numeric range assertions.
Live benchmark ~23 ms vs ~251 ms full capture/copy. No images/files in measurement.
Classes group UI; individual button IDs/contour fits are not implemented. Keep real
image/desktop checks. [Usage and Archive evidence](../../../docs/scrywrite_inspector.md#fast-numerical-visual-checks-2026-09-22).

Extrude source-plane increment (2026-09-22): `EXTRUDE FROM` cycles XY/XZ/YZ in native
settings, carried as `extrude_from` in drafts/observation. Scene v13 adds the
`F <plane> <lattice> <reason>` default record; older scenes use XY/unknown.
Desktop's existing dropdown now resolves loaded geometry too. Source IDs take
precedence over rest-axis alignment; mixed/oblique inputs remain explicit fallbacks.
Future blunt-end/freeform options are deferred; user-approved freeform semantics are
canonical-plane topology plus persisted placement. Frame ownership and commits remain
outstanding. See the audit below and `.development-artifacts/vr-extrude-from/validation.md`.

VR Extrude persistence/coordinates audit (2026-09-22):
[findings and implementation contract](../../../docs/vr_extrude_lattice_mapping_audit.md).
Painted cells are native drafts; existing-end plans preflight but have no attached
Extrude commit executor. Arbitrary orientation needs explicit lattice-frame ownership,
frame-aware cell consumers and a browser-authoritative transaction. Mixed-plane same-cell
segments reproduce duplicate cadnano export coordinates; do not assume UI paint proves authoring.

User preference and reusable skill: [make debugging observable](../../feedback_debug_visibility.md).
Proactively improve viewing conditions while preserving the behavior under test.
