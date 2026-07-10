/**
 * CanDo FEM display controller.
 *
 * Three mutually-exclusive display modes, all Physical-layer / display-state only
 * (topology is never touched — Three-Layer Law).  They share the one bead-position
 * overlay + scalar-colour channel, so turning one on supersedes the others.
 *
 * Each mode renders the job's OWN design snapshot (the topology the design had when
 * the analysis ran — fetched via /cando/jobs/{id}/snapshot-geometry) in place of the
 * live model (designRenderer.renderExternalGeometry), THEN overlays the FEM shape on
 * it.  So a job solved before loops/skips were added still shows its shape on the
 * topology it was solved for, instead of stranding the new (unsolved) beads at native.
 * clearExternalGeometry() restores the live model on toggle-off / tab-leave / edit.
 *
 *  - "Predicted shape (deform model)" (showDeform): deform the NADOC model to a
 *    job's FEM-predicted configuration via designRenderer.applyFemPositions(...).
 *  - "Flexibility map (RMSF)" (showFlex): deform to the predicted shape AND recolour
 *    each backbone bead by its per-bp RMSF (rigid = dark, flexible = bright) via
 *    designRenderer.applyScalarColors(...).  RMSF comes from the free-free NMA.
 *  - "Deviation from design" (showDeviation): deform to the predicted shape AND
 *    recolour each bead green→red by how far the FEM prediction lands from the
 *    design's INTENDED (displayed) geometry.  Reports the global RMSD.
 *
 * Coarse (linear) and Fine (nonlinear) jobs both land here — the solver mode is
 * baked into the job's cached positions, so the display path is identical.
 * Toggling off restores the model via applyFemPositions(null) + clearScalarColors().
 *
 * Sibling of mrdna_display.js / oxdna_display.js.  Factory:
 * initCandoDisplay({ designRenderer, api }) → controller (showDeform / showFlex /
 * showDeviation / stopDeform / stopAndRestore / refresh + deformActive / deformJobId
 * / mode / lastStats).
 */

import { colormapHex } from './colormaps.js'

/**
 * Pure mapping: a /cando/jobs/{id}/display response → applyFemPositions updates.
 * When the FEM display carries the WOUND slab frame (nx/ny/nz base-normal + tx/ty/tz
 * axis-tangent — newer job caches), those are threaded through so applyFemPositions
 * reorients each base slab to follow the wound backbone (fixes slabs splaying radially
 * on a bent/mark-dense bundle).  Older caches omit them → slabs keep their design
 * orientation (option B, backward-compatible).  Returns [] for a not-ready response.
 */
export function toFemUpdates(displayResponse) {
  if (!displayResponse || !displayResponse.ready || !Array.isArray(displayResponse.positions)) {
    return []
  }
  return displayResponse.positions.map((p) => _femUpdate(p))
}

/** One position dict → an applyFemPositions update, threading the wound slab frame
 *  (nx/ny/nz + tx/ty/tz) only when present. */
function _femUpdate(p) {
  const u = {
    helix_id:          p.helix_id,
    bp_index:          p.bp_index,
    direction:         p.direction,
    copy:              p.copy ?? 0,   // loop-copy index → addresses the exact loop bead
    backbone_position: p.backbone_position,
  }
  if (p.nx !== undefined) { u.nx = p.nx; u.ny = p.ny; u.nz = p.nz }
  if (p.tx !== undefined) { u.tx = p.tx; u.ty = p.ty; u.tz = p.tz }
  return u
}

// ── Colour ramps (pure) ───────────────────────────────────────────────────────
// Sourced from the shared colormap registry so the CanDo maps, the workspace scale
// legend, and the colormap picker can never drift apart.  t∈[0,1].

/** viridis (rigid→flexible) hex for t∈[0,1]. */
export function viridisHex(t) { return colormapHex('viridis', t) }
/** green→red (matches design → far from design) hex for t∈[0,1]. */
export function deviationHex(t) { return colormapHex('devramp', t) }

/** Scalar-colour key for a nucleotide: the 4-part "helix:bp:dir:copy" that
 *  helix_renderer.applyScalarColors keys on (so each LOOP COPY colours its own bead),
 *  plus the 3-part alias for copy 0 (crossover-arc recolour, which lands on the base). */
