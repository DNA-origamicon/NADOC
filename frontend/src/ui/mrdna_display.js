/**
 * mrDNA display controller.
 *
 * Mutually-exclusive display modes, all Physical-layer / display-state only
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

import { deviationColorMap, rmsfColorMap, strainColorMap } from './oxdna_display.js'

/**
 * Pure mapping: a /mrdna/jobs/{id}/display response → applyFemPositions updates.
 * Fine display responses include the relaxed duplex frame so slabs follow the
 * reconstructed bases.  Older cached responses remain position-only compatible.
 */
export function toFemUpdates(displayResponse) {
  if (!displayResponse || !displayResponse.ready || !Array.isArray(displayResponse.positions)) {
    return []
  }
  return displayResponse.positions.map((p) => {
    const out = {
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction,
      backbone_position: p.backbone_position,
    }
    if (p.base_position !== undefined) out.base_position = p.base_position
    if (p.copy !== undefined) out.copy = p.copy
    for (const k of ['nx', 'ny', 'nz', 'tx', 'ty', 'tz']) {
      if (p[k] !== undefined) out[k] = p[k]
    }
    return out
  })
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

function _confidence(resp) {
  const confidence = resp?.confidence
  if (!confidence?.lower_confidence) return null
  return {
    direct: Number(confidence.direct) || 0,
    interpolated: Number(confidence.interpolated) || 0,
    lowerConfidence: true,
  }
}

export function initMrdnaDisplay({
  designRenderer, api, beadOverlay = null, connectionOverlay = null,
  setDesignVisible = null, flexScale = null,
}) {
  let _epoch = 0                 // bumps on every request → stale responses ignored
  let _deformJobId = null        // job whose relaxed positions are applied (or null)
  let _beadsJobId  = null        // job whose bead cloud is drawn (or null)
  let _mode = null
  let _stats = null
  let _rmsfResp = null
  let _devResp = null
  let _strainResp = null
  let _rmsfCmap = 'viridis'
  let _devCmap = 'devramp'
  let _strainCmap = 'coolwarm'
  let _loadAbort = null
  function _beginLoad() {
    _loadAbort?.abort()
    _loadAbort = new AbortController()
    return { epoch: ++_epoch, signal: _loadAbort.signal }
  }
  function _cancelLoad() { _loadAbort?.abort(); _loadAbort = null; _epoch++ }

  // Show/hide the native NADOC model (whatever rep) while the CG-beads mode owns
  // the view.  designRenderer.setDesignVisible covers the design root; the injected
  // setDesignVisible (main.js _setDesignGeometryVisible) additionally covers the
  // sibling scene owners (blunt-ends, arcs, joint/extrude handles).
  function _nativeVisible(v) {
    if (setDesignVisible) setDesignVisible(v)
    else designRenderer?.setDesignVisible?.(v)
  }

  function _snapshotReady(snap) {
    return !!(snap?.ready && snap.design && snap.nucleotides?.length)
  }

  function _renderSnapshot(snap) {
    const axes = {}
    for (const ax of snap.helix_axes ?? []) axes[ax.helix_id] = {
      start: ax.start, end: ax.end, samples: ax.samples ?? null,
      ovhgAxes: ax.ovhg_axes ?? null, segments: ax.segments ?? null,
    }
    designRenderer.renderExternalGeometry(snap.design, snap.nucleotides, axes)
  }

  function _clearVisuals() {
    flexScale?.hide()
    beadOverlay?.update([], _BEAD_RADIUS_NM, 0.95)
    connectionOverlay?.clear()
    designRenderer.applyFemPositions?.(null)
    designRenderer.clearScalarColors?.()
    designRenderer.clearExternalGeometry?.()
    _nativeVisible(true)
    _deformJobId = null
    _beadsJobId = null
    _mode = null
    _stats = null
  }

  function _prepareSnapshot(snap) {
    beadOverlay?.update([], _BEAD_RADIUS_NM, 0.95)
    connectionOverlay?.clear()
    _nativeVisible(true)
    designRenderer.clearScalarColors?.()
    _renderSnapshot(snap)
    _beadsJobId = null
  }

  async function showDeform(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getMrdnaDisplay(jobId, signal), api.getMrdnaSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const updates = toFemUpdates(resp)
    if (!updates.length || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareSnapshot(snap)
    designRenderer.applyFemPositions(updates)
    _deformJobId = jobId
    _mode = 'deform'; _stats = { kind: 'deform', confidence: _confidence(resp) }
    return { ok: true, n: updates.length, ..._stats }
  }

  function _recolorRmsf(lo, hi, cmap) {
    if (_mode !== 'flex' || !_rmsfResp) return
    if (cmap) _rmsfCmap = cmap
    const map = rmsfColorMap(_rmsfResp, lo, hi, _rmsfCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }

  function _recolorDeviation(lo, hi, cmap) {
    if (_mode !== 'deviation' || !_devResp) return
    if (cmap) _devCmap = cmap
    const map = deviationColorMap(_devResp, lo, hi, _devCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }

  function _recolorStrain(lo, hi, cmap) {
    if (_mode !== 'strain' || !_strainResp) return
    if (cmap) _strainCmap = cmap
    const map = strainColorMap(_strainResp, lo, hi, _strainCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }

  async function showFlex(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, display, snap] = await Promise.all([
      api.getMrdnaRmsf(jobId, signal), api.getMrdnaDisplay(jobId, signal),
      api.getMrdnaSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const map = rmsfColorMap(resp, undefined, undefined, _rmsfCmap)
    const relaxed = toFemUpdates(display)
    if (!map || !relaxed.length || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareSnapshot(snap)
    // Scalar profiles contain only keys shared by every sampled frame. Applying
    // those partial mean coordinates mixes relaxed and native endpoints and draws
    // design-spanning cones. Keep one complete, bond-coherent final relaxed shape;
    // the RMSF payload supplies colours only.
    designRenderer.applyFemPositions(relaxed)
    designRenderer.applyScalarColors(map.colorByKey)
    _rmsfResp = resp
    _deformJobId = jobId; _mode = 'flex'
    _stats = { kind: 'flex', min: map.min, max: map.max, mean: resp.mean_rmsf, nFrames: resp.n_frames,
      confidence: _confidence(resp) ?? _confidence(display) }
    flexScale?.show({ title: 'RMSF (nm)', min: map.min, max: map.max, mapType: 'flex', onRecolor: _recolorRmsf })
    return { ok: true, ..._stats }
  }

  async function showDeviation(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, display, snap] = await Promise.all([
      api.getMrdnaDeviation(jobId, signal), api.getMrdnaDisplay(jobId, signal),
      api.getMrdnaSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    const relaxed = toFemUpdates(display)
    if (!map || !relaxed.length || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareSnapshot(snap)
    designRenderer.applyFemPositions(relaxed)
    designRenderer.applyScalarColors(map.colorByKey)
    _devResp = resp
    _deformJobId = jobId; _mode = 'deviation'
    _stats = { kind: 'deviation', min: map.min, max: map.max, rmsd: resp.rmsd_nm,
      mean: resp.mean_deviation, confidence: _confidence(resp) ?? _confidence(display) }
    flexScale?.show({ title: 'Deviation (nm)', min: map.min, max: map.max, mapType: 'deviation', onRecolor: _recolorDeviation })
    return { ok: true, ..._stats }
  }

  async function showStrain(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, display, snap] = await Promise.all([
      api.getMrdnaStrain(jobId, signal), api.getMrdnaDisplay(jobId, signal),
      api.getMrdnaSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const map = strainColorMap(resp, undefined, undefined, _strainCmap)
    const relaxed = toFemUpdates(display)
    if (!map || !relaxed.length || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareSnapshot(snap)
    designRenderer.applyFemPositions(relaxed)
    designRenderer.applyScalarColors(map.colorByKey)
    _strainResp = resp
    _deformJobId = jobId; _mode = 'strain'
    _stats = { kind: 'strain', min: map.min, max: map.max, n: resp.n,
      confidence: _confidence(resp) ?? _confidence(display) }
    flexScale?.show({ title: 'Backbone strain', min: map.min, max: map.max,
      mapType: 'strain', onRecolor: _recolorStrain })
    return { ok: true, ..._stats }
  }

  function stopDeform() {
    _cancelLoad()
    if (_mode === null) return
    _clearVisuals()
  }

  async function showBeads(jobId) {
    const { epoch, signal } = _beginLoad()
    const resp = await api.getMrdnaBeads(jobId, signal)
    if (epoch !== _epoch) return { ok: false }
    const pts = beadsToPoints(resp)
    if (!pts.length || !beadOverlay) return { ok: false, reason: 'not-ready' }
    const edges = edgesFrom(resp)
    _clearVisuals()
    beadOverlay.update(pts, _BEAD_RADIUS_NM, 0.95)
    connectionOverlay?.update(pts, edges)
    // Standalone CG rep: hide the native model so only beads + connections show.
    _nativeVisible(false)
    _beadsJobId = jobId
    _mode = 'beads'; _stats = { kind: 'beads', n: pts.length, edges: edges.length,
      confidence: _confidence(resp) }
    return { ok: true, n: pts.length, edges: edges.length }
  }

  function hideBeads() {
    _cancelLoad()
    if (_beadsJobId === null) return
    _clearVisuals()
  }

  /** Restore everything (deform + beads) — used when leaving the tab / job. */
  function stopAndRestore() {
    _cancelLoad()
    _clearVisuals()
  }

  return {
    showDeform,
    showFlex,
    showDeviation,
    showStrain,
    stopDeform,
    showBeads,
    hideBeads,
    stopAndRestore,
    deformActive: () => _deformJobId !== null,
    beadsActive:  () => _beadsJobId !== null,
    deformJobId:  () => _deformJobId,
    beadsJobId:   () => _beadsJobId,
    mode:         () => _mode,
    lastStats:    () => _stats,
  }
}
