import * as THREE from 'three'

/** Rebake `currentHelixAxes` for `helixIds` so its baked-in cluster transform
 *  matches `newCt` instead of `oldCt`. Plan B's commit/edit path keeps
 *  currentHelixAxes stale (skipGeometry: true), but downstream consumers that
 *  rebuild geometry from helix_axes (notably jointRenderer.rebuildHulls) need
 *  fresh axes to place the hull prism correctly. We apply the inverse of the
 *  old transform then the new one to each axis point, in place — keeping the
 *  outer object reference stable so subscribers that gate on identity don't
 *  fire spurious rebuilds.
 *
 *  Pure given `currentHelixAxes` (mutated in place); the store read lives in
 *  the factory wrapper below so this stays unit-testable. */
export function rebakeHelixAxesForClusterDelta(currentHelixAxes, helixIds, oldCt, newCt) {
  if (!currentHelixAxes || !helixIds?.length || !oldCt || !newCt) return
  const pOld = new THREE.Vector3(...oldCt.pivot)
  const tOld = new THREE.Vector3(...oldCt.translation)
  const rOldInv = new THREE.Quaternion(...oldCt.rotation).invert()
  const pNew = new THREE.Vector3(...newCt.pivot)
  const tNew = new THREE.Vector3(...newCt.translation)
  const rNew = new THREE.Quaternion(...newCt.rotation)
  const _tmp = new THREE.Vector3()
  const xform = (p) => {
    _tmp.set(p[0], p[1], p[2]).sub(pOld).sub(tOld).applyQuaternion(rOldInv).add(pOld)
    _tmp.sub(pNew).applyQuaternion(rNew).add(pNew).add(tNew)
    return [_tmp.x, _tmp.y, _tmp.z]
  }
  const xformDir = (d) => {
    _tmp.set(d[0], d[1], d[2]).applyQuaternion(rOldInv).applyQuaternion(rNew)
    return [_tmp.x, _tmp.y, _tmp.z]
  }
  for (const hid of helixIds) {
    const ax = currentHelixAxes[hid]
    if (!ax) continue
    if (ax.start) ax.start = xform(ax.start)
    if (ax.end)   ax.end   = xform(ax.end)
    if (Array.isArray(ax.samples)) ax.samples = ax.samples.map(xform)
    if (Array.isArray(ax.segments)) {
      ax.segments = ax.segments.map(seg => ({
        ...seg,
        start: seg.start ? xform(seg.start) : seg.start,
        end:   seg.end   ? xform(seg.end)   : seg.end,
      }))
    }
    if (ax.ovhgAxes && typeof ax.ovhgAxes === 'object') {
      for (const ohId of Object.keys(ax.ovhgAxes)) {
        const oa = ax.ovhgAxes[ohId]
        if (!oa) continue
        if (oa.start) oa.start = xform(oa.start)
        if (oa.end)   oa.end   = xform(oa.end)
        if (Array.isArray(oa.samples)) oa.samples = oa.samples.map(xform)
        if (oa.direction) oa.direction = xformDir(oa.direction)
      }
    }
  }
}

/**
 * Backend response-delta application: the in-place renderer update for every
 * client.js endpoint that goes through `_syncClusterOnlyDiff` /
 * `_syncPositionsOnlyDiff` (undo, redo, seek, delete-feature, edit-feature,
 * relaxLinker, …). Registered once via `api.registerResponseDeltaHandler`, so
 * each endpoint gets the in-place update for free, without per-endpoint
 * main.js wrappers.
 */
