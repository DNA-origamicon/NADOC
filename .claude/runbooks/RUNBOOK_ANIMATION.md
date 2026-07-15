# animation — diagnostics runbook
Loaded on demand from the `animation` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

## Symptoms
- Configuration dropdown in animation panel is empty (no configs appear)
- Cluster doesn't animate / jumps to wrong position on playback
- "Go To" config button does nothing
- Animation export produces wrong geometry
- Config capture button does nothing / captures wrong state
- slerp produces identity (no rotation interpolation)

## Status Context
- Phase 1 (camera poses) + Phase 2 (keyframe playback) are STABLE
- Phase 3 (configurations + cluster animation) is IMPLEMENTED but has known bugs — test end-to-end before assuming it works

## Known Bug Suspects (Phase 3, in order of likelihood)

1. **captureClusterBase append mode vs renderer rebuild** — `captureClusterBase(append=true)` is called to snapshot cluster transform matrices. If the renderer rebuilt between capture and animation playback, the base matrices are invalid. Check whether `helix_renderer.buildHelixObjects()` clears `_clusterBases`.

2. **_restoreBaseClusters identity quaternion** — slerp from identity `[0,0,0,1]` → target rotation may produce wrong interpolation if identity is not handled correctly. Check that base quaternion is actually `[0,0,0,1]` vs a properly captured rotation.

3. **Config dropdown timing** — `initConfigPanel` runs at main.js ~line 3511. If `store.currentDesign` already has configurations at that point (loaded design), the panel may not populate. Check if `initConfigPanel` subscribes to store and populates on design load.

4. **`set_design_silent` missing on `update_configuration`** — If `PATCH /design/configurations/{id}` uses `mutate_and_validate` instead of `set_design_silent` inside a `snapshot()` bracket, each config update pushes to undo. This pollutes the undo stack during animations.

5. **seekTo doesn't trigger backend persist** — `animPlayer.seekTo(t)` moves frontend state but does NOT call any API. For export, the exporter must call `api.goToConfiguration(configId)` explicitly to get correct geometry from backend.

## Diagnosis Tree

### Config dropdown empty
1. Open browser console, check for errors during `initConfigPanel`
2. Check `store.currentDesign.configurations` — does it have entries?
3. If yes but dropdown empty → `initConfigPanel` didn't re-render on design load
4. Find where `initConfigPanel` populates the dropdown and check if it subscribes to `currentDesign`

### "Go To" config does nothing
1. Check `api.goToConfiguration(configId)` is defined in `client.js`
2. Check `POST /design/configurations/{id}/go-to` or similar endpoint exists in `crud.py`
3. Check that cluster transforms are actually in `design.configurations[id].entries`

### Cluster jumps to wrong position
1. Check `captureClusterBase` was called before animation started (not after renderer rebuild)
2. Check slerp: `quaternionSlerp(base.rotation, target.rotation, t)` — verify base != target accidentally
3. Check `_restoreBaseClusters()` is called on `stop()` — otherwise clusters stay at interpolated position

### Export wrong geometry
1. `exportVideo` captures canvas frames during playback
2. If backend geometry doesn't match frontend display → check that `api.getGeometry()` is called at each keyframe during export
3. Or: `seekTo(t)` must trigger a backend update for the current cluster config
