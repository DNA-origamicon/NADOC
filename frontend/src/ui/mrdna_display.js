/**
 * mrDNA display controller.
 *
 * Two INDEPENDENT display modes, both Physical-layer / display-state only
 * (topology is never touched):
 *
 *  - "mrDNA display" (showDeform): deform the NADOC model to a job's relaxed
 *    coarse configuration via designRenderer.applyFemPositions(...).
 *  - "CG beads" (showBeads): a STANDALONE coarse-grained representation — draws the
 *    ARBD bead cloud (5 bp/bead) as a sphere overlay AND its bond connectivity
 *    (backbone + crossovers) as line segments, and HIDES the native NADOC model
 *    (whatever rep it's in) via setDesignVisible(false) so only the CG model shows.
 *    Toggling beads off restores the native model.
 *
 * Toggling deform off restores the model via applyFemPositions(null).
 *
 * Factory: initMrdnaDisplay({ designRenderer, api, beadOverlay, connectionOverlay,
 * setDesignVisible }) → controller.
 */

/**
 * Pure mapping: a /mrdna/jobs/{id}/display response → applyFemPositions updates.
 * The coarse reconstruction carries no relaxed base-normal, so nx/ny/nz are
 * omitted — applyFemPositions keeps each base's design orientation and only moves
 * the backbone (option B).  Returns [] for a not-ready / empty response.
 */
export function toFemUpdates(displayResponse) {
  if (!displayResponse || !displayResponse.ready || !Array.isArray(displayResponse.positions)) {
    return []
  }
  return displayResponse.positions.map((p) => ({
    helix_id:          p.helix_id,
    bp_index:          p.bp_index,
    direction:         p.direction,
    backbone_position: p.backbone_position,
  }))
}

/**
 * Pure mapping: a /mrdna/jobs/{id}/beads response → md_overlay point list.
 * Backend beads are [[x,y,z], …] in nm (design frame); md_overlay wants
 * [{x,y,z}].  Returns [] for a not-ready / empty response.
 */
export function beadsToPoints(beadsResponse) {
  if (!beadsResponse || !beadsResponse.ready || !Array.isArray(beadsResponse.beads)) {
    return []
  }
  return beadsResponse.beads.map((b) => ({ x: b[0], y: b[1], z: b[2] }))
}

/**
 * Pure: the bond edges from a /mrdna/jobs/{id}/beads response, kept only when both
 * endpoints index a real bead.  Returns [] when absent.
 */
export function edgesFrom(beadsResponse) {
  const n = Array.isArray(beadsResponse?.beads) ? beadsResponse.beads.length : 0
  if (!beadsResponse?.ready || !Array.isArray(beadsResponse.edges) || n === 0) return []
  return beadsResponse.edges.filter(
    (e) => Array.isArray(e) && e[0] >= 0 && e[1] >= 0 && e[0] < n && e[1] < n,
  )
}

// Coarse mrDNA beads are 5 bp/bead — bigger than the oxDNA P-atom beads.
const _BEAD_RADIUS_NM = 0.55

export function initMrdnaDisplay({
  designRenderer, api, beadOverlay = null, connectionOverlay = null,
  setDesignVisible = null,
}) {
  let _epoch = 0                 // bumps on every request → stale responses ignored
  let _deformJobId = null        // job whose relaxed positions are applied (or null)
  let _beadsJobId  = null        // job whose bead cloud is drawn (or null)

  // Show/hide the native NADOC model (whatever rep) while the CG-beads mode owns
  // the view.  designRenderer.setDesignVisible covers the design root; the injected
  // setDesignVisible (main.js _setDesignGeometryVisible) additionally covers the
  // sibling scene owners (blunt-ends, arcs, joint/extrude handles).
  function _nativeVisible(v) {
    if (setDesignVisible) setDesignVisible(v)
    else designRenderer?.setDesignVisible?.(v)
  }

  async function showDeform(jobId) {
    const epoch = ++_epoch
    const resp = await api.getMrdnaDisplay(jobId)
    if (epoch !== _epoch) return { ok: false }
    const updates = toFemUpdates(resp)
    if (!updates.length) return { ok: false, reason: 'not-ready' }
    designRenderer.applyFemPositions(updates)
    _deformJobId = jobId
    return { ok: true, n: updates.length }
  }

  function stopDeform() {
    if (_deformJobId === null) return
    designRenderer.applyFemPositions(null)
    _deformJobId = null
  }

  async function showBeads(jobId) {
    const epoch = ++_epoch
    const resp = await api.getMrdnaBeads(jobId)
    if (epoch !== _epoch) return { ok: false }
    const pts = beadsToPoints(resp)
    if (!pts.length || !beadOverlay) return { ok: false, reason: 'not-ready' }
    const edges = edgesFrom(resp)
    beadOverlay.update(pts, _BEAD_RADIUS_NM, 0.95)
    connectionOverlay?.update(pts, edges)
    // Standalone CG rep: hide the native model so only beads + connections show.
    _nativeVisible(false)
    _beadsJobId = jobId
    return { ok: true, n: pts.length, edges: edges.length }
  }

  function hideBeads() {
    if (_beadsJobId === null) return
    beadOverlay?.update([], _BEAD_RADIUS_NM, 0.95)
    connectionOverlay?.clear()
    _nativeVisible(true)   // restore the native NADOC model
    _beadsJobId = null
  }

  /** Restore everything (deform + beads) — used when leaving the tab / job. */
  function stopAndRestore() {
    stopDeform()
    hideBeads()
    _epoch++   // invalidate any in-flight fetches
  }

  return {
    showDeform,
    stopDeform,
    showBeads,
    hideBeads,
    stopAndRestore,
    deformActive: () => _deformJobId !== null,
    beadsActive:  () => _beadsJobId !== null,
    deformJobId:  () => _deformJobId,
    beadsJobId:   () => _beadsJobId,
  }
}
