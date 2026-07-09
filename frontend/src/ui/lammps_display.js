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
  let _jobId = null

  function _restore() {
    designRenderer?.applyFemPositions(null)
    designRenderer?.clearScalarColors?.()
  }

  async function displayJob(jobId, align = true) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getLammpsDisplay(jobId, align)
    const updates = toFemUpdates(resp)
    if (!updates.length) return { ok: false, reason: resp?.reason || 'not ready' }
    designRenderer.clearScalarColors?.()          // plain positions, no per-base colour
    designRenderer.applyFemPositions(updates)
    _mode = 'display'; _traj = null; _jobId = jobId
    return { ok: true, n: updates.length }
  }

  async function displayRmsf(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getLammpsRmsf(jobId)
    const map = rmsfColorMap(resp)
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _mode = 'rmsf'; _traj = null; _jobId = jobId
    return { ok: true, min: map.min, max: map.max, mean: resp.mean_rmsf,
             nFrames: resp.n_frames, confidence: resp.confidence }
  }

  async function displayDeviation(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getLammpsDeviation(jobId)
    const map = deviationColorMap(resp)
    if (!map) return { ok: false, reason: resp?.reason || 'not ready' }
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _mode = 'deviation'; _traj = null; _jobId = jobId
    return { ok: true, min: map.min, max: map.max, mean: resp.mean_deviation, nFrames: resp.n_frames }
  }

  async function loadTrajectory(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const t = await api.getLammpsTrajectory(jobId)
    if (!t || !t.ready) { _traj = null; return { ok: false, reason: t?.reason || 'not ready' } }
    _traj = { keys: t.keys, frames: t.frames }
    _mode = 'trajectory'; _jobId = jobId
    designRenderer.clearScalarColors?.()
    showFrame(0)
    return { ok: true, n_frames: t.n_frames, markers: t.markers || [] }
  }

  function showFrame(i) {
    if (_mode !== 'trajectory' || !_traj) return
    const f = _traj.frames[i]
    if (f) designRenderer.applyFemPositions(framesToUpdates(_traj.keys, f))
  }

  function stopAndRestore() {
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
    displayJob, displayRmsf, displayDeviation, loadTrajectory, showFrame, stopAndRestore,
    mode: () => _mode, activeJobId: () => _jobId, isActive: () => _mode !== null,
  }
}