function _putColor(colorByKey, helix, bp, dir, copy, hex) {
  colorByKey[`${helix}:${bp}:${dir}:${copy}`] = hex
  if (copy === 0) colorByKey[`${helix}:${bp}:${dir}`] = hex
}

/**
 * Pure: a /cando/jobs/{id}/display response + a /cando/jobs/{id}/rmsf response →
 * { updates, colorByKey, min, max }.  Positions come from the display list (every
 * nucleotide); each is coloured by the RMSF of its (helix, bp) — RMSF is per axis
 * node (direction-independent), so both strands + gap-filled loop bases of a bp
 * share the colour.  Uncovered bp (no RMSF node) are left uncoloured (keep design
 * colour).  Scaled over [lo,hi] (default: the design's own RMSF min→max).
 */
export function flexColorMap(displayResp, rmsfResp, loBound, hiBound, cmap = 'viridis') {
  const updates = toFemUpdates(displayResp)
  if (!updates.length || !rmsfResp?.rmsf?.length) return null
  const byBp = new Map()
  for (const r of rmsfResp.rmsf) byBp.set(`${r.helix_id}:${r.bp_index}`, r.rmsf_nm)
  const dataLo = Number.isFinite(rmsfResp.min_nm) ? rmsfResp.min_nm : 0
  const dataHi = Number.isFinite(rmsfResp.max_nm) ? rmsfResp.max_nm : 0
  const lo = Number.isFinite(loBound) ? loBound : dataLo
  const hi = Number.isFinite(hiBound) ? hiBound : dataHi
  const span = hi - lo
  const colorByKey = {}
  for (const u of updates) {
    const val = byBp.get(`${u.helix_id}:${u.bp_index}`)
    if (val === undefined) continue                       // uncovered → keep design colour
    const t = span > 1e-9 ? (val - lo) / span : 0.0
    // RMSF is per axis node (direction- + copy-independent), so a bp's loop copies all
    // take that bp's colour — but keyed by their own copy so each loop bead recolours.
    _putColor(colorByKey, u.helix_id, u.bp_index, u.direction, u.copy ?? 0, colormapHex(cmap, t))
  }
  return { updates, colorByKey, min: dataLo, max: dataHi }
}

/**
 * Pure: a /cando/jobs/{id}/deviation response → { updates, colorByKey, min, max, rmsd }.
 * Positions + per-nucleotide `deviation` come from the same list; each bead is
 * coloured green→red over [0, max deviation] (0 anchored so "matches design" always
 * reads green).  Returns null for a not-ready / empty response.
 */
export function deviationColorMap(devResp, loBound, hiBound, cmap = 'devramp') {
  if (!devResp || !devResp.ready || !Array.isArray(devResp.positions) || !devResp.positions.length) {
    return null
  }
  const dataHi = Number.isFinite(devResp.max_deviation) ? devResp.max_deviation : 0
  // Default scale is 0-anchored [0, max] so "matches design" always reads as the ramp
  // start; the scale widget may override with an explicit [lo, hi] window.
  const lo = Number.isFinite(loBound) ? loBound : 0
  const hi = Number.isFinite(hiBound) ? hiBound : dataHi
  const span = hi - lo
  const updates = []
  const colorByKey = {}
  for (const p of devResp.positions) {
    const copy = p.copy ?? 0
    updates.push(_femUpdate(p))   // carries the wound slab frame (nx/ny/nz + tx/ty/tz) when present
    const t = span > 1e-9 ? (p.deviation - lo) / span : 0.0
    _putColor(colorByKey, p.helix_id, p.bp_index, p.direction, copy, colormapHex(cmap, t))
  }
  return {
    updates, colorByKey,
    min: Number.isFinite(devResp.min_deviation) ? devResp.min_deviation : 0,
    max: dataHi,
    rmsd: Number.isFinite(devResp.rmsd_nm) ? devResp.rmsd_nm : 0,
  }
}

