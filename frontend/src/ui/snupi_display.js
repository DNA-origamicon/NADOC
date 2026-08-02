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

import { toFemUpdates, flexColorMap, deviationColorMap } from './cando_display.js'
import { framesToUpdates } from './oxdna_display.js'
import { initFrameSteppers } from './frame_steppers.js'

export function initSnupiDisplay({
  designRenderer, api, cylinderOverlay = null, setDesignVisible = null, flexScale = null,
}) {
  let _epoch = 0            // bumps on every request → stale responses ignored
  let _loadAbort = null
  function _beginLoad() {
    _loadAbort?.abort()
    _loadAbort = new AbortController()
    return { epoch: ++_epoch, signal: _loadAbort.signal }
  }
  function _cancelLoad() { _loadAbort?.abort(); _loadAbort = null; _epoch++ }
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

  function _clearAll() {
    flexScale?.hide()
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
    designRenderer.clearExternalGeometry?.()
    _nativeVisible(true)
  }

  function _prepareForExternal() {
    flexScale?.hide()
    cylinderOverlay?.clear()
    designRenderer.clearScalarColors?.()
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

  /** Deform the model to the predicted shape (no recolour). */
  async function showDeform(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getSnupiDisplay(jobId, signal), api.getSnupiSnapshotGeometry(jobId, signal)])
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
  async function showFlex(jobId) {
    const { epoch, signal } = _beginLoad()
    const [disp, rmsf, snap] = await Promise.all([
      api.getSnupiDisplay(jobId, signal), api.getSnupiRmsf(jobId, signal), api.getSnupiSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const map = flexColorMap(disp, rmsf, undefined, undefined, _flexCmap)
    if (!map || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _flexResp = { disp, rmsf }
    _flexBounds = { lo: map.min, hi: map.max }
    _jobId = jobId; _mode = 'flex'
    _stats = { kind: 'flex', min: map.min, max: map.max }
    flexScale?.show({ title: 'RMSF (nm)', min: map.min, max: map.max, mapType: 'flex', onRecolor: _recolorFlex })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max }
  }

  /** Deform to the predicted shape + recolour beads green→red by deviation from the
   *  design's intended geometry (deviation map).  Reports the global RMSD. */
  async function showDeviation(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getSnupiDeviation(jobId, signal), api.getSnupiSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    if (!map || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _devResp = resp
    _devBounds = { lo: map.min, hi: map.max }
    _jobId = jobId; _mode = 'deviation'
    _stats = { kind: 'deviation', min: map.min, max: map.max, rmsd: map.rmsd }
    flexScale?.show({ title: 'Deviation (nm)', min: map.min, max: map.max, mapType: 'deviation', onRecolor: _recolorDeviation })
    return { ok: true, n: map.updates.length, min: map.min, max: map.max, rmsd: map.rmsd }
  }

  /** CanDo-style output: draw the predicted shape as jointed-cylinder tubes (native model hidden). */
  async function showCandoStyle(jobId) {
    const { epoch, signal } = _beginLoad()
    const resp = await api.getSnupiCylinders(jobId, signal)
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
    if (resp.has_rmsf) {
      flexScale?.show({ title: 'RMSF (nm)', min: resp.rmsf_min, max: resp.rmsf_p95, mapType: 'cando', onRecolor: _recolorCando })
    }
    return { ok: true, helices: resp.n_helices, joints: resp.n_joints }
  }

  // ── Trajectory player (dynamics jobs) — animate the actual thermal motion ───────
  let _traj = null           // { keys, frames } payload
  let _trajIdx = 0
  let _trajRaf = null
  let _trajPlaying = false
  let _trajLast = 0
  const _TRAJ_FPS = 12       // playback rate (frames are downsampled snapshots, not real-time)
  const _tel = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null)

  function _trajApplyFrame(idx) {
    if (!_traj || !_traj.frames?.length) return
    _trajIdx = ((idx % _traj.frames.length) + _traj.frames.length) % _traj.frames.length
    designRenderer.applyFemPositions(framesToUpdates(_traj.keys, _traj.frames[_trajIdx]))
    const sc = _tel('snupi-traj-scrubber'); if (sc) sc.value = String(_trajIdx)
    const lbl = _tel('snupi-traj-frame'); if (lbl) lbl.textContent = `${_trajIdx + 1}/${_traj.frames.length}`
    _trajSteppers?.refresh()
  }

  function _trajTick(now) {
    if (!_trajPlaying) return
    if (now - _trajLast >= 1000 / _TRAJ_FPS) { _trajLast = now; _trajApplyFrame(_trajIdx + 1) }
    _trajRaf = requestAnimationFrame(_trajTick)
  }

  function _trajSetPlaying(on) {
    _trajPlaying = on
    const btn = _tel('snupi-traj-play'); if (btn) btn.textContent = on ? '⏸' : '▶'
    if (on) { _trajLast = 0; _trajRaf = requestAnimationFrame(_trajTick) }
    else if (_trajRaf) { cancelAnimationFrame(_trajRaf); _trajRaf = null }
  }

  let _trajWired = false
  let _trajSteppers = null
  function _wireTrajControls() {
    if (_trajWired) return
    _trajWired = true
    _tel('snupi-traj-play')?.addEventListener('click', () => _trajSetPlaying(!_trajPlaying))
    _tel('snupi-traj-scrubber')?.addEventListener('input', (e) => {
      _trajSetPlaying(false); _trajApplyFrame(parseInt(e.target.value, 10) || 0)
    })
    // ◂ / ▸ — one frame at a time; playback wraps, so these do too.
    _trajSteppers = initFrameSteppers({
      prevBtn: _tel('snupi-traj-prev'), nextBtn: _tel('snupi-traj-next'), wrap: true,
      count: () => _traj?.frames?.length || 0, current: () => _trajIdx,
      onStep: (i) => { _trajSetPlaying(false); _trajApplyFrame(i) },
    })
  }

  /** Animate a dynamics job's thermal trajectory (the actual motion, not just its mean shape). */
  async function showTrajectory(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getSnupiTrajectory(jobId, signal), api.getSnupiSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    if (!resp?.ready || !resp.n_frames || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    _traj = { keys: resp.keys, frames: resp.frames }
    _trajIdx = 0
    _wireTrajControls()
    const ctl = _tel('snupi-traj-controls'); if (ctl) ctl.style.display = 'flex'
    const sc = _tel('snupi-traj-scrubber'); if (sc) { sc.max = String(resp.n_frames - 1); sc.value = '0' }
    _trajApplyFrame(0)
    _trajSetPlaying(true)
    _jobId = jobId; _mode = 'trajectory'
    _stats = { kind: 'trajectory', frames: resp.n_frames }
    return { ok: true, frames: resp.n_frames }
  }

  function stopTrajectory() {
    _trajSetPlaying(false)
    _traj = null
    const ctl = _tel('snupi-traj-controls'); if (ctl) ctl.style.display = 'none'
  }

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
    if (_mode === null) return
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
    trajectoryInfo: () => (_mode === 'trajectory' && _traj?.frames?.length)
      ? { frame: _trajIdx + 1, total: _traj.frames.length }
      : null,
    lastStats:    () => _stats,
    coloringInfo: () => {
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
