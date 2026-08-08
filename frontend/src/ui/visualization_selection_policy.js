/**
 * Selection policy for simulation visualization ownership.
 *
 * A visualization is live state, not job-detail state.  Selecting the job that is
 * currently producing frames may retarget/replace that state; deselection and selections
 * of queued, completed, failed, or cancelled jobs are observational and must leave it
 * untouched. Capability/readout refresh is separate, so historical results remain
 * manually viewable. Keeping this rule here prevents the engine panels from each
 * inventing subtly different selection semantics.
 */
export function selectionUpdatesVisualization(job) {
  return job?.status === 'running'
}

/** Snapshot the active MD view before a job switch changes radio availability. */
export function mdVisualizationJobSwitchAction({ display, flex, occupancy, trajectory } = {}) {
  if (trajectory) return 'off'
  if (display) return 'display'
  if (flex) return 'flex'
  if (occupancy) return 'occupancy'
  return 'none'
}

/** Execute a previously-snapshotted MD job-switch action. */
export async function applyMdVisualizationJobSwitch(action, handlers = {}) {
  if (action === 'off') return handlers.off?.()
  if (action === 'display') return handlers.display?.()
  if (action === 'flex') return handlers.flex?.()
  if (action === 'occupancy') return handlers.occupancy?.()
  return handlers.none?.()
}
