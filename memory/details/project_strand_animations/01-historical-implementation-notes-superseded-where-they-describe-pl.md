# Historical implementation notes (superseded where they describe placement) — supporting detail

[Topic head](../../project_strand_animations.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Historical implementation notes (superseded where they describe placement)

A standalone, **display-only** teaching/figure tool for showing strand-displacement / un-zipping
of two DNA strands (ssDNA ⇄ duplex) and every intermediate. First stage toward animating dynamic
origami (e.g. a hinge that opens as a linker unhybridizes). **No Design, no topology, no backend** —
pure parametric geometry. Three-Layer Law N/A (there is no topology layer to corrupt).

Opened from main app **Help → Strand Animations Testing…** → `window.open('/strand-anim.html')`
(handler in `frontend/src/main.js` next to `menu-help-hotkeys`). Separate Vite page registered in
`frontend/vite.config.js` `rollupOptions.input` as `strand-anim`.

## ⇒ Integration handoff (read this first — for dropping into the main animation toolset)

> **STATUS 2026-07-30 (`/audit-plan`): the integration BELOW ALREADY HAPPENED — option (c) shipped.**
> `AnimationKeyframe.strand_anim_phi` (`backend/core/models.py:1726`, OverhangSpec id → φ) is
> lerped by the player (`animation_player.js:250, :1051`), authored in `ui/strand_anim_panel.js`
> (which imports this module's `createParamState` + `createPhiTicker`), and rendered by
> `scene/overhang_strand_anim.js` (711 LOC) via this module's `createStrandRenderer`.
> `scene/overhang_unzip_overlay.js:33-34` additionally imports `meltFraction` **and `DEFAULTS`**,
> so `params.js` defaults are now production constants. **Caveat:** only the *renderer* seam was
> reused — `overhang_strand_anim.js:441/:599` re-implements the strand-list contract by hand on
> the real helix frame, so `buildStrandGeometry` is still sandbox-only (`app.js:42`, sole caller)
> and fixes to the pure builders do **not** reach the app. Editor-side details:
> `.claude/rules/animation.md`; the reverse-coupling traps: `.claude/rules/strand-anim.md`.
> The "player exposes no scalar-`t` driver" analysis below is historical.

The module is split into **drop-in pieces** (no page dependencies) vs **page-only glue**:

| Layer | Files | Deps | Reuse |
|---|---|---|---|
| **Model** (pure) | `model.js`, `params.js`, `melt.js`, `geometry_{straight,helical,displacement}.js` | none (plain math) | **drop in as-is** |
| **Renderer** (THREE only) | `strand_renderer.js` | `three`, `model.js` | **drop in as-is** |
| **Ticker** (RAF only) | `ticker.js` | none | optional (host may use its own clock) |
| **Page glue** | `app.js`, `panel.js`, `main.js`, `strand-anim.html` | scene/DOM/page primitives | rewrite/replace per host |

**The two seams a host needs:**
1. `buildStrandGeometry(params, phi)` (in [model.js]) → `{ strands:[{pos,tan,bn,role}], meta }`. Pure; `phi`∈[0,1] is the single reaction coordinate. `params` = `STRAND_DEFAULTS` shape (scenario + form + the sliders). See the output-contract JSDoc at the top of `model.js`.
2. `createStrandRenderer(scene, {roleColor?})` (in [strand_renderer.js]) → `{ update(strands), dispose() }`. Adds its own InstancedMeshes (`strandBeads`/`strandSlabs`) + pooled `THREE.Line`s to the given scene/group; grows buffers automatically; ball-and-slab constants match `helix_renderer.js`. Call `update()` each frame/edit.

Minimal host loop: `renderer.update(buildStrandGeometry(params, phi).strands)` whenever φ changes.

**Connecting φ to the main toolset's timeline** — the existing `animation_player.js` is **keyframe/scene-state based and exposes NO scalar-`t` driver** (no `(t)=>void` callback, no current-`t` getter; it owns its own RAF). So a strand animation cannot be driven by the player as-is. Options, easiest first:
- **(a) Per-frame driver like `kinematics_ticker.js`** (recommended for a first integration): own a scene group + a φ value; advance φ each frame in the main render loop (`main.js` ~14742, the same place `kinematicsTicker.tick(dt)` is called) or via the existing `createPhiTicker`. Decoupled from the keyframe player. Lets the strand demo live in a scene alongside a design.
- **(b) Add a scalar seam to the player**: give `animation_player.js` an `onParametricTick(t)` opt or a `registerFrameCallback(fn)` so a keyframe segment can drive φ. Most work; couples strand φ to the keyframe timeline/scrub/export.
- **(c) Keyframe field**: add a `strand_phi` (or generic param) field to the keyframe schema (`backend/core/models.py` AnimationKeyframe + CRUD) and lerp it in `_applyAt`. Persists with the design; biggest surface.

Player/panel/keyframe/backend specifics (signatures, event contract, endpoints) were mapped this session — see [animation] (recorded path: `project_*`) topic files / `animation_player.js` directly; the key fact for integration is the **missing scalar seam** above.

**Gotchas for the host:** the model lays geometry along **+X in the XY plane** (helix spirals in YZ); `app.js` sets a specific camera — a host with its own camera should frame accordingly. Renderer meshes are display-only (no raycast/picking wired). ssDNA tails get base slabs too (NADOC draws real ss as arcs — only the duplex regions follow NADOC slab conventions). `W` default 2.0 ≈ B-DNA diameter is assumed for slabs to bridge.

## Architecture (all under `frontend/src/strand-anim/`)
- **Shared output contract** (all builders): `{ strands: [{pos,tan,bn,role}], meta }` where each strand's `pos/tan/bn` are flat Float32Arrays (3·count) of backbone position, unit tangent, unit base-normal; `role` ∈ {A,B,substrate,invader,incumbent} → app.js maps role→color. `meta.readout` is the scenario-specific status string. (Refactored from the old 2-strand posA/posB contract on 2026-05-29 to support 3-strand displacement.)
- `geometry_straight.js` — `buildStraightLineGeometry(params, phi)` + `nucsPerStrand(N)`. THE core unzip math (roles A/B).
- `melt.js` — shared `meltFraction(i, jIdx, meltBp)` (smoothstep over `meltBp` bp centered on the continuous fork index), `smoothstep`, `lerp`. Both forms blend each base between its paired candidate H and arm candidate A by this fraction, so a base eases out over a couple bp instead of snapping. `meltBp` param (default 2.0, 0 = old sudden step). The main visible win is the **slab orientation**: without melt, tangent + base_normal snap ~30° in one frame as a base flips to the arm; with melt that's ~1–2°/step (verified). Position pop was already small (fork-anchoring makes H≈A at the fork).
- `geometry_helical.js` — `buildHelicalGeometry(params, phi)`. Hybridized region = real B-DNA double helix built with the **SAME conventions as backend/core/geometry.py `nucleotide_positions`** (verified by backend cross-check 2026-05-29): backbones at radius R=W/2 (=HELIX_RADIUS at default W=2), forward at `phase + bp·twist`, reverse offset by the **minor groove 150°** (`MINOR_GROOVE_RAD`, = BDNA_MINOR_GROOVE_ANGLE_DEG); per-nuc **`base_normal` = normalize(rev_backbone − fwd_backbone)** (negated on reverse strand) — the cross-strand chord, NOT radial-to-axis; **`axis_tangent` = helix axis (+X)** shared by both strands, NOT the backbone spiral tangent. So a base-pair slab is oriented exactly as `slabQuaternion(base_normal, axis_tangent)` in `helix_renderer.js`. Computes BOTH strands together per bp (so the chord is available). Unzipping region = straight freed ssDNA arms, fixed pull direction (A up / B down, no spiral), peeling from the last paired bp; freed-base slabs are ⟂ to the strand (ssDNA has no NADOC slab convention — NADOC draws ss as arcs). Same per-nuc output contract → shared app.js renderer. twistDeg=0 → paired region = flat ladder.
  - **Phase anchored at the FORK, not the fixed end** (`jIdx = f·N − 1`, continuous; `anchorAngle = (π − groove)/2` so the fork base pair straddles the pull plane symmetrically — fwd up, rev down, base-pair vector vertical, equal depth): freed strands peel cleanly, never cross. Consequence: the far/closed end rotates as f changes → the hybridized helix **twists as the ends are pulled apart**. Fixed the "strands clip ~once per helical turn" artifact (was fixed-end phase anchoring; 2026-05-29).
  - **Renderer constants match `helix_renderer.js` verbatim** (now in `strand_renderer.js`): BEAD_RADIUS 0.10, GEO_SPHERE(0.10,10,8), slab {len 0.30, wid 0.06, thick 0.70, dist 0.55}, slabCenter `+bn·(HELIX_RADIUS−dist)=+0.45`, slabQuaternion `makeBasis(tan×bn, tan, bn)`.
- `model.js` — **drop-in facade**: `buildStrandGeometry(params, phi)` (dispatch scenario→form), `STRAND_DEFAULTS` (=DEFAULTS), `ROLE_COLOR`, `nucsPerStrand`, and the output-contract JSDoc. The one model entry point a host imports. Pure.
- `strand_renderer.js` — **drop-in renderer**: `createStrandRenderer(scene, {roleColor?,lineOpacity?})` → `{update(strands), dispose()}`. Renders the strand-list into ball-and-slab (InstancedMeshes `strandBeads`/`strandSlabs` + pooled `THREE.Line` backbones) in any scene/group; **grows buffers automatically** based on total/longest-strand counts (decoupled from N/params). THREE-only.
- `params.js` — `createParamState()` tiny observable + `DEFAULTS`.
- `ticker.js` — `createPhiTicker({getState,setPhi,onState})`; RAF sweep of a linear progress `u`, φ=ease(u)/1−ease(u); loop/bounce; resumes from scrubbed φ via numeric `_invEase`. `_ease` copied from `animation_player.js` (no dependency on the 990-line player). **Boundary fix (2026-05-29)**: `dt` clamped ≥0 (a first rAF timestamp can predate play()'s clock read → negative dt) and boundary checks are direction-aware (only "hit" the end you're heading toward), so pressing Play exactly at a boundary (φ=0 hybridize / φ=1 dehybridize) sweeps inward instead of instantly finishing.
- `panel.js` — `buildPanel(panelRoot, state, {onChange,onPlayToggle,isPlaying})` → right-sidebar sliders via `createPanelSection` + `attachAllDragScrub`. Returns `{refresh}` (pushes state→controls when the ticker advances φ).
- `geometry_displacement.js` — `buildDisplacementGeometry(params, phi)`. **Toehold-mediated strand displacement**, 3 strands: substrate (spine, N bp = toehold t + branch domain m, fully duplexed), invader (N bases, bound over toehold+displaced [0,p), free leading tail), incumbent (m bases, bound over [p,N), displaced tail). φ = **fraction displaced**; branch point p = t + round(φ·m). Duplex uses the same NADOC conventions + helix/straight forms as the unzip builders; the two free ssDNA tails splay up in a Λ from the branch point (invader up-right, incumbent up-left); helix phase anchored at the branch point (tails peel up cleanly → duplex rotates as the branch migrates); per-base melt smooths bound↔free. `toeholdBp` param. Emits the shared strand-list contract.
- `app.js` — **page-host glue only** (thin, post-refactor 2026-05-29): `initStrandAnimApp(canvas, panelRoot)` wires `initScene()` + `createStrandRenderer(scene)` + `buildPanel` + `createPhiTicker` + readout + camera framing. `rebuildGeometry()` = `buildStrandGeometry(snapshot, phi)` → `renderer.update(strands)` + readout. No THREE/geometry math here anymore.
- `main.js` — entry; exposes `window.strandAnim`.
- `frontend/strand-anim.html` — page (clones cadnano-editor head: tokens/reset/base/components CSS); has `#strand-canvas`, `#strand-panel-body`, `#strand-readout`.

## Model
- Two **scenarios** (segmented selector): **Unzip** (2 strands) and **Strand displacement** (3 strands). **Form** (straight/helical) applies to both. One φ slider drives whichever scenario; its label switches to "fraction displaced" in displacement mode; the readout is scenario-specific (`meta.readout`).
- **Unzip: φ = fraction of base pairs still PAIRED.** φ=1 closed ladder, φ=0 fully unzipped.
- **Displacement: φ = fraction of the invader bound over the whole substrate (N bp).** The single sweep covers BOTH phases: φ∈[0, t/N] zips the toehold (invader binds the exposed ss toehold [0,t)); φ∈[t/N, 1] branch-migrates to displace the incumbent. φ=0 → invader fully free + substrate toehold exposed ss + incumbent fully bound; φ=t/N → toehold complex (the old φ=0 state); φ=1 → incumbent released. Binding front b=round(φ·N); the substrate region [b,t) has no partner → reads as the exposed ss toehold. `toeholdBp` param; m = N − t. Classic Λ of two ssDNA tails at the branch point during phase B. (Added toehold-binding phase 2026-05-29; was displacement-only.)
- Straight-line "ladder + traveling fork": duplex = two parallel rails at y=±W/2; its synthetic animation slabs point inward and nearly meet. This is an animation convention, not the full representation's coordinate solver. As φ drops a junction at `xJ=(nPaired/N)·L` travels, freed strands splay one UP (+Y) one DOWN (−Y) at half-angle θ; arm slabs stay ⟂ to the strand, angled back toward the centerline. `nPaired=round(φ·N)`. Zipped beads sit on a fixed lattice (spacing `L/N`, φ-independent) so the junction sweeps PAST beads instead of sliding them.
- **W default 2.0 ≈ real B-DNA diameter** is what makes the paired slabs (fixed 0.45 nm reach) meet — large/small W won't bridge as cleanly (sandbox tradeoff for matching `helix_renderer` constants verbatim).
- `strand_renderer.js` grows its InstancedMesh capacity on demand (total bead count) and per-line capacity (longest strand); φ/θ/W edits just rewrite instance matrices. `frustumCulled=false`.
- Scrub the φ range slider = inspect any static intermediate; Play animates φ (same `setPhi` path). `direction` only sets the time sign, never changes φ's meaning.

## Status — shipped 2026-05-29 (both forms, ball-and-slab)
BOTH straight-line and helical forms complete in **ball-and-slab** representation (all same day; plain-line version was an intermediate step). Form toggle switches between them; both driven by the same φ + panel. `twistDeg` param (default 34.3°/bp) added for helix tightness. Verified headless (Playwright) + screenshots at φ=1/0.6/0 for both forms: zero console errors; straight = closed ladder → traveling fork → two symmetric ssDNA chains; helical = full spiral → spiral+straight-fork → fully straight splayed strands. Math checks: vectors unit & ⟂, strands diametric, twistDeg=0 → flat paired ladder. Play sweeps φ in both forms (drops 1→0, stops, ⏸/▶ toggles); N/W/θ/twist/forkToCenter/endFrom rebuild clean. Fork-anchored helix phase (2026-05-29) eliminates the periodic strand-clipping at the junction and makes the hybridized portion twist as it's pulled apart — verified: fork bp stays in the pull plane at all φ, far end rotates through all angles, last-paired→first-arm peel = exactly armStep. **Helical bead positions + slab orientations matched to NADOC (2026-05-29)**: 150° minor groove, base_normal=chord(rev−fwd), axis_tangent=helix axis — verified to FP precision by JS invariant checks AND a direct backend `nucleotide_positions` cross-check; renderer constants verbatim from `helix_renderer.js`. **Per-base melt (2026-05-29)**: `meltBp` "Melt width" slider blends each base H→A over a few bp around the fork (both forms) so the paired→unzipped transition (esp. slab reorientation) isn't sudden; meltBp=0 restores the hard step. **Strand-displacement scenario (2026-05-29)**: 3-strand TMSD (substrate/invader/incumbent), `Scenario` selector + `toeholdBp` slider, same φ slider (= fraction displaced), both forms; output contract generalized to a strand list + app.js renders ≤3 strands by role-color. Verified: counts (sub N, inv N, inc N−t), end states, branch x tracks φ, unit vectors, screenshots of straight+helical Λ-junction intermediate, Play sweeps φ in all scenario×direction combos, unzip regression intact, zero console errors. **Toehold-binding phase (2026-05-29)**: φ reparametrized to invader-bound-fraction so the sweep zips the toehold THEN displaces; verified readout phases (toehold 0/6→6/6 over φ 0→0.25, then displaced 0→18/18) + screenshots (φ=0 free invader & exposed ss toehold → 0.125 zipping → 0.25 toehold complex → 0.6 Λ migration). Also fixed a latent ticker boundary bug (Play from φ=0/φ=1 now sweeps inward).

## Phase 2 — SHIPPED 2026-05-29 (bind/unbind φ animation in the design editor)
The original motivation landed: φ now couples to a dynamic-origami hinge in the main animation
toolset. A keyframe carries `AnimationKeyframe.binding_states` (driverId → φ ∈[0,1]; φ=1
bound/closed, φ=0 unbound/open), lerped in `animation_player.js _applyAt` like `joint_values`.
A *driver* is an `OverhangBinding` (WC pair) OR a linker `OverhangConnection` — both gained
display-only `target_joint_id` + `unbound_angle_deg` + `bound_angle_deg` (annotation; never read
by relax/topology). Per frame: `_driveBindingHinge` rotates the driver's target-joint cluster to
`lerp(unbound,bound,φ)` via the existing `applyClusterTransform` path (restored on stop, no
live-window clamp). The unzip moves the **REAL overhang beads** (NOT synthetic): per the user's
direction, `frontend/src/scene/overhang_unzip_overlay.js` splays the actual rendered nucleotides
via a NEW `helixCtrl.setBeadOverrides(updates)` (quiet, surgical per-bead updater in
`helix_renderer.js` — like `applyFemPositions` but no console.log / no full sweep → per-frame safe;
backed by a new `_keyToSlab` map). φ=1 = authored positions; φ→0 = melt fork tip→root, freed beads
splay as a straight ssDNA arm pointing TOWARD that strand's OWN root (perp-to-axis component of
root−center; ~90° for OH-OH). Linkers = overhangs' beads only (bridge left as-is). Moving-arm
overhang beads are rotated by the hinge incrRot to stay attached. (The strand-anim
`buildStrandGeometry`/`createStrandRenderer` seams are NO LONGER used by this path — only
`melt.js meltFraction` + `params.js DEFAULTS` are reused.) Authoring: animation_panel "Bind/Unbind
poses" + per-keyframe driver φ rows. Endpoints: `PATCH /design/overhang-{bindings|connections}/{id}/display-pose`
(linker auto-detects spanning joint via `_overhang_owning_cluster_id`). 10 backend tests; 1599 pass.
Three-layer-safe. **Verified:** backend data path + joint auto-detect on the real
`workspace/Ultimate Polymer Hinge2.nadoc` (in-process); frontend builds clean. **NOT yet visually
verified in app** — the 3D coupled hinge+unzip playback and polarity defaults (which end unzips,
angle sign, which arm moves) need a human smoke test. v1 caveats: splay/root geometry from authored
frame. See `.claude/rules/animation.md` "Strand-anim integration".
