/**
 * oxDNA display controller.
 *
 * The analogue of the MD display's "nadoc" representation, but for an oxDNA
 * relaxation job: it fetches a job's last relaxed configuration and deforms the
 * NADOC model to it via designRenderer.applyFemPositions(...).  An oxDNA run
 * yields a single relaxed frame (not a trajectory), so this is a one-shot fetch
 * + apply with an explicit refresh — no scrubber/playback.
 *
 * oxDNA positions are Physical-layer / display state only; toggling display off
 * restores the model via applyFemPositions(null).  Topology is never touched.
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

export function initOxdnaDisplay({ designRenderer, api }) {
  let _active = false
  let _jobId = null

  /** Fetch the latest relaxed frame for jobId and deform the model to it. */
  async function displayJob(jobId) {
    if (!jobId || !designRenderer) return { ok: false, reason: 'no job' }
    const resp = await api.getOxdnaDisplay(jobId)
    const updates = toFemUpdates(resp)
    if (!updates.length) {
      return { ok: false, reason: resp?.ready === false ? 'no relaxed frame yet' : 'empty' }
    }
    designRenderer.applyFemPositions(updates)
    _active = true
    _jobId = jobId
    return { ok: true, n: updates.length, stage: resp.stage_name }
  }

  /** Re-fetch the current job's frame (e.g. after a stage completes). */
  async function refresh() {
    if (_active && _jobId) return displayJob(_jobId)
    return { ok: false, reason: 'not active' }
  }

  /** Clear the overlay and restore the design's own geometry. */
  function stopAndRestore() {
    if (!_active) return
    designRenderer?.applyFemPositions(null)
    _active = false
    _jobId = null
  }

  return {
    displayJob,
    refresh,
    stopAndRestore,
    isActive: () => _active,
    activeJobId: () => _jobId,
  }
}
