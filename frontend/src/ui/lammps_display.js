/**
 * LAMMPS display controller — deform/recolour the NADOC model from a LAMMPS run's
 * visualization endpoints. A lean sibling of oxdna_display.js that runs the LAMMPS
 * data through the SAME validated pure mappers (`toFemUpdates` / `rmsfColorMap` /
 * `deviationColorMap` / `framesToUpdates`) + the SAME `designRenderer` methods, so
 * "different data source, same validated rendering code". LAMMPS is coarse-grained
 * only, so there are no atomistic/surface (heavy-rep) paths — just the CG deform.
 *
 * Four mutually-exclusive views (mirrors the oxDNA card):
 *   display    — the run's final structure (last aligned frame)
 *   rmsf       — average structure recoloured rigid→flexible by per-base RMSF
 *   deviation  — mean structure recoloured green→red by distance from the design
 *   trajectory — scrub every frame (drive showFrame from a player)
 *
 * Factory: initLammpsDisplay({ designRenderer, api? }) → controller.
 * Physical-layer / display-state only (topology is never touched).
 */

import { toFemUpdates, rmsfColorMap, deviationColorMap, framesToUpdates } from './oxdna_display.js'
import * as client from '../api/client.js'

export function initLammpsDisplay({ designRenderer = null, api = client } = {}) {
  let _mode = null          // 'display' | 'rmsf' | 'deviation' | 'trajectory' | null
  let _traj = null          // { keys, frames } while in trajectory mode
  let _trajIdx = 0
  let _jobId = null
  let _rmsfResp = null      // cached payloads so the scale widget can recolour without a re-fetch
  let _devResp = null
  let _rmsfCmap = 'viridis'
  let _devCmap = 'devramp'
  let _rmsfBounds = null
  let _devBounds = null
  let _epoch = 0
  let _loadAbort = null
  function _beginLoad() {
    _loadAbort?.abort()
    _loadAbort = new AbortController()
    return { epoch: ++_epoch, signal: _loadAbort.signal }
  }
  function _cancelLoad() { _loadAbort?.abort(); _loadAbort = null; _epoch++ }

  function _restore() {
    designRenderer?.applyFemPositions(null)
    designRenderer?.clearScalarColors?.()
  }

  async function displayJob(jobId, align = true) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const { epoch, signal } = _beginLoad()
    const resp = await api.getLammpsDisplay(jobId, align, signal)
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    const updates = toFemUpdates(resp)
    if (!updates.length) return { ok: false, reason: resp?.reason || 'not ready' }
    designRenderer.clearScalarColors?.()          // plain positions, no per-base colour
    designRenderer.applyFemPositions(updates)
    _mode = 'display'; _traj = null; _jobId = jobId
    return { ok: true, n: updates.length }
  }

  async function displayRmsf(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const { epoch, signal } = _beginLoad()
    const resp = await api.getLammpsRmsf(jobId, signal)
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    const map = rmsfColorMap(resp, undefined, undefined, _rmsfCmap)
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    _rmsfResp = resp
    _rmsfBounds = { lo: map.min, hi: map.max }
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _mode = 'rmsf'; _traj = null; _jobId = jobId
    return { ok: true, min: map.min, max: map.max, mean: resp.mean_rmsf,
             nFrames: resp.n_frames, confidence: resp.confidence }
  }

  async function displayDeviation(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const { epoch, signal } = _beginLoad()
    const resp = await api.getLammpsDeviation(jobId, signal)
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    const map = deviationColorMap(resp, undefined, undefined, _devCmap)
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    _devResp = resp
    _devBounds = { lo: map.min, hi: map.max }
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _mode = 'deviation'; _traj = null; _jobId = jobId
    return { ok: true, min: map.min, max: map.max, mean: resp.mean_deviation, nFrames: resp.n_frames }
  }

  /** Recolour the active RMSF map to [lo,hi] on colormap `cmap` (scale-widget driven). */
  function recolorRmsf(lo, hi, cmap) {
    if (_mode !== 'rmsf' || !_rmsfResp || !designRenderer) return false
    if (cmap) _rmsfCmap = cmap
    _rmsfBounds = { lo, hi }
    const map = rmsfColorMap(_rmsfResp, lo, hi, _rmsfCmap)
    if (!map) return false
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  /** Recolour the active deviation map to [lo,hi] on colormap `cmap` (scale-widget driven). */
  function recolorDeviation(lo, hi, cmap) {
    if (_mode !== 'deviation' || !_devResp || !designRenderer) return false
    if (cmap) _devCmap = cmap
    _devBounds = { lo, hi }
    const map = deviationColorMap(_devResp, lo, hi, _devCmap)
    if (!map) return false
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  async function loadTrajectory(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const { epoch, signal } = _beginLoad()
    const t = await api.getLammpsTrajectory(jobId, signal)
    if (epoch !== _epoch) return { ok: false, reason: 'superseded' }
    if (!t || !t.ready) { _traj = null; return { ok: false, reason: t?.reason || 'not ready' } }
    _traj = { keys: t.keys, frames: t.frames }
    _mode = 'trajectory'; _jobId = jobId
    designRenderer.clearScalarColors?.()
    showFrame(0)
    return { ok: true, n_frames: t.n_frames, markers: t.markers || [] }
  }

  function showFrame(i) {
    if (_mode !== 'trajectory' || !_traj) return
    const idx = Math.max(0, Math.min(_traj.frames.length - 1, i | 0))
    const f = _traj.frames[idx]
    if (f) _trajIdx = idx
    if (f) designRenderer.applyFemPositions(framesToUpdates(_traj.keys, f))
  }

  function stopAndRestore() {
    _cancelLoad()
    // No-op when nothing is displayed. `_restore()` reverts every backbone bead to
    // the design geometry (applyFemPositions(null) → revertToGeometry), so calling
    // it while inactive CLOBBERS positions this overlay never set — e.g. the live
    // cluster-move preview: a cluster commit fires `nadoc:design-changed`, the panel
    // calls _viewsOff() → stopAndRestore(), and an unconditional restore snapped the
    // moved beads/slabs back to the un-posed geometry while the axis kept the new
    // pose. The sibling displays (oxdna `!_active`, cando/mrdna `_mode/_jobId===null`)
    // already guard this; match them.
    if (_mode === null) return
    _mode = null; _traj = null; _jobId = null
    _restore()
  }

  return {
    displayJob, displayRmsf, displayDeviation, recolorRmsf, recolorDeviation, loadTrajectory, showFrame, stopAndRestore,
    mode: () => _mode, activeJobId: () => _jobId, isActive: () => _mode !== null,
    trajectoryInfo: () => (_mode === 'trajectory' && _traj?.frames?.length)
      ? { frame: _trajIdx + 1, total: _traj.frames.length }
      : null,
    coloringInfo: () => {
      const resp = _mode === 'rmsf' ? _rmsfResp : (_mode === 'deviation' ? _devResp : null)
      if (!resp?.positions?.length) return null
      const rmsf = _mode === 'rmsf'
      const bounds = (rmsf ? _rmsfBounds : _devBounds) || { lo: 0, hi: 1 }
      return {
        attribute: rmsf ? 'rmsf' : 'deviation', title: rmsf ? 'RMSF' : 'Deviation', unit: 'nm',
        colormap: rmsf ? _rmsfCmap : _devCmap, lo: bounds.lo, hi: bounds.hi,
        values: resp.positions.map(p => ({
          helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction,
          copy: p.copy ?? 0, value: rmsf ? p.rmsf : p.deviation,
        })),
      }
    },
  }
}
