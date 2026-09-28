/**
 * SNUPI FEM display controller.
 *
 * Sibling of cando_display.js — SNUPI is the SAME FEM display path (deform / flex-RMSF /
 * deviation / CanDo-style cylinders), just pointed at the /snupi/* endpoints.  The pure
 * response→colour mappers are byte-identical to CanDo's, so they're imported from
 * cando_display.js (one tested copy) rather than duplicated; only the stateful controller
 * — which reads the SNUPI job's cached FEM frame — is cloned here.
 *
 * All modes are Physical-layer / display-state only (topology is never touched —
 * Three-Layer Law).  They share the one bead-position overlay + scalar-colour channel, so
 * turning one on supersedes the others.  Each renders the job's OWN design snapshot (its
 * topology at solve time) in place of the live model, then overlays the FEM shape on it.
 *
 * Factory: initSnupiDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible,
 * flexScale }) → controller (showDeform / showFlex / showDeviation / showCandoStyle /
 * refresh / stopDeform / stopAndRestore + deformActive / deformJobId / mode / lastStats).
 */

import { initCandoDisplay, toFemUpdates, flexColorMap, deviationColorMap } from './cando_display.js'
import { initSnupiTrajectoryPlayer } from './snupi_trajectory_player.js'
import { LARGE_CANDO_THRESHOLD } from '../scene/cando_large_view.js'
import { parseCandoRepresentativeBin } from '../scene/cando_representative_bin.js'

