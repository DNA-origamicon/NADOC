# Hand-specific quiver and VR view tools — 2026-09-28

## Implemented behavior

Right quiver and wheel Nick equip scissors on the right controller only. Left
quiver independently opens/stows a two-column world panel with the eleven original
desktop SVG icons. Triggering a tile invokes its shared desktop handler. The
native renderer receives document-bound binary snapshots of displayed geometry,
colors, instance poses, opacity and text textures. Shared mesh instancing is
preserved. Every snapshot carries the triggering action's acknowledgement sequence;
an older upload cannot release a newer pending click.

The layout prerequisites match desktop. Native canonical editing is suppressed in
straight/Unfold/Cadnano inspection layouts, where canonical edit coordinates would
otherwise disagree with visible geometry. If a snapshot cannot be exported, the
panel reports the error, retains the last drawable scene and acknowledges the
request so the user can turn the unavailable overlay off.

The shared desktop Expanded button now reflects the requested state immediately,
including changes from Q/force-off; its old read of the settled animation state
could leave the button reporting OFF after a completed expansion.

## Evidence routes

- Debug → VR Tours & Tests → Right sidebar → **Left-hand view tools**.
- `uv run python -m tools.vr_workflows.view_tools_tour --validate`.
- `tools.vr_workflows.nick_tour --validate` additionally verifies left-menu
  equip/stow while right scissors remain equipped and a left trigger cannot nick.
- Browser regressions: `vr_view_tools_capture.spec.js`,
  `vr_view_tools_transfer.spec.js`, and `vr_tours.spec.js`.

The generated runtime fixture includes loop and skip sites, a named assigned
sequence overhang, and a displaced cluster that makes view changes meaningful.
The design is placed beside the tablet using ordinary grip manipulation. Controller
reaches use the existing noisy motion profiles without snapping their endpoints.
The tablet checker samples projected tile locations in both stereo eyes and the
actual submitted-eye desktop mirror; displaced/offscreen samples must fail.
Stowing must remove those pixels. Screenshots retain the displayed design for
review of the resulting overlays/layouts.

## Transfer benchmark

Artifact: `.development-artifacts/vr-view-tools/transfer2/`.

| Generated VDW design | Instances | Shared vertices | Expanded equivalent | Bytes | Browser capture / encode |
| --- | ---: | ---: | ---: | ---: | ---: |
| Two 42-bp helices | 3,360 | 1,680 | 1,411,200 | 17,106,788 | 37 / 4.8 ms |
| Twenty 140-bp helices | 112,000 | 1,680 | 47,040,000 | 25,797,988 | 117 / 20 ms |

These measurements preceded the four-byte action-acknowledgement header addition
and the non-finite-instance filter. They establish preserved instancing and a
bounded transfer rather than a throughput guarantee. Native live state reports
`parse_ms`, `upload_ms`, primitive counts and instance counts for each accepted
snapshot. GPU upload timing is CPU submission time, not compositor timing.

## Retained development failures

All attempts remain under `.development-artifacts/vr-view-tools/`:

- `initial`: launch timed out during a native rebuild.
- `pass2`, `pass3`: fixture extrusion used an incompatible neighbor/end; fixed
  the generated fixture to use the actual reverse-strand 3′ end.
- `pass4`, `pass6`: probe started before focus/socket readiness; added readiness
  checks. `pass5` exposed Unicode SVG serialization and a development reload.
- `pass7`: input worked but the new tablet was omitted by the old menu-render
  condition. Stereo/mirror pixels revealed this and the gate was fixed.
- `pass8`: desktop Expanded's animation-state reporting was stale.
- `layout-check`, `capture`: Cadnano's non-drawable slab connector instances
  contained NaN matrices. These instances are now omitted; backend finite-value
  validation remains strict.
- `final`: steady_fast passed; steady_deliberate exposed the stale upload
  acknowledgement race on the second Length click. Acknowledgements are now
  action-specific; no visibility or motion threshold was relaxed.
- `acknowledged`: a concurrent browser regression reused the native test's
  document ID and overwrote its display feed. Regression and runtime fixtures
  now use distinct process-specific IDs, and browser/runtime campaigns run
  separately.
- `isolated-final`: steady_fast passed on the final implementation; the next
  viewer's startup socket existed before it responded, so the probe timed out
  before any controller movement. Startup transport errors are now retried
  within the existing 30-second focus-readiness deadline and recorded separately
  in `startup.json`. Motion/visibility thresholds are unchanged.
- `transfer`: stopped an oversized-count assertion whose initial generated
  fixture had fewer than 100,000 atoms; enlarged the fixture instead of lowering
  the assertion. `transfer2` passed with 112,000 instances.

An owned test viewer from `layout-check` was stopped explicitly after a native
rebuild changed its executable inode and the normal status-based teardown could
not recognize it. Subsequent final campaigns use a fixed built executable.

## Review limits

Stereo captures and submitted-eye mirror checks establish rendered output, not
physical through-lens legibility or comfort. The panel remains world-placed until
stowed/reopened. Display snapshots use flat material colors and billboard text;
lighting/shadows and object-ID ownership continue to belong to the canonical
native scene path. Arbitrary straight/2D editing is intentionally not enabled.


## Completed view-menu gate

All four motion profiles passed on the final production implementation:

| Profile | Evidence below `.development-artifacts/vr-view-tools/` | Result |
| --- | --- | --- |
| steady_fast | `isolated-final/end/steady_fast/` | 25 actions passed |
| steady_deliberate | `steady-deliberate/end/steady_deliberate/` | 25 actions passed |
| variable_fast | `variable-fast/end/variable_fast/` | 25 actions passed |
| variable_deliberate | `variable-deliberate/end/variable_deliberate/` | 25 actions passed |

Each run checked 24 visible-tablet stereo/mirror captures plus one stowed-tablet
capture; offscreen negative controls failed as required. All eleven tile handlers
agreed with desktop state. Aggregate: `view-validation.json`.

Focused automated checks: 68 frontend unit tests, 30 backend view/ligation/tour
tests and four native interaction/live-input tests passed. Browser regressions
verified finite Cadnano exports, delayed-upload acknowledgement isolation and
last-view/error-panel recovery (`regression2/`). Seven Debug-tour UI checks plus
the original Cadnano regression passed in `regression/`.


Across the 100 view-menu checkpoints, native parsing took a median 4.51 ms and
GPU upload submission 1.34 ms. The largest upload (14.71 ms) was the initial atlas
allocation before the first equip; subsequent recorded uploads were at most
4.09 ms. These are CPU-side measurements and do not establish compositor frame
pacing or headset comfort.


## Completed scissors / independent-hand gate

`scissors-final/result.json`: steady_fast, steady_deliberate, variable_fast and
variable_deliberate all passed. Each profile exercised right quiver equip/stow,
left menu equip/stow with the right scissors still equipped, a left-trigger
attempt on a bond that must not nick, gradual right-trigger closure/glow,
one backend nick, non-repetition while held, and exact Undo/Redo restoration.
Stereo/mirror tablet and scissors checks include offscreen negative controls.
The maximum recorded target-acquisition attempt was one; no target retries were
needed in this final scissors campaign. Isolated viewers and test workspaces
were stopped/removed after the runs; retained evidence is in the archive-backed
`.development-artifacts` directory.
