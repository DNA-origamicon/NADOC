/**
 * BLADE display controller.
 *
 * Drives the two display modes a BLADE relax can honestly support:
 *   • Relaxed shape (deform) — the settled structure, i.e. the LAST frame of the relax.
 *   • Trajectory — play back the relaxation itself, idealized geometry settling under
 *     implicit solvent.
 *
 * There is deliberately no flex / deviation / cylinder mode. Those are FEM products: an NMA
 * eigenbasis, a comparison against the intended shape, axis tubes. A relax produces none of
 * them, so offering the modes would mean inventing numbers.
 *
 * Both modes are Physical-layer / display-state only (topology is never touched — Three-Layer
 * Law). They share the one bead-position overlay, so turning one on supersedes the other. Each
 * renders the job's OWN design snapshot (its topology at relax time) in place of the live
 * model, then overlays the relaxed shape on it.
 *
 * Wire-format note: BLADE's compute is atomistic, but `/blade/jobs/{id}/display` serves the
 * settled shape as {keys, frame} in the SAME encoding as `/trajectory` (see routes_blade.py),
 * so both modes decode through `framesToUpdates` and neither needs an atomistic renderer path.
 *
 * Factory: initBladeDisplay({ designRenderer, api, setDesignVisible }) → controller
 * (showDeform / showTrajectory / stopTrajectory / refresh / stopDeform / stopAndRestore +
 * deformActive / deformJobId / mode / trajectoryInfo / lastStats).
 */

import { framesToUpdates } from './oxdna_display.js'
import { initFrameSteppers } from './frame_steppers.js'

export function initBladeDisplay({
  designRenderer, api, setDesignVisible = null, restoreDesignVisible = null,
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
  let _mode = null          // 'deform' | 'trajectory' | null
  let _stats = null         // last summary for the panel readout

  function _nativeVisible(v) {
    if (setDesignVisible) setDesignVisible(v)
    else designRenderer?.setDesignVisible?.(v)
  }
  function _restoreNative() {
    if (restoreDesignVisible) restoreDesignVisible()
    else _nativeVisible(true)
  }

  function _clearAll() {
    designRenderer.clearScalarColors?.()
    designRenderer.clearExternalGeometry?.()
    _restoreNative()
  }

  function _prepareForExternal() {
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

  /** Deform the model to the relaxed (settled) shape — the last frame of the relax.
   *
   *  /blade/jobs/{id}/display serves that frame in the trajectory encoding ({keys, frame}),
   *  so this decodes through framesToUpdates exactly as the player does. */
  async function showDeform(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getBladeDisplay(jobId, signal), api.getBladeSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    if (!resp?.ready || !resp.keys?.length || !resp.frame?.length) {
      return { ok: false, reason: 'not-ready' }
    }
    if (!_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    const updates = framesToUpdates(resp.keys, resp.frame)
    if (!updates.length) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    designRenderer.applyFemPositions(updates)
    designRenderer.clearScalarColors?.()
    _jobId = jobId; _mode = 'deform'
    _stats = { kind: 'deform', n: updates.length, summary: resp.summary || null }
    return { ok: true, n: updates.length }
  }

  // ── Trajectory player — animate the relaxation itself ──────────────────────────
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
    const sc = _tel('blade-traj-scrubber'); if (sc) sc.value = String(_trajIdx)
    const lbl = _tel('blade-traj-frame'); if (lbl) lbl.textContent = `${_trajIdx + 1}/${_traj.frames.length}`
    _trajSteppers?.refresh()
  }

  function _trajTick(now) {
    if (!_trajPlaying) return
    if (now - _trajLast >= 1000 / _TRAJ_FPS) { _trajLast = now; _trajApplyFrame(_trajIdx + 1) }
    _trajRaf = requestAnimationFrame(_trajTick)
  }

  function _trajSetPlaying(on) {
    _trajPlaying = on
    const btn = _tel('blade-traj-play'); if (btn) btn.textContent = on ? '⏸' : '▶'
    if (on) { _trajLast = 0; _trajRaf = requestAnimationFrame(_trajTick) }
    else if (_trajRaf) { cancelAnimationFrame(_trajRaf); _trajRaf = null }
  }

  let _trajWired = false
  let _trajSteppers = null
  function _wireTrajControls() {
    if (_trajWired) return
    _trajWired = true
    _tel('blade-traj-play')?.addEventListener('click', () => _trajSetPlaying(!_trajPlaying))
    _tel('blade-traj-scrubber')?.addEventListener('input', (e) => {
      _trajSetPlaying(false); _trajApplyFrame(parseInt(e.target.value, 10) || 0)
    })
    // ◂ / ▸ — one frame at a time; playback wraps, so these do too.
    _trajSteppers = initFrameSteppers({
      prevBtn: _tel('blade-traj-prev'), nextBtn: _tel('blade-traj-next'), wrap: true,
      count: () => _traj?.frames?.length || 0, current: () => _trajIdx,
      onStep: (i) => { _trajSetPlaying(false); _trajApplyFrame(i) },
    })
  }

  /** Animate the relaxation trajectory — idealized geometry settling under implicit solvent. */
  async function showTrajectory(jobId) {
    const { epoch, signal } = _beginLoad()
    const [resp, snap] = await Promise.all([
      api.getBladeTrajectory(jobId, signal), api.getBladeSnapshotGeometry(jobId, signal)])
    if (epoch !== _epoch) return { ok: false }
    if (!resp?.ready || !resp.n_frames || !_snapshotReady(snap)) return { ok: false, reason: 'not-ready' }
    _prepareForExternal()
    _renderExternal(snap)
    _traj = { keys: resp.keys, frames: resp.frames }
    _trajIdx = 0
    _wireTrajControls()
    const ctl = _tel('blade-traj-controls'); if (ctl) ctl.style.display = 'flex'
    const sc = _tel('blade-traj-scrubber'); if (sc) { sc.max = String(resp.n_frames - 1); sc.value = '0' }
    _trajApplyFrame(0)
    _trajSetPlaying(true)
    _jobId = jobId; _mode = 'trajectory'
    _stats = { kind: 'trajectory', frames: resp.n_frames }
    return { ok: true, frames: resp.n_frames }
  }

  function stopTrajectory() {
    _trajSetPlaying(false)
    _traj = null
    const ctl = _tel('blade-traj-controls'); if (ctl) ctl.style.display = 'none'
  }

  /** Re-apply the active mode for the current job (e.g. after a running job completes). */
  async function refresh() {
    if (_mode === null || _jobId === null) return { ok: false, reason: 'inactive' }
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
    // No coloringInfo(): BLADE drives no scalar-colour channel. The photo/export path checks
    // for the method, so omitting it is the correct signal — an empty stub would advertise a
    // colouring that does not exist.
  }
}
