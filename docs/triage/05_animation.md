# Feature 05: Animation
**Phase**: E (Temporal/Presentation — requires all prior phases)

---

## Feature Description

Keyframe animation system with three phases of completion:
- **Phase 1 (Camera Poses)**: ✅ Stable — `CameraPose` CRUD, `V` hotkey to capture
- **Phase 2 (Keyframe Playback + Export)**: ✅ Stable — frame loop, bounce/seek, MediaRecorder export
- **Phase 3 (Configurations)**: 🔴 Needs debugging — cluster state animation, config dropdown

**Key files**:
- `frontend/src/scene/animation_player.js` — `initAnimationPlayer({camera, controls, designRenderer, deformView, getConfigPanel})`
- `frontend/src/ui/animation_panel.js` — `initAnimationPanel(store, {player, api})`
- `frontend/src/ui/config_panel.js` — `initConfigPanel(store, {getHelixCtrl, api})`
- `frontend/src/ui/camera_panel.js` — `initCameraPanel(store, {captureCurrentCamera, animateCameraTo, api})`

**Models**: `CameraPose`, `AnimationKeyframe`, `DesignConfiguration`, `ClusterConfigEntry`

**Phase 3 bug suspects** (from MAP_ANIMATION.md):
1. `captureClusterBase` append mode interaction with renderer rebuild
2. `_restoreBaseClusters` identity quaternion math
3. Config dropdown not populating if configs loaded after panel init (timing race)
4. `set_design_silent` missing on `update_configuration` (undo stack pollution)
5. Export timing: `seekTo()` doesn't trigger backend persist → export uses stale geometry

---

## Pre-Condition State

- Phase 1 + 2 are flagged stable but have not been tested with the new crossover model
- Phase 3 has 5 known bug suspects, none confirmed fixed
- Unknown whether crossover lines update correctly during animation playback (they should, if `currentGeometry` updates at each frame)

---

## Clarifying Questions

1. During animation **playback**, should crossover connection lines:
   - (a) Update every frame (requires `currentGeometry` update per frame — may be costly)
   - (b) Update only at keyframe boundaries (cheaper, but lines snap at keyframes)
   - (c) Not update at all during playback (freeze at start state)

2. Can an animation keyframe reference a specific `design.crossovers` state?
   - (a) No — topology (crossovers) is frozen at animation start; only camera + cluster transforms animate
   - (b) Yes — the feature log system allows seeking to any past topology state; keyframes can reference past states

3. Should the **deformed view toggle** be:
   - (a) Locked during animation playback (cannot toggle)
   - (b) Controllable per-keyframe (each keyframe specifies deformVisuActive state)
   - (c) Independently togglable during playback

---

## Experiment Protocol

### Experiment 5.1 — Camera-only animation plays smoothly

**Hypothesis**: An animation with two camera-pose keyframes and no cluster config interpolates camera position and orientation smoothly over the keyframe transition duration.

**Test Steps**:
1. Load `26hb_platform_v3.nadoc`
2. Capture camera pose A (use `V` key or Camera panel)
3. Move camera to a new position, capture pose B
4. Create animation with 2 keyframes: A (hold 1s) → B (transition 2s, hold 1s)
5. Play animation — observe smooth camera lerp

**Data Collection**:
```javascript
// Listen to animation player tick events
window._nadoc?.animPlayer?.addEventListener('tick', e => {
  console.log('t:', e.currentTime.toFixed(2), 'cam pos:', camera.position.toArray().map(v => v.toFixed(2)))
})
```

**Pass Criteria**: Camera moves smoothly. No jump cuts. `tick` events fire at ~60fps.

**Fail → Iteration 5.1a**: If camera jumps, `_buildSchedule()` has incorrect timing. Check keyframe duration math in `animation_player.js`.

---

### Experiment 5.2 — Config animation interpolates cluster positions

**Hypothesis**: An animation with two cluster configurations (cluster at position A → position B) smoothly interpolates cluster helix positions and crossover lines between keyframes.

**Test Steps**:
1. Create two clusters with 3 helices each
2. Capture config A (clusters at origin)
3. Move cluster 1 by +5nm in X, capture config B
4. Create animation: config A → transition 2s → config B
5. Play — observe cluster lerp

**Data Collection**: Screenshot at t=0, t=1s, t=2s. Check crossover lines at each frame.

**Pass Criteria**: Cluster moves smoothly; crossover lines between clusters stretch during transition; intra-cluster crossovers move rigidly.

**Fail → Iteration 5.2a**: If cluster doesn't move, `captureClusterBase()` is not saving the correct initial state. Check MAP_ANIMATION.md bug suspect #1.

