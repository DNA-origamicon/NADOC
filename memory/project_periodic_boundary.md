---
name: periodic-boundary-cadnano
description: "Cadnano 2D path-view \"periodic boundary\" mirror — view/edit a polymerization seam by drawing one end beside the other. Shipped 2026-05-24."
metadata: 
  node_type: memory
  type: project
  originSessionId: f2637643-d58c-484b-9ad6-82d89f6ed13a
---

# Periodic Boundary View (cadnano 2D editor)

Shipped 2026-05-24. Lets the user close an end-to-end **polymerization seam**: with
the boundary on, the active design is redrawn as a dimmed **mirror** of one end
beside the other, so the far-end strands sit next to the near-end strands and the
seam gap can be eyeballed + closed (typically with a forced ligation). Pure 2D-editor
view state — **no backend, no `.nadoc`, no 3D-view change**. Edits made through a
mirror still flow through the existing API callbacks, so the real topology change
DOES appear in 3D (correct/expected). Plan: `~/.claude/plans/write-this-up-to-cheeky-cocke.md`.

## Locked model
- Period **P = far_slider_bp − near_slider_bp**, derived live (`_pbPeriod()`, never stored).
- Defaults: near = `ext.lo`, far = `ext.hi + 1` over **active** strands (`_activeStrandExtent()`,
  excludes `is_reference` ALWAYS). Domains occupy cells `[lo..hi]` inclusive (right edge
  `_bpToX(hi+1)`), so far = hi+1 makes P = cell count. Example 18hb 0–200 ⇒ near 0, far 200, P 200.
- Right of far slider: near-end content shifted **+P**. Left of near slider: far-end content
  shifted **−P**. **ALWAYS-OVERLAY (changed 2026-05-24, user choice):** primary (real) strands
  are drawn FULL + unclipped at full opacity; the mirror is a TRANSLUCENT overlay (alpha 0.55)
  ON TOP in its zones — so sliding a slider into the body superimposes periodic-onto-primary
  (slide the far end onto the near end to eyeball the seam). At default slider positions this
  looks unchanged (no real strands beyond the structure to overlay). REPLACES the earlier
  "beyond a slider it's clipped/hidden beneath the boundary" behavior. `_drawPbContentPasses`
  order: full real pass (opaque) → tint bands → left/right mirror passes (translucent, clipped
  to zones) on top. Editing a mirror zone still resolves to the MIRRORED strand; the visible
  primary underneath is an alignment reference only.
- Red ruler labels appear ONLY in mirror zones = **real bp of mirrored content**: right zone
  `display − P`, left zone `display + P`. Far slider reads red 0 / near reads red P when the
  structure starts at bp 0. Black labels suppressed inside the zones. (NOT seam-relative.)
- **Mirror-pass cull gotcha (fixed 2026-05-24):** `_drawSequences` and `_drawUndefinedBases` do a
  MANUAL per-char on-screen cull (`sx = cx*_zoom + _panX`) — it must ADD the mirror translate
  `ghostShiftX = _ghostPass * _pbPeriod() * BP_W`, else mirrored sequence/undef-base letters get
  culled even though the chars draw at `cx` (the ctx translate places them on the mirror side).
  Strand bodies/arcs have NO manual cull (canvas clips), which is why they mirrored fine but
  letters didn't. Any new per-feature manual screen-x cull inside `_drawWorldContent` needs the
  same `ghostShiftX` term.
- Editing a mirror edits the REAL strand (live proxy). Forced ligation (strand-ID based,
  position-independent) is the seam tool; a lattice crossover across the full period is not
  meaningful → crossover sprites suppressed in mirror zones.