export function initResponseDelta({
  store,
  api,
  designRenderer,
  getJointRenderer,
  bluntEnds,
  unfoldView,
  flexibleArcs,
  overhangLinkArcs,
  overhangLocations,
  overhangNameOverlay,
  loopSkipHighlight,
  unligatedCrossoverMarkers,
}) {
  const rebakeFromStore = (helixIds, oldCt, newCt) =>
    rebakeHelixAxesForClusterDelta(store.getState().currentHelixAxes, helixIds, oldCt, newCt)

  /**
   * Re-rebuild the position-derived overlays after an in-place cluster/position
   * mutation whose store update was lean (Plan B), so their currentDesign
   * subscribers fired with stale backbone_position. Single source of truth for
   * this rendering-invariant block, shared by both delta paths here AND the
   * Translate/Rotate tool's commit pipeline in main.js (via the returned API).
   *
   * `withFlexibleArcs` gates the anchor-derived ssDNA-arc rebuild: the delta
   * paths want it (a relax undo/redo must re-apply the arcs), the tool's commit
   * historically did not — pass the caller's existing behavior to stay verbatim.
   */
  function refreshClusterOverlays({ withFlexibleArcs = true } = {}) {
    const s = store.getState()
    const cd = s.currentDesign
    const cg = s.currentGeometry
    const ca = s.currentHelixAxes
    if (!cd || !cg) return
    if (withFlexibleArcs) flexibleArcs?.rebuild?.(cd)
    overhangLinkArcs?.rebuild?.(cd, cg)
    if (overhangLocations?.isVisible?.()) overhangLocations.rebuild(cd, cg)
    // rebuild(geometry, design) — arg order is reversed vs the others.
    if (overhangNameOverlay?.isVisible?.()) overhangNameOverlay.rebuild(cg, cd)
    if (loopSkipHighlight?.isVisible?.()) loopSkipHighlight.rebuild(cd, cg, ca)
    if (unligatedCrossoverMarkers) unligatedCrossoverMarkers.rebuild(cd, cg, s.unligatedCrossoverIds)
  }

  /**
   * Re-emit ds-linker bridge nucs for the moved clusters and patch them in
   * place. Plan B skips backend geometry on a cluster move, so bridge midpoints
   * (derived from live OH anchors via `_emit_bridge_nucs`) go stale — this asks
   * the backend to re-emit just the affected bridges. Single source of truth
   * for that round-trip, shared by both delta paths here AND the
   * Translate/Rotate tool's two commit pipelines in main.js (via the returned
   * API). A failure is swallowed (a tiny round-trip; it must not abort the
   * commit).
   */
  async function reemitClusterBridges(clusterIds) {
    const helixCtrl = designRenderer.getHelixCtrl()
    if (!helixCtrl) return
    try {
      const bridgeNucs = await api.refreshBridges(clusterIds)
      if (bridgeNucs.length) helixCtrl.applyBridgeNucsUpdate(bridgeNucs)
    } catch (e) {
      console.warn('[refreshBridges] failed:', e)
    }
  }

  /**
   * Fast-path renderer update for an undo/redo whose only delta is cluster
   * transforms (signaled by `diff_kind: 'cluster_only'` in the response).
   * Mirrors the cluster-commit Plan B optimisation: avoids the backend full
   * geometry recompute and the design_renderer scene rebuild by composing
   * the existing applyClusterTransform pipeline (which the live-drag and
   * Apply path also use). For each changed cluster, snapshots the current
   * visual state, then applies a delta `(R_new * R_old⁻¹, oldOrigin → newOrigin)`
   * on top — landing each affected mesh at the post-undo/redo position.
   *
   * Backend's `_diff_is_cluster_only` requires pivot to be unchanged across
   * the diff, so the math reduces to a single applyClusterTransform call
   * per cluster (no straight-position resolve needed).
   */
  async function applyClusterUndoRedoDeltas(clusterDiffs) {
    if (!Array.isArray(clusterDiffs) || !clusterDiffs.length) return
    const helixCtrl = designRenderer.getHelixCtrl()
    if (!helixCtrl) return
    const clusterIds = clusterDiffs.map(d => d.cluster_id).filter(Boolean)
    const allHelixIds = new Set()
    let anyAxisRebake = false
    for (const d of clusterDiffs) {
      const helixIds = d.helix_ids ?? []
      if (!helixIds.length) continue
      for (const hid of helixIds) allHelixIds.add(hid)
      const oldQ = new THREE.Quaternion(
        d.old_rotation[0], d.old_rotation[1], d.old_rotation[2], d.old_rotation[3])
      const newQ = new THREE.Quaternion(
        d.new_rotation[0], d.new_rotation[1], d.new_rotation[2], d.new_rotation[3])
      const deltaQ = newQ.clone().multiply(oldQ.clone().invert())
      const oldOrigin = new THREE.Vector3(
        d.old_pivot[0] + d.old_translation[0],
        d.old_pivot[1] + d.old_translation[1],
        d.old_pivot[2] + d.old_translation[2])
      const newOrigin = new THREE.Vector3(
        d.new_pivot[0] + d.new_translation[0],
        d.new_pivot[1] + d.new_translation[1],
        d.new_pivot[2] + d.new_translation[2])
      // Snapshot current visual state as the base for the delta transform.
      // NOTE: jointRenderer and overhangLocations are intentionally omitted
      // here — they auto-rebuild via dedicated subscribers when their
      // backing fields change in currentDesign, which fired synchronously
      // during the preceding _syncClusterOnlyDiff setState. Calling
      // applyClusterTransform on top would double-apply the delta on
      // already-positioned meshes, putting joints/overhangs at the wrong
      // location. Same applies to overhangLinkArcs (rebuilt below).
      helixCtrl.captureClusterBase(helixIds, null)
      bluntEnds?.captureClusterBase?.(helixIds)
      // Apply: world = R_delta * (current - oldOrigin) + newOrigin.
      helixCtrl.applyClusterTransform(helixIds, oldOrigin, newOrigin, deltaQ, null)
      bluntEnds?.applyClusterTransform?.(helixIds, oldOrigin, newOrigin, deltaQ)
      unfoldView?.applyClusterArcUpdate?.(helixIds)
      unfoldView?.applyClusterExtArcUpdate?.(helixIds)
      designRenderer.applyClusterCrossoverUpdate(helixIds)
      // Rebake currentHelixAxes for these helices so jointRenderer.rebuildHulls
      // (called below) reads post-delta axes when constructing the hull prism.
      // Sub-cluster (domain_ids) moves don't rigidly transform the helix —
      // skip the rebake there. cluster_diffs doesn't include domain_ids, so
      // look them up on the live design.
      const liveCt = store.getState().currentDesign?.cluster_transforms?.find(c => c.id === d.cluster_id)
      if (!liveCt?.domain_ids?.length) {
        rebakeFromStore(
          helixIds,
          { pivot: d.old_pivot, translation: d.old_translation, rotation: d.old_rotation },
          { pivot: d.new_pivot, translation: d.new_translation, rotation: d.new_rotation },
        )
        anyAxisRebake = true
      }
    }
    // Sync currentGeometry's nuc.backbone_position / base_normal in-place
    // so downstream consumers see the post-undo/redo positions.
    if (allHelixIds.size) {
      helixCtrl.commitClusterPositions([...allHelixIds])
      if (anyAxisRebake) getJointRenderer()?.rebuildHulls(store.getState().currentDesign)
      // Re-emit ds-linker bridge nucs (Plan B doesn't refresh geometry on
      // undo/redo, so bridge midpoints would otherwise stay frozen at the
      // pre-undo anchor positions). Shared helper — single source of truth.
      await reemitClusterBridges(clusterIds)
      // Refresh overlays whose subscribers fired during the lean store
      // update (with currentGeometry's nuc.backbone_position still stale)
      // — same as the cluster-commit reconciliation in _confirmTranslateRotateTool.
      // Flexible ssDNA arcs are anchor-derived: the cluster delta moved the
      // beads imperatively (Plan B skips geometry) and the currentDesign
      // subscriber's rebuild already ran against the PRE-delta positions, so
      // rebuild them too (undo/redo of a relax must re-apply the arc shape).
      refreshClusterOverlays({ withFlexibleArcs: true })
    }
  }

  /** Apply a positions_only diff to the renderer: walk the per-helix
   * positions arrays into helix_renderer.applyPositionsUpdate, then refresh
   * overlays the same way the cluster-commit reconciliation does. The
   * store has already mutated currentGeometry / currentHelixAxes in place
   * (see _syncPositionsOnlyDiff in client.js), so design_renderer's
   * visual-only-design-change check returns early — no rebuild. */
  function applyPositionsOnlyDiff(json) {
    const helixCtrl = designRenderer.getHelixCtrl()
    if (!helixCtrl) return
    helixCtrl.applyPositionsUpdate(json.positions_by_helix, json.helix_axes)
    // Cross-helix arcs (unfold_view's _arcGroup) and crossover extra-base
    // beads pull from helixCtrl.getNucLivePos() via applyClusterArcUpdate /
    // applyClusterCrossoverUpdate. Live drag refreshes these per frame; for
    // a seek we have to invoke them once with every potentially-affected
    // helix. Topology is unchanged so design.helices covers every real helix
    // (extension and __lnk__ ones inherit through the cluster-arc helpers).
    const cd = store.getState().currentDesign
    const allHelixIds = (cd?.helices ?? []).map(h => h.id)
    if (allHelixIds.length) {
      unfoldView?.applyClusterArcUpdate?.(allHelixIds)
      unfoldView?.applyClusterExtArcUpdate?.(allHelixIds)
      designRenderer.applyClusterCrossoverUpdate(allHelixIds)
    }
    // Overlays that derive positions from currentDesign + currentGeometry
    // need a refresh now that backbone_position has shifted (incl. the
    // anchor-derived flexible ssDNA arcs).
    refreshClusterOverlays({ withFlexibleArcs: true })
  }

  /** Apply whichever delta path the response signals — registered with
   * api.registerResponseDeltaHandler so EVERY client.js endpoint that goes
   * through _syncClusterOnlyDiff / _syncPositionsOnlyDiff (undo, redo, seek,
   * delete-feature, edit-feature, relaxLinker, …) gets the in-place renderer
   * update for free, without per-endpoint main.js wrappers. */
  async function applyResponseDelta(result) {
    if (result?.diff_kind === 'cluster_only') {
      await applyClusterUndoRedoDeltas(result.cluster_diffs)
    } else if (result?.diff_kind === 'positions_only') {
      applyPositionsOnlyDiff(result)
    }
    return result
  }

  return {
    applyResponseDelta,
    applyClusterUndoRedoDeltas,
    applyPositionsOnlyDiff,
    refreshClusterOverlays,
    reemitClusterBridges,
    rebakeHelixAxesForClusterDelta: rebakeFromStore,
  }
}