**Fail → Iteration 5.2b**: If cluster snaps to incorrect position, `_restoreBaseClusters()` identity quaternion math is wrong. Check MAP_ANIMATION.md bug suspect #2.

---

### Experiment 5.3 — Config dropdown race condition

**Hypothesis**: Opening the animation panel immediately after loading a design (within 500ms) correctly populates the config dropdown with any existing configurations.

**Test Steps**:
1. Load `26hb_platform_v3.nadoc` via `POST /design/load`
2. Immediately (< 200ms later) open the animation panel
3. Check config dropdown — does it show existing configurations?

**Data Collection**:
```javascript
// Check if configs are available in store immediately after load
const configs = window._nadoc?.store?.getState()?.configurations
console.log('configs on panel open:', configs?.length)
```

**Pass Criteria**: Dropdown populates correctly even with fast panel open.

**Fail → Iteration 5.3a**: If dropdown is empty, check the timing between `fetchDesign()` resolving and `initConfigPanel()` subscribing to the store. The panel may miss the initial state update. Fix: call `configPanel.refresh()` after design load completes.

---

### Experiment 5.4 — Bounce mode playback

**Hypothesis**: With bounce mode enabled, the animation plays forward to the end, then reverses back to the start, and repeats continuously. Geometry states are correct in reverse.

**Test Steps**:
1. Create a 3-keyframe animation
2. Enable bounce mode
3. Play and observe: forward → reverse → forward
4. At each keyframe in reverse, geometry should match the keyframe's config

**Pass Criteria**: Smooth forward and reverse playback; no geometry glitches in reverse.

**Fail → Iteration 5.4a**: If reverse playback has wrong geometry, `_clusterStateAtIndex()` is computing cluster state incorrectly when walking the feature log backwards. The feature log is linear — walking backwards means seeking to progressively earlier `featureLogIndex` values, not reversing transformations.

---

### Experiment 5.5 — Undo stack not polluted by config updates

**Hypothesis**: Creating or updating a configuration does NOT add an entry to the undo stack (the `feature_log`). Pressing Ctrl-Z after saving a config does not undo the config.

**Test Steps**:
1. Record feature log length before config creation: `feature_log_length_before`
2. Create a new configuration
3. Record feature log length after
4. Press Ctrl-Z
5. Check: config still exists; feature log back to previous length

**Pass Criteria**: Feature log length unchanged after config create. Undo does not remove the config.

**Fail → Iteration 5.5a**: Backend `update_configuration` endpoint calls `set_design()` instead of `set_design_silent()`. Fix: use `set_design_silent()` in the config CRUD handler (MAP_ANIMATION.md bug suspect #4).

---

### Experiment 5.6 — WebM export captures correct geometry

**Hypothesis**: Exporting the animation as WebM produces a video file that shows the correct cluster animation. The exported frames use the geometry at each `seekTo()` position (not stale startup geometry).

**Test Steps**:
1. Create animation with cluster motion
2. Export to WebM
3. Open the WebM file — verify cluster moves in video

**Pass Criteria**: Video shows correct animation.

**Fail → Iteration 5.6a**: If video shows static geometry, `seekTo()` in the export path doesn't trigger a backend geometry persist. Check `animation_player.js::_exportFrame()` — it must await the geometry update before capturing the frame.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_clusterStateAtIndex(featureLogIndex)` walks the feature log from index 0 linearly to compute cluster state at any point. This is O(featureLogIndex). For animations with many feature log entries (long editing sessions), seeking to a late keyframe is slow. Fix: build a sparse index of cluster state at every N-th feature log entry; seek by finding the nearest sparse entry and playing forward from there.
- During animation playback, `designRenderer.rebuild()` is called at each keyframe boundary. This is expensive for large designs. Consider caching the `buildHelixObjects()` output per config state and swapping rather than rebuilding.
- `_buildSchedule()` is O(keyframes) — fast; no optimization needed.
- For 60fps WebM export, each frame needs a geometry update + render. The bottleneck is the backend geometry fetch. Consider pre-baking all frame geometries at export start (MAP_ANIMATION.md `{type: 'baking'}` event), then playing back from cache.

---

## Refactor Plan

*Execute only after all 5.x experiments pass.*

1. **Fix `set_design_silent`**: update `update_configuration` endpoint to use `set_design_silent()`. Write test asserting feature log unchanged.
2. **Fix export seek timing**: add `await seekTo(frameTime)` with a geometry-fetched promise before each frame capture in the export path.
3. **Sparse feature log index**: implement `_buildFeatureLogIndex()` that snapshots cluster state every 50 feature log entries. Use for O(1) seek approximation.
4. **Config panel timing**: add a `refresh()` call from the design-load completion handler.
5. **Performance baseline**: record export time for a 5-second animation on the 26HB fixture.