export function initSnupiDisplay({
  designRenderer, api, cylinderOverlay = null, setDesignVisible = null,
  restoreDesignVisible = null, flexScale = null, largeView = null,
}) {
  let _epoch = 0            // bumps on every request → stale responses ignored
  let _loadAbort = null
  function _beginLoad() {
    _loadAbort?.abort()
    compact.cancelPending()
    player.stop()
    _loadAbort = new AbortController()
    return { epoch: ++_epoch, signal: _loadAbort.signal }
  }
  function _cancelLoad() { _loadAbort?.abort(); _loadAbort = null; _epoch++ }
  function _progress(onProgress, phase, done, total = 1) {
    onProgress?.({ phase, done, total })
  }
  async function _fetchPhase(onProgress, phase, promise) {
    _progress(onProgress, phase, 0)
    const result = await promise
    _progress(onProgress, phase, 1)
    return result
  }
  async function _paintBefore(onProgress, phase) {
    const epoch = _epoch
    _progress(onProgress, phase, 0)
    if (typeof requestAnimationFrame === 'function') {
      await new Promise(resolve => requestAnimationFrame(resolve))
    }
    if (epoch !== _epoch) throw new DOMException('Display superseded', 'AbortError')
  }
  async function _displayRequest(jobId, signal, onProgress) {
    if (api.getSnupiDisplayBin) {
      _progress(onProgress, 'display-download', 0, 0)
      const buf = await api.getSnupiDisplayBin(jobId, {
        signal,
        onProgress: p => _progress(onProgress, 'display-download', p.done, p.total),
      })
      signal.throwIfAborted()
      if (buf) {
        await _paintBefore(onProgress, 'display-decode')
        const decoded = parseCandoRepresentativeBin(buf)
        _progress(onProgress, 'display-decode', 1)
        if (decoded) return {
          ...decoded,
          positions: decoded.representative_positions,
          axis: decoded.representative_axis,
        }
      }
    }
    return _fetchPhase(onProgress, 'display-data', api.getSnupiDisplay(jobId, signal))
  }
  let _jobId = null         // job whose overlay is applied (or null)
  let _mode = null          // 'deform' | 'flex' | 'deviation' | 'cando' | null
  let _stats = null         // last flex/deviation/cando summary for the panel readout
  let _flexResp = null      // { disp, rmsf } for the flex map
  let _devResp = null       // deviation response
  let _candoResp = null     // cylinder response
  let _flexCmap = 'viridis'
  let _devCmap = 'devramp'
  let _candoCmap = 'jet'
  let _flexBounds = null
  let _devBounds = null

  function _nativeVisible(v) {
    if (setDesignVisible) setDesignVisible(v)
    else designRenderer?.setDesignVisible?.(v)
  }
  function _restoreNative() {
    if (restoreDesignVisible) restoreDesignVisible()
    else _nativeVisible(true)
  }

  function _clearAll() {
    flexScale?.hide()
    largeView?.clear()
    _flexResp = null; _devResp = null; _candoResp = null
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    designRenderer.applyFemPositions?.(null)
    designRenderer.clearExternalGeometry?.()
    _restoreNative()
  }

  function _prepareForExternal() {
    flexScale?.hide()
    largeView?.clear()
    _flexResp = null; _devResp = null; _candoResp = null
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    _nativeVisible(true)
  }

  function _prepareForLive() {
    flexScale?.hide()
    largeView?.clear()
    _flexResp = null; _devResp = null; _candoResp = null
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    designRenderer.clearExternalGeometry?.()
    _nativeVisible(true)
  }

  function _snapshotReady(snap) {
    return !!(snap?.ready && snap.design && Array.isArray(snap.nucleotides) && snap.nucleotides.length)
  }

  /** Render a job's OWN design snapshot (its topology at solve time), hiding the live model. */
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

  const compact = initCandoDisplay({ designRenderer, cylinderOverlay, setDesignVisible,
    restoreDesignVisible, flexScale, largeView, api: {
      getCandoJob: api.getSnupiJob, getCandoVisualizationBin: api.getSnupiVisualizationBin,
    } })
  async function _large(jobId, fn, epoch, signal, onProgress, nNucleotides) {
    if (!largeView || !api.getSnupiVisualizationBin) return null
    const n = nNucleotides ?? (await api.getSnupiJob(jobId, signal))?.n_nucleotides
    signal.throwIfAborted()
    if (epoch !== _epoch) throw new DOMException('Display superseded', 'AbortError')
    if (!Number.isFinite(n)) throw new Error('Could not determine result size')
    if (n <= LARGE_CANDO_THRESHOLD) return null
    const result = await compact[fn](jobId, onProgress, { nNucleotides: n })
    if (epoch !== _epoch) throw new DOMException('Display superseded', 'AbortError')
    _jobId = jobId; _mode = compact.mode(); _stats = compact.lastStats()
    _flexResp = null; _devResp = null; _candoResp = null
    return result
  }

  /** Deform the model to the predicted shape (no recolour). */
  async function showDeform(jobId, onProgress, { reuseLiveGeometry = false, nNucleotides } = {}) {
    const { epoch, signal } = _beginLoad()
    const large = await _large(jobId, 'showDeform', epoch, signal, onProgress, nNucleotides)
    if (large) return large
    const [resp, snap] = await Promise.all([
      _displayRequest(jobId, signal, onProgress),
      reuseLiveGeometry ? Promise.resolve(null)
        : _fetchPhase(onProgress, 'snapshot', api.getSnupiSnapshotGeometry(jobId, signal))])
    if (epoch !== _epoch) return { ok: false }
    await _paintBefore(onProgress, 'transform')
    const updates = toFemUpdates(resp)
    _progress(onProgress, 'transform', 1)
    if (!updates.length || (!reuseLiveGeometry && !_snapshotReady(snap))) return { ok: false, reason: 'not-ready' }
    const scenePhase = reuseLiveGeometry ? 'reuse-scene' : 'render-snapshot'
    await _paintBefore(onProgress, scenePhase)
    if (reuseLiveGeometry) _prepareForLive()
    else { _prepareForExternal(); _renderExternal(snap) }
    _progress(onProgress, scenePhase, 1)
    await _paintBefore(onProgress, 'apply')
    designRenderer.applyFemPositions(updates)
    designRenderer.clearScalarColors?.()
    _progress(onProgress, 'apply', 1)
    _jobId = jobId; _mode = 'deform'; _stats = null
    return { ok: true, n: updates.length }
  }

  // ── Live recolour hooks driven by the shared workspace scale widget ──────────
  function _recolorFlex(lo, hi, cmap) {
    if (_mode !== 'flex' || !_flexResp) return
    if (cmap) _flexCmap = cmap
    _flexBounds = { lo, hi }
    const map = flexColorMap(_flexResp.disp, _flexResp.rmsf, lo, hi, _flexCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }
  function _recolorDeviation(lo, hi, cmap) {
    if (_mode !== 'deviation' || !_devResp) return
    if (cmap) _devCmap = cmap
    _devBounds = { lo, hi }
    const map = deviationColorMap(_devResp, lo, hi, _devCmap)
    if (map) designRenderer.applyScalarColors(map.colorByKey)
  }
  function _recolorCando(lo, hi, cmap) {
    if (_mode !== 'cando' || !_candoResp) return
    if (cmap) _candoCmap = cmap
    cylinderOverlay?.recolor(lo, hi, _candoCmap)
  }

  /** Deform to the predicted shape + recolour beads by per-bp RMSF (flexibility map). */
  async function showFlex(jobId, onProgress, { reuseLiveGeometry = false, nNucleotides } = {}) {
    const { epoch, signal } = _beginLoad()
    const large = await _large(jobId, 'showFlex', epoch, signal, onProgress, nNucleotides)
    if (large) return large
    const [disp, rmsf, snap] = await Promise.all([
      _displayRequest(jobId, signal, onProgress),
      _fetchPhase(onProgress, 'rmsf', api.getSnupiRmsf(jobId, signal)),
      reuseLiveGeometry ? Promise.resolve(null)
        : _fetchPhase(onProgress, 'snapshot', api.getSnupiSnapshotGeometry(jobId, signal))])
    if (epoch !== _epoch) return { ok: false }
    await _paintBefore(onProgress, 'transform')
    const map = flexColorMap(disp, rmsf, undefined, undefined, _flexCmap)
    _progress(onProgress, 'transform', 1)
    if (!map || (!reuseLiveGeometry && !_snapshotReady(snap))) return { ok: false, reason: 'not-ready' }
    const scenePhase = reuseLiveGeometry ? 'reuse-scene' : 'render-snapshot'
    await _paintBefore(onProgress, scenePhase)
    if (reuseLiveGeometry) _prepareForLive()
    else { _prepareForExternal(); _renderExternal(snap) }
    _progress(onProgress, scenePhase, 1)
    await _paintBefore(onProgress, 'apply')
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _progress(onProgress, 'apply', 1)
    _flexResp = { disp, rmsf }
    _flexBounds = { lo: map.min, hi: map.max }
    _jobId = jobId; _mode = 'flex'
    _stats = { kind: 'flex', min: map.min, max: map.max }
    flexScale?.show({ title: 'RMSF (nm)', min: map.min, max: map.max, mapType: 'flex', onRecolor: _recolorFlex })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max }
  }

  /** Deform to the predicted shape + recolour beads green→red by deviation from the
   *  design's intended geometry (deviation map).  Reports the global RMSD. */
  async function showDeviation(jobId, onProgress, { reuseLiveGeometry = false, nNucleotides } = {}) {
    const { epoch, signal } = _beginLoad()
    const large = await _large(jobId, 'showDeviation', epoch, signal, onProgress, nNucleotides)
    if (large) return large
    const [resp, snap] = await Promise.all([
      _fetchPhase(onProgress, 'deviation', api.getSnupiDeviation(jobId, signal)),
      reuseLiveGeometry ? Promise.resolve(null)
        : _fetchPhase(onProgress, 'snapshot', api.getSnupiSnapshotGeometry(jobId, signal))])
    if (epoch !== _epoch) return { ok: false }
    await _paintBefore(onProgress, 'transform')
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    _progress(onProgress, 'transform', 1)
    if (!map || (!reuseLiveGeometry && !_snapshotReady(snap))) return { ok: false, reason: 'not-ready' }
    const scenePhase = reuseLiveGeometry ? 'reuse-scene' : 'render-snapshot'
    await _paintBefore(onProgress, scenePhase)
    if (reuseLiveGeometry) _prepareForLive()
    else { _prepareForExternal(); _renderExternal(snap) }
    _progress(onProgress, scenePhase, 1)
    await _paintBefore(onProgress, 'apply')
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _progress(onProgress, 'apply', 1)
    _devResp = resp
    _devBounds = { lo: map.min, hi: map.max }
    _jobId = jobId; _mode = 'deviation'
    _stats = { kind: 'deviation', min: map.min, max: map.max, rmsd: map.rmsd }
    flexScale?.show({ title: 'Deviation (nm)', min: map.min, max: map.max, mapType: 'deviation', onRecolor: _recolorDeviation })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max, rmsd: map.rmsd }
  }

  /** CanDo-style output: draw the predicted shape as jointed-cylinder tubes (native model hidden). */
  async function showCandoStyle(jobId, onProgress, { reuseLiveGeometry = false, nNucleotides } = {}) {
    const { epoch, signal } = _beginLoad()
    const large = await _large(jobId, 'showCandoStyle', epoch, signal, onProgress, nNucleotides)
    if (large) return large
    const resp = await _fetchPhase(onProgress, 'cylinders', api.getSnupiCylinders(jobId, signal))
    if (epoch !== _epoch) return { ok: false }
    if (!resp?.ready || !cylinderOverlay || (!resp.helices?.length && !resp.joints?.length)) {
      return { ok: false, reason: 'not-ready' }
    }
    await _paintBefore(onProgress, 'apply')
    _clearAll()   // restore the live model first, then hide it under the tubes
    cylinderOverlay.update(resp, {
      lo: resp.rmsf_min, hi: resp.rmsf_p95, colormap: _candoCmap,
    })
    _nativeVisible(false)
    _progress(onProgress, 'apply', 1)
    _candoResp = resp
    _jobId = jobId; _mode = 'cando'
    _stats = { kind: 'cando', helices: resp.n_helices || 0, joints: resp.n_joints || 0 }
    if (resp.has_rmsf) {
      flexScale?.show({ title: 'RMSF (nm)', min: resp.rmsf_min, max: resp.rmsf_p95, mapType: 'cando', onRecolor: _recolorCando })
    }
    return { ok: true, helices: resp.n_helices, joints: resp.n_joints }
  }

  const player = initSnupiTrajectoryPlayer({ api, view: largeView,
    onPrepare: () => { _clearAll(); _nativeVisible(false) } })
  async function showTrajectory(jobId, onProgress) {
    const { epoch } = _beginLoad()
    if (!largeView) return { ok: false, reason: 'Trajectory renderer unavailable' }
    _nativeVisible(false)
    const result = await player.show(jobId, onProgress)
    if (epoch !== _epoch) return { ok: false }
    if (result.ok) {
      _jobId = jobId; _mode = 'trajectory'
      _stats = { kind: 'trajectory', frames: result.frames, large: true,
        representation: 'zoom-adaptive nucleotide points; one frame in memory' }
    }
    return result
  }
  function stopTrajectory() { player.stop() }

  /** Re-apply the active mode for the current job (e.g. after a running job completes). */
  async function refresh() {
    if (_mode === null || _jobId === null) return { ok: false, reason: 'inactive' }
    if (_mode === 'flex') return showFlex(_jobId)
    if (_mode === 'deviation') return showDeviation(_jobId)
    if (_mode === 'cando') return showCandoStyle(_jobId)
    if (_mode === 'trajectory') return showTrajectory(_jobId)
    return showDeform(_jobId)
  }

  function stopDeform() {
    _cancelLoad()
    compact.stopDeform()
    stopTrajectory()
    _clearAll()
    _jobId = null; _mode = null; _stats = null
  }

  /** Restore the native model — used when leaving the tab / deleting the job. */
  function stopAndRestore() {
    stopDeform()
  }

  return {
    showDeform,
    showFlex,
    showDeviation,
    showCandoStyle,
    showTrajectory,
    stopTrajectory,
    refresh,
    stopDeform,
    stopAndRestore,
    deformActive: () => _mode !== null,
    deformJobId:  () => _jobId,
    mode:         () => _mode,
    trajectoryInfo: () => _mode === 'trajectory' ? player.info() : null,
    cancelPending: () => { _cancelLoad(); compact.cancelPending(); player.cancelPending(); if (!_mode) { player.stop(); _clearAll() } },
    getBoundingBox: () => largeView?.getBoundingBox?.() ?? null,
    lastStats:    () => _stats,
    coloringInfo: () => {
      if (largeView?.active()) return compact.coloringInfo()
      if (_mode === 'flex' && _flexResp?.disp?.positions?.length) {
        const byBp = new Map((_flexResp.rmsf?.rmsf || []).map(r => [`${r.helix_id}:${r.bp_index}`, r.rmsf_nm]))
        return {
          attribute: 'rmsf', title: 'RMSF', unit: 'nm', colormap: _flexCmap,
          lo: _flexBounds?.lo ?? 0, hi: _flexBounds?.hi ?? 1,
          values: _flexResp.disp.positions.flatMap(p => {
            const value = byBp.get(`${p.helix_id}:${p.bp_index}`)
            return value === undefined ? [] : [{ helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0, value }]
          }),
        }
      }
      if (_mode === 'deviation' && _devResp?.positions?.length) return {
        attribute: 'deviation', title: 'Deviation', unit: 'nm', colormap: _devCmap,
        lo: _devBounds?.lo ?? 0, hi: _devBounds?.hi ?? 1,
        values: _devResp.positions.map(p => ({ helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction, copy: p.copy ?? 0, value: p.deviation })),
      }
      return null
    },
  }
}