- Auto-shift (`update(design)` ~4719): fires ONLY when an EDIT grows the active-strand extent
  OUTWARD past a slider, gated on the LAST-SEEN extent `_pbLastExt` (set in `_pbInitDefaults`):
  `grewNear = ext.lo < prev.lo && ext.lo < _pbNearBp`; `grewFar = ext.hi > prev.hi && ext.hi+1 > _pbFarBp`.
  When fired, TRANSLATE both sliders by the same delta so the exceeded slider lands on the new
  extent while the **period P stays constant** (rest of the design / mirror copy doesn't jump);
  both-ends-grew-at-once falls back to grow-to-enclose. `_pbLastExt = ext` each update.
  **Why gated on extent-GROWTH, not "slider inside structure":** so the user can drag a slider
  INTO the occupied region (jagged puzzle-fit seam, e.g. far→190 while content reaches 200) and it
  STICKS across refreshes — the old `ext.hi+1 > _pbFarBp` check reset it to 200 on the next update.
  Brief `_pbFlash()` pulse on shift. (Replaced the original grow-one-slider behavior.)
- Ephemeral: resets on reload + on toggle-off.

## Key code (all in `frontend/src/cadnano-editor/pathview.js` unless noted)
- Wiring: `store.js` `viewTools.periodicBoundary`; `cadnano-editor.html` View-menu item
  `#menu-view-periodic-boundary` + `vt-btn[data-vt="periodicBoundary"]` (red, "pbc") + CSS;
  `main.js` menu click handler + `_syncViewToolButtons` toggles the `.is-checked` ✓.
  `setViewTools` caches `_pbActive`, resets `_pbInit`, calls `_pbInitDefaults()` on enable.
- State: `_pbActive/_pbNearBp/_pbFarBp/_pbNearDragging/_pbFarDragging/_pbInit/_pbFlashUntil`,
  `_ghostPass` (0|±1), `_ghostShiftBp` (captured at pointerdown).
- Helpers: `_pbPeriod`, `_pbOn` (gate everything; false when P<1 → degenerate no-op),
  `_activeStrandExtent`, `_ghostShiftForWorldX`, `_screenToRealWorld`, `_pbInitDefaults`, `_pbFlash`.
- **Camera preserved on toggle (2026-05-24):** toggling PB on/off does NOT move the camera —
  `_pbInitDefaults` only sets slider positions, never pan/zoom. (The old `_pbFrameSeam`
  reachability auto-frame was REMOVED — it jumped the view to fit the seam, losing a zoomed-in
  area of interest.) Tradeoff: the mirror can be off-screen when zoomed in; pan to it. Verified:
  zoom in, toggle on → structure/ruler stay at identical screen positions, only sliders+mirror
  appear; toggle off → round-trips to the identical view.
- Render: `_drawPbContentPasses` (left mirror −P / right mirror +P / real-clip / tint bands;
  sets `_ghostPass` around `_drawWorldContent`) called from `_draw` when `_pbOn()`;
  `_drawPbChrome` (screen-space red bars + handles + **seam-gap readout** `P − span`,
  green when flush) after `_drawRuler`; red labels added inside `_drawRuler`.
- Reference exclusion: the 5 `isRef && ...` skip sites changed to
  `isRef && (_ghostPass !== 0 || _viewTools.referenceGeometry === false)`;
  `_drawCrossoverIndicators` early-returns when `_ghostPass !== 0` (before touching `_xoverSprites`).
- Editing translation: `_hitTest` resolves via `_screenToRealWorld` (single choke point → all
  callers). Slider drag in pointerdown (priority over slice bar) / pointermove (clamp near≤far−1)
  / release in up/leave/cancel. Paint + nick subtract `_ghostShiftBp` for REAL bp; previews
  (`_drawEndDragGhost`/`_drawDomainDragGhost`/`_drawPencilGhost`/`_drawNickHover` via
  `_nickHover.shift`/`_drawForcedLigationArc`) render BACK at the mirror by `+shift`.
  End/domain drag deltas are shift-invariant (no resolve change, preview offset only).
- Auto-shift: in `update(design)` after `_rebuildLayout()`, grow-outward only.

## Mirror-side editing (full parity, 2026-05-24)
Ends, crossovers, AND loop/skip markers are all select/resize/move-able on the mirror side:
- **Ends**: always worked — `_hitTest` resolves via `_screenToRealWorld`; end-drag ghost renders
  back via `_ghostShiftBp`. Verified: dragging a mirror-side end cap resized the real strand (42→38 nt).
- **Crossovers** (was body-only in the first cut; FIXED 2026-05-24): all `_hitTestArc` call sites
  now resolve through the mirror — pointerdown drag-start uses `_hitTestArc(wx - _ghostShiftBp*BP_W, wy)`;
  pointermove subtracts `_ghostShiftBp` from `curBpFrac`; `_drawXoverDragGhost` does
  `ctx.translate(_ghostShiftBp*BP_W,0)` to render the preview on the mirror; pointerup-select, hover
  cursor, and contextmenu use `_screenToRealWorld`. Verified: hover→grab + click-select on a mirror
  arc (highlighted in body+mirror); drag behaves identically to body (control test). Loop/skip SELECT
  fixed too (same pointerup `_screenToRealWorld`).
- Editing a mirror element always commits to the REAL element (the mirror is a pure x-shift view).

## v1 limitations (documented, non-blocking)
- Lasso is display-space; a lasso spanning the seam selects only body strands.
- Crossover SPRITES (place-new-crossover indicators) are still body-only — `_drawCrossoverIndicators`
  early-returns in mirror passes. Placing a new crossover happens in the body; existing ones are
  select/move-able on the mirror side.
- Mixed inclusive/exclusive nuance lives in `_activeStrandExtent` (hi inclusive → far = hi+1).

## Seam ligations: flag + sequence verification (2026-05-24)
Follow-on to the 2D feature.
**3D GLOWING ARROWS REMOVED 2026-05-24** (user: "don't help at all; keep periodic-boundary
visuals in the cadnano editor only"). Deleted `seam_arrows.js` + `assembly_seam_arrows.js` and all
their wiring (design_renderer `buildSeamArrows`/`_seamArrowsGroup`/`setSeamArrowsVisible`; main.js
`initAssemblySeamArrows` + the 5 `assemblySeamArrows.rebuild` sites + click handler + subscriber;
`menu-view-seam-arrows` in index.html; `showSeamArrows` in store.js). The `is_periodic_seam` FLAG +
2D detection + editor dashed through-boundary arcs are KEPT (they're the editor-side visual). The
struck-through "Glowing yellow arrows" bullet below is HISTORICAL — no 3D seam rendering exists now.
- **Sequence assignment across the seam already works** (confirmed, no code change): forced
  ligation MERGES the two strands into one multi-domain `Strand` (`_ligate`), and
  `sequences.py` walks `strand.domains` 5'→3', so a seam-closing ligation is sequenced as one
  continuous strand. Regression test `TestForcedLigationPeriodicSeam` in
  `tests/test_forced_ligation.py` asserts merged.sequence == a_seq + b_seq.
- **`ForcedLigation.is_periodic_seam: bool = False`** (models.py ~633) — display flag, no topology
  role. Added to `ForcedLigationRequest` + stored in the route (crud.py ~5764/5807). Set
  MECHANICALLY in the 2D editor: at forced-lig completion, `crossesSeam = _pbOn() &&
  _forcedLigStartShift !== endShift` (3' click zone vs 5' click zone differ — one body, one
  mirror). Threaded `onForcedLigation(a,b,isPeriodicSeam)` → api.js `forcedLigation(...)`.
- ~~**Glowing yellow arrows** in BOTH 3D views~~ (REMOVED — see note above; historical detail follows) toggle `View ▸ Seam Ligations`
  (`menu-view-seam-arrows`, store `showSeamArrows` default true, single-design + assembly both —
  NOT hidden in assembly). `seam_arrows.js` `buildSeamArrows(design, nucleotides)` → local-coords
  Group (per-call geo+materials — both renderers `_disposeRoot`/teardown dispose everything, so
  NO module singletons). Single-design: built in `design_renderer._rebuild` → added to
  `_helixCtrl.root`; `setSeamArrowsVisible`. Assembly: `assembly_seam_arrows.js`
  (`initAssemblySeamArrows`) — renderer-agnostic standalone overlay modeled on
  assembly_joint_renderer: fetches per-instance geometry (`getAssemblyGeometry` batch), builds
  arrows in local coords, `arrows.applyMatrix4(_instMat4(inst))` → world. Rebuilt next to every
  `assemblyJointRenderer.rebuild(...)` site in main.js (5 sites); toggled via the store subscriber.
  Arrow form (changed 2026-05-24, user clarification): NOT one long arrow spanning 3'→5' (the
  endpoints are at opposite ends of the structure). Instead TWO SHORT stubs per connection —
  one glowing arrow at each terminus, length `STUB_LEN`=3nm, pointing along that strand's helix
  axis (`axis_tangent`) outward = away from the other endpoint (toward where the next polymer
  copy attaches). `_outwardDir(tangent, away)` orients the tangent by `sign(tangent·away)`;
  `away` = ±(posA−posB). Independent of the cadnano periodic-boundary toggle (driven only by 3D
  `showSeamArrows` + `is_periodic_seam`). Verified via geometry unit test: group has 2 children,
  each ~4nm bbox (vs ~68nm span), one reaching beyond each end. NOTE: assembly default renderer is
  the SHARED instancing one — arrows are a separate scene overlay (not added to an instance group).
- **2D dashed seam arcs through the boundary** (2026-05-24): in the cadnano editor, an
  `is_periodic_seam` forced ligation whose endpoints are >½ period apart (so the wrap is shorter)
  is drawn, while PB is on, as TWO short DASHED arcs — one through each seam to the other
  endpoint's mirror image — instead of the long straight arc. Helpers `_pbSeamFLThroughBoundary(fl)`
  (gate: `_pbOn() && fl.is_periodic_seam && |3'bp−5'bp| > _pbPeriod()/2`) + `_pbSeamFLArcs(fl,xA,yA,
  xB,yB)` (returns the two bowed segments: 3'→(5' image one period nearer) and 5'→(3' image nearer);
  `dx = sign(5'−3')·P·BP_W`). Used by THREE sites that MUST stay in sync: `_drawCrossoverArcs` FL
  loop (draw dashed in the real pass only, `continue` to skip the straight arc + ticks in every
  pass), `_hitTestArc` FL loop (click-select), and `_hitTestLassoElements` FL loop (lasso). Verified:
  seam FL 3'bp41↔5'bp7 (P 35, wrap 1bp) — PB off shows the long diagonal; PB on replaces it with a
  blue dashed arc crossing each seam to the mirror image.
- **2D fading-stub mode when PB is OFF** (2026-05-28): user choice — a periodic-seam FL with PB
  turned OFF should NOT render the long straight arc across the structure. Instead, draw TWO
  short DASHED stubs (length `BP_W*5`) leaving each endpoint outward along x (away from the other
  endpoint), each stub fading from full alpha at the endpoint to 0 at the tip via `FADE_DASHES=6`
  segmented dashes with decreasing `ctx.globalAlpha`. Helpers `_pbSeamFLAsStubs(fl)` (gate:
  `!_pbOn() && fl.is_periodic_seam`) + `_pbSeamFLStubs(fl,xA,yA,xB,yB)` (returns two
  `{x0,y0,cx,cy,x1,y1}` straight segments — `cx,cy` at the midpoint so the quadratic collapses to a
  line, letting hit-test reuse `_quadBezierMinDistSq` unchanged). Same THREE sync sites (draw +
  click hit-test + lasso) — each now has THREE branches: stubs / through-boundary / straight arc,
  in that priority. Direction: 3' stub points `sign(3'bp − 5'bp)`, 5' stub points opposite. Tick
  marks and `isRefFL` reference-strand dashing are skipped in this mode (the stubs *are* the visual).

## Verification (2026-05-24)
Vite build clean. Playwright screenshot smoke on `Examples/6hb_test.nadoc`: PBC button present,
two sliders (near 42 / far 0), mirror direction + red-label origin both correct (no sign flip),
`seam: flush ✓`, no console errors. **Eval-based store reads are unreliable in Vite dev**
(dynamic `import()` in `page.evaluate` gets a duplicate module instance) — trust SCREENSHOTS /
DOM, not `editorStore.getState()` via evaluate. STILL PENDING USER VERIFICATION: interactive
editing through a mirror (resize/forced-lig → real strand), auto-shift on a real edit, and
reference-strand exclusion (6hb_test has none). See [[reference-geometry]] for the is_reference
flag; `.claude/rules/cadnano-editor.md` for editor architecture (auto-loads on any
`frontend/src/cadnano-editor/**` read; it replaced the deleted `project_cadnano_overhaul` plan).
