/**
 * oxDNA display controller.
 *
 * Two display modes, both Physical-layer / display-state only (topology is never
 * touched), and mutually exclusive (they share the one bead-position overlay):
 *
 *  - "OxDNA display" (displayJob): deform the NADOC model to a job's last relaxed
 *    configuration via designRenderer.applyFemPositions(...).
 *  - "Flexibility map" (displayRmsf): deform the model to the per-base AVERAGE
 *    position over the production trajectory and recolour each backbone bead by
 *    its RMSF (root-mean-square fluctuation) — rigid = dark, flexible = bright —
 *    via designRenderer.applyScalarColors(...).
 *
 * Toggling either off restores the model via applyFemPositions(null) +
 * clearScalarColors().
 *
 * Factory: initOxdnaDisplay({ designRenderer, api }) → controller.
 */

/**
 * Pure mapping: a /oxdna/jobs/{id}/display response → applyFemPositions updates.
 * Returns [] for a not-ready / empty response.  Kept pure for unit testing.
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
    nx: p.nx, ny: p.ny, nz: p.nz,
  }))
}

// Viridis colormap anchors (perceptually uniform). t in [0,1] → [r,g,b] 0-255.
const _VIRIDIS = [
  [68, 1, 84], [59, 82, 139], [33, 144, 140], [93, 201, 99], [253, 231, 37],
]

/** Pure: viridis colour for t∈[0,1] as a 0xRRGGBB int (rigid→flexible ramp). */
export function viridisHex(t) {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0))
  const seg = x * (_VIRIDIS.length - 1)
  const i = Math.min(_VIRIDIS.length - 2, Math.floor(seg))
  const f = seg - i
  const a = _VIRIDIS[i], b = _VIRIDIS[i + 1]
  const r = Math.round(a[0] + (b[0] - a[0]) * f)
  const g = Math.round(a[1] + (b[1] - a[1]) * f)
  const bl = Math.round(a[2] + (b[2] - a[2]) * f)
  return (r << 16) | (g << 8) | bl
}

/**
 * Pure: a /oxdna/jobs/{id}/rmsf response → { updates, colorByKey, min, max }.
 * RMSF is scaled to [loBound, hiBound] (values outside clamp to the endpoints);
 * when bounds are omitted it defaults to the design's own min→max RMSF so
 * rigid-vs-flexible contrast is maximised.  colorByKey maps "helix:bp:dir" →
 * viridis hex.  Returns null for a not-ready / empty response.
 */
export function rmsfColorMap(resp, loBound, hiBound) {
  if (!resp || !resp.ready || !Array.isArray(resp.positions) || !resp.positions.length) {
    return null
  }
  const dataLo = Number.isFinite(resp.min_rmsf) ? resp.min_rmsf : 0
  const dataHi = Number.isFinite(resp.max_rmsf) ? resp.max_rmsf : 0
  const lo = Number.isFinite(loBound) ? loBound : dataLo
  const hi = Number.isFinite(hiBound) ? hiBound : dataHi
  const span = hi - lo
  const updates = []
  const colorByKey = {}
  for (const p of resp.positions) {
    updates.push({
      helix_id: p.helix_id, bp_index: p.bp_index, direction: p.direction,
      backbone_position: p.backbone_position, nx: p.nx, ny: p.ny, nz: p.nz,
    })
    const t = span > 1e-9 ? (p.rmsf - lo) / span : 0.0   // viridisHex clamps to [0,1]
    colorByKey[`${p.helix_id}:${p.bp_index}:${p.direction}`] = viridisHex(t)
  }
  return { updates, colorByKey, min: dataLo, max: dataHi }
}

/**
 * Pure: turn one composite-trajectory frame (flat float list) + the shared key
 * list into applyFemPositions updates.  keys = [[helix,bp,dir], …]; frame holds
 * 6 floats per key (backbone x,y,z then a1 nx,ny,nz).  Kept pure for testing.
 */
export function framesToUpdates(keys, frame) {
  if (!Array.isArray(keys) || !Array.isArray(frame)) return []
  const updates = []
  for (let j = 0; j < keys.length; j++) {
    const o = j * 6
    updates.push({
      helix_id: keys[j][0], bp_index: keys[j][1], direction: keys[j][2],
      backbone_position: [frame[o], frame[o + 1], frame[o + 2]],
      nx: frame[o + 3], ny: frame[o + 4], nz: frame[o + 5],
    })
  }
  return updates
}