export function initCandoDisplay({
  designRenderer, api, cylinderOverlay = null, setDesignVisible = null, flexScale = null,
}) {
  let _epoch = 0            // bumps on every request → stale responses ignored
  let _jobId = null         // job whose overlay is applied (or null)
  let _mode = null          // 'deform' | 'flex' | 'deviation' | 'cando' | null
  let _stats = null         // last flex/deviation/cando summary for the panel readout
  // Cached responses so the workspace scale widget can recolour / rescale live
  // without a re-fetch, plus the active per-map colormap.
  let _flexResp = null      // { disp, rmsf } for the flex map
  let _devResp = null       // deviation response
  let _candoResp = null     // cylinder response
  let _flexCmap = 'viridis'
  let _devCmap = 'devramp'
  let _candoCmap = 'jet'

  // Show/hide the native NADOC model while the CanDo-style cylinder rep owns the view
  // (mirrors the mrDNA CG-beads mode).  The injected setDesignVisible (main.js
  // _setDesignGeometryVisible) also covers arcs / blunt-ends; fall back to the design
  // root alone if it wasn't provided.
  function _nativeVisible(v) {
    if (setDesignVisible) setDesignVisible(v)
    else designRenderer?.setDesignVisible?.(v)
  }

  // Full restore to the clean LIVE native model — drops whatever the current mode
  // drew (cylinder tubes, scalar recolour, AND the job-snapshot render).  Used when
  // turning a mode off, and before the cylinder mode (which hides the live model).
  function _clearAll() {
    flexScale?.hide()
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    designRenderer.clearExternalGeometry?.()   // rebuilds the live model (no-op if not external)
    _nativeVisible(true)
  }

  // Prepare the scene for an external (job-snapshot) render: clear the previous mode's
  // tubes / colours and make sure visibility isn't left off by the cylinder mode.  The
  // subsequent renderExternalGeometry() rebuilds the model in one pass (no live rebuild).
  function _prepareForExternal() {
    flexScale?.hide()
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    _nativeVisible(true)
  }

  function _snapshotReady(snap) {
    return !!(snap?.ready && snap.design && Array.isArray(snap.nucleotides) && snap.nucleotides.length)
  }

  /** Render a job's OWN design snapshot (its topology at solve time), hiding the live
   *  model, so the FEM overlay below lands on beads that match the solved topology. */
  function _renderExternal(snap) {
    const axes = {}
    for (const ax of snap.helix_axes ?? []) {
      axes[ax.helix_id] = {
        start: ax.start, end: ax.end,
        samples: ax.samples ?? null, ovhgAxes: ax.ovhg_axes ?? null, segments: ax.segments ?? null,
      }
    }
    designRenderer.renderExternalGeometry(snap.design, snap.nucleotides, axes)
  }

  /** Deform the model to the predicted shape (no recolour). */
  async function showDeform(jobId) {
    const epoch = ++_epoch
    const [resp, snap] = await Promise.all([
      api.getCandoDisplay(jobId), api.getCandoSnapshotGeometry(jobId)])
    if (epoch !== _epoch) return { ok: false }
    const updates = toFemUpdates(resp)
    if (!updates.length || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(updates)
    designRenderer.clearScalarColors?.()
    _jobId = jobId; _mode = 'deform'; _stats = null
    return { ok: true, n: updates.length }
  }

  // ── Live recolour hooks driven by the shared workspace scale widget ──────────
  function _recolorFlex(lo, hi, cmap) {
    if (_mode !== 'flex' || !_flexResp) return
    if (cmap) _flexCmap = cmap
    const map = flexColorMap(_flexResp.disp, _flexResp.rmsf, lo, hi, _flexCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }
  function _recolorDeviation(lo, hi, cmap) {
    if (_mode !== 'deviation' || !_devResp) return
    if (cmap) _devCmap = cmap
    const map = deviationColorMap(_devResp, lo, hi, _devCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }
  function _recolorCando(lo, hi, cmap) {
    if (_mode !== 'cando' || !_candoResp) return
    if (cmap) _candoCmap = cmap
    cylinderOverlay?.recolor(lo, hi, _candoCmap)
  }

  /** Deform to the predicted shape + recolour beads by per-bp RMSF (flexibility map). */
  async function showFlex(jobId) {
    const epoch = ++_epoch
    const [disp, rmsf, snap] = await Promise.all([
      api.getCandoDisplay(jobId), api.getCandoRmsf(jobId), api.getCandoSnapshotGeometry(jobId)])
    if (epoch !== _epoch) return { ok: false }
    const map = flexColorMap(disp, rmsf, undefined, undefined, _flexCmap)
    if (!map || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _flexResp = { disp, rmsf }
    _jobId = jobId; _mode = 'flex'
    _stats = { kind: 'flex', min: map.min, max: map.max }
    // Hand the shared scale widget this map's range + a live recolour callback; it
    // reconciles the on-structure colours to the remembered colormap on show.
    flexScale?.show({ title: 'RMSF (nm)', min: map.min, max: map.max, mapType: 'flex', onRecolor: _recolorFlex })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max }
  }

  /** Deform to the predicted shape + recolour beads green→red by deviation from the
   *  design's intended geometry (deviation map).  Reports the global RMSD. */
  async function showDeviation(jobId) {
    const epoch = ++_epoch
    const [resp, snap] = await Promise.all([
      api.getCandoDeviation(jobId), api.getCandoSnapshotGeometry(jobId)])
    if (epoch !== _epoch) return { ok: false }
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    if (!map || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _devResp = resp
    _jobId = jobId; _mode = 'deviation'
    _stats = { kind: 'deviation', min: map.min, max: map.max, rmsd: map.rmsd }
    flexScale?.show({ title: 'Deviation (nm)', min: map.min, max: map.max, mapType: 'deviation', onRecolor: _recolorDeviation })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max, rmsd: map.rmsd }
  }

  /** CanDo-style output: draw the predicted shape as the familiar jointed-cylinder
   *  representation (one grey tube per helix + crossover joints) with the native
   *  NADOC model hidden.  Standalone rep, like the mrDNA CG-beads mode. */
  async function showCandoStyle(jobId) {
    const epoch = ++_epoch
    const resp = await api.getCandoCylinders(jobId)
    if (epoch !== _epoch) return { ok: false }
    if (!resp?.ready || !cylinderOverlay || (!resp.helices?.length && !resp.joints?.length)) {
      return { ok: false, reason: 'not-ready' }
    }
    _clearAll()   // restore the live model first, then hide it under the tubes
    cylinderOverlay.update(resp, {
      lo: resp.rmsf_min, hi: resp.rmsf_p95, colormap: _candoCmap,
    })
    _nativeVisible(false)
    _candoResp = resp
    _jobId = jobId; _mode = 'cando'
    _stats = { kind: 'cando', helices: resp.n_helices || 0, joints: resp.n_joints || 0 }
    // The tubes are an RMSF heat map (min→p95); show the adjustable scale + colormap
    // picker when the job carried RMSF, otherwise the tubes are plain grey.
    if (resp.has_rmsf) {
      flexScale?.show({ title: 'RMSF (nm)', min: resp.rmsf_min, max: resp.rmsf_p95, mapType: 'cando', onRecolor: _recolorCando })
    }
    return { ok: true, helices: resp.n_helices, joints: resp.n_joints }
  }

  /** Re-apply the active mode for the current job (e.g. after a running job completes,
   *  or more of the solve landed).  No-op when nothing is displayed. */
  async function refresh() {
    if (_mode === null || _jobId === null) return { ok: false, reason: 'inactive' }
    if (_mode === 'flex') return showFlex(_jobId)
    if (_mode === 'deviation') return showDeviation(_jobId)
    if (_mode === 'cando') return showCandoStyle(_jobId)
    return showDeform(_jobId)
  }

  function stopDeform() {
    if (_mode === null) return
    _clearAll()
    _jobId = null; _mode = null; _stats = null
  }

  /** Restore the native model — used when leaving the tab / deleting the job. */
  function stopAndRestore() {
    stopDeform()
    _epoch++   // invalidate any in-flight fetch
  }

  return {
    showDeform,
    showFlex,
    showDeviation,
    showCandoStyle,
    refresh,
    stopDeform,
    stopAndRestore,
    deformActive: () => _mode !== null,
    deformJobId:  () => _jobId,
    mode:         () => _mode,
    lastStats:    () => _stats,
  }
}
