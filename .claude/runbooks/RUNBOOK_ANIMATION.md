# animation — diagnostics runbook

Loaded on demand from the `animation` rule's Diagnostics pointer. Symptom → diagnosis; not
auto-loaded. **Rewritten 2026-07-30** — the previous version diagnosed a design-scoped
configuration feature (`config_panel.js`, `DesignConfiguration`, `api.goToConfiguration`,
`POST /design/configurations/{id}/go-to`) that **never existed**. Every one of its five "bug
suspects" named a dead symbol. See the rule's *Removed API* block before trusting any older prose.

## Status

- Camera poses + keyframe playback + WebM/GIF export: **stable, shipped**.
- Configurations: shipped **assembly-scoped only** (`/assembly/configurations`,
  `AssemblyConfigurationSnapshot`), in production use across 10+ `.nass` files. There is no
  design-scoped equivalent and there never was.
- Overhang bind/unbind: two independent paths (`binding_states` overlay, `strand_anim_phi` model)
  — see the rule. Both display-only.

## First question, always: design mode or assembly mode?

`animation_panel.js:711` reads configurations as
`_assemblyMode ? (store.getState().currentAssembly?.configurations ?? []) : []`.
**In design mode the config list is empty by construction, not by bug.** Most "configurations are
broken" reports are a design-mode session expecting assembly-mode behaviour.

## Symptoms

### Configuration dropdown is empty
1. Are you in assembly mode? If not — expected, stop here.
2. `store.getState().currentAssembly?.configurations` in the console — populated?
3. If empty on a saved assembly: check the `.nass` on disk actually has a `configurations` array.
4. If populated but the dropdown is stale: the panel reads the store at render time — force a
   re-render (reopen the panel). A config created via `POST /assembly/configurations`
   (`routes_assembly_configs.py:130`) must land in the store before the list refreshes.

### "Restore" a configuration does nothing
The route is `POST /assembly/configurations/{config_id}/restore`
(`routes_assembly_configs.py:147`), client fn in `api/animation_endpoints.js:17`. It calls
`assembly_state.set_assembly_silent` (`:212`) — **silent by design**, so it will not push an undo
entry and will not emit the usual mutation event. If the scene doesn't move, check the renderer
re-read the assembly, not that the route "failed".

### Clusters jump to the wrong position / stay stuck after playback
1. `_captureAllBases()` (`animation_player.js:583`) runs at `play()` (`:1159`), passing `!first`
   as the **3rd positional** `append` arg plus `{forceAxes:true}`. If you changed a call site,
   check the arg *position* — `domain_ends.js:758` has a different order
   (`transformKeys, append, domainIds`) and mixing them up silently captures the wrong set.
2. Stuck-after-stop → `_restoreBaseClusters()` (`:688`, called only from `stop()` `:1196`) didn't
   run, or the renderer rebuilt between play and stop so the restore targeted stale objects.
   Note it applies an **identity quaternion with `dummy === center`** — there is no slerp; if you
   see rotation drift, the base capture is wrong, not the restore math.
3. A cluster driven by `_driveBindingHinge` (`:740`) is restored by the same path — if only the
   hinge-driven cluster is stuck, look at the driver's `target_joint_id`, not the base capture.

### Overhang beads don't unzip / unzip on the wrong end
1. Which path? `binding_states` (overlay) or `strand_anim_phi` (model)? They move **disjoint
   beads**; a keyframe can have one and not the other.
2. Overlay path: it no-ops if `helixCtrl.setBeadOverrides` or `geometry` is missing
   (`overhang_unzip_overlay.js:114`). Confirm the player got a non-null
   `getDesignGeometry()` at `animation_player.js:1047`.
3. Wrong end / wrong angle sign is a **known v1 caveat**: splay and root geometry are computed
   from the *authored* frame and polarity uses defaults. Verify in the app; this is not a
   regression.
4. `setBeadOverrides` (`helix_renderer.js:3266`) is the surgical per-frame path. If you find
   yourself reaching for `applyFemPositions` (`:3316`) for animation, stop — that's the bulk
   sim-display path and it sweeps the scene.

### Export produces wrong geometry
`seekTo` (`animation_player.js:1267`) makes **no backend call — by design**. Geometry for each
keyframe's `feature_log_index` is **pre-baked** before playback via
`POST /design/features/geometry-batch` (`routes_feature_log.py:112`), with `atomistic-batch`
(`:138`) and `surface-batch` (`:168`) for the other representations.
So "export used stale geometry" means **the bake was wrong or incomplete**, not that seek needs a
persist. Check: did `cancelBake()` (`:355`) fire mid-bake? Does every keyframe have a
`feature_log_index`? Did the representation in use (atomistic / surface) get its own batch?

### Camera won't follow / user can't orbit during playback
`setDisablePoses(true)` (`:1260`) skips the camera-pose lerp entirely so the user can orbit.
If poses are being ignored, check this flag before debugging the pose lerp.

### Text overlay missing
`AnimationKeyframe.text*` (7 fields) → player `onTextOverlayUpdate` →
`applyAnimationTextOverlay(document.getElementById('canvas-area'), state)`
([main.js:1619](../../frontend/src/main.js#L1619)). It is a **DOM overlay**, not a Three.js
object — it will not appear in a `MediaRecorder` canvas capture unless composited deliberately.

## Three-Layer reminder

Everything the player does at playback time is **display state**. `_driveBindingHinge`, the unzip
overlay, `setBeadOverrides`, cluster transforms during playback — none of it is written back to
topology. If a fix tempts you to persist a frame, it belongs in authoring (a PATCH route), not in
the frame loop.