export function initOxdnaDisplay({ designRenderer, api }) {
  let _active = false
  let _jobId = null
  let _mode = null     // 'relaxed' | 'rmsf' | 'trajectory'
  let _rmsfResp = null // cached /rmsf payload so the scale can recolour without re-fetching
  let _traj = null     // cached /trajectory payload {keys, frames, markers, n_frames, stages}

  /** Fetch the latest relaxed frame for jobId and deform the model to it. */
  async function displayJob(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getOxdnaDisplay(jobId)
    const updates = toFemUpdates(resp)
    if (!updates.length) {
      return { ok: false, reason: resp?.ready === false ? 'no relaxed frame yet' : 'empty' }
    }
    designRenderer.clearScalarColors?.()   // leaving a flexibility map → restore bead colours
    designRenderer.applyFemPositions(updates)
    _active = true
    _mode = 'relaxed'
    _jobId = jobId
    return { ok: true, n: updates.length, stage: resp.stage_name }
  }

  /**
   * Fetch the production flexibility map for jobId, deform the model to the
   * average structure, and recolour beads by RMSF (rigid→flexible).
   */
  async function displayRmsf(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getOxdnaRmsf(jobId)
    const map = rmsfColorMap(resp)
    if (!map) {
      return { ok: false, reason: resp?.reason || 'not ready' }
    }
    _rmsfResp = resp
    designRenderer.applyFemPositions(map.updates)
    designRenderer.applyScalarColors(map.colorByKey)
    _active = true
    _mode = 'rmsf'
    _jobId = jobId
    return { ok: true, n: map.updates.length, min: map.min, max: map.max, mean: resp.mean_rmsf }
  }

  /**
   * Recolour the active flexibility map to a custom RMSF range [lo, hi] (values
   * outside clamp to the endpoints) — driven by the workspace scale widget.
   * Positions are untouched (only colours change).  No-op unless the RMSF map is
   * the active overlay and its data is cached.
   */
  function recolorRmsf(lo, hi) {
    if (_mode !== 'rmsf' || !_rmsfResp || !designRenderer) return false
    const map = rmsfColorMap(_rmsfResp, lo, hi)
    if (!map) return false
    designRenderer.applyScalarColors(map.colorByKey)
    return true
  }

  /**
   * Fetch the composite trajectory (relaxation + all production runs) for jobId,
   * cache it, and show the first frame.  Returns metadata for the player
   * (n_frames + stage markers).  The actual scrubbing is driven by showFrame().
   */
  async function loadTrajectory(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getOxdnaTrajectory(jobId)
    if (!resp?.ready || !Array.isArray(resp.frames) || !resp.frames.length) {
      return { ok: false, reason: resp?.reason || 'no trajectory yet' }
    }
    _traj = resp
    designRenderer.clearScalarColors?.()
    _active = true
    _mode = 'trajectory'
    _jobId = jobId
    showFrame(0)
    return { ok: true, n_frames: resp.n_frames, markers: resp.markers || [], stages: resp.stages || [] }
  }

  /** Deform the model to composite-trajectory frame i (clamped). No-op off mode. */
  function showFrame(i) {
    if (_mode !== 'trajectory' || !_traj || !designRenderer) return
    const n = _traj.frames.length
    const idx = Math.max(0, Math.min(n - 1, i | 0))
    designRenderer.applyFemPositions(framesToUpdates(_traj.keys, _traj.frames[idx]))
  }

  /** Re-fetch the current job's frame (e.g. after a stage completes). */
  async function refresh() {
    if (!_active || !_jobId) return { ok: false, reason: 'not active' }
    if (_mode === 'trajectory') return loadTrajectory(_jobId)
    return _mode === 'rmsf' ? displayRmsf(_jobId) : displayJob(_jobId)
  }

  /** Clear the overlay (positions + colours) and restore the design. */
  function stopAndRestore() {
    if (!_active) return
    designRenderer?.clearScalarColors?.()
    designRenderer?.applyFemPositions(null)
    _active = false
    _mode = null
    _jobId = null
    _rmsfResp = null
    _traj = null
  }

  return {
    displayJob,
    displayRmsf,
    recolorRmsf,
    loadTrajectory,
    showFrame,
    refresh,
    stopAndRestore,
    isActive: () => _active,
    mode: () => _mode,
    activeJobId: () => _jobId,
  }
}
