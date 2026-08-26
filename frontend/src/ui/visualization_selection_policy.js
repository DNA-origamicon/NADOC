/**
 * Selection policy for simulation visualization ownership.
 *
 * Selection owns every job-scoped card, including visualization. A completed parent is
 * often the only locally available trajectory while its child runs remotely; treating
 * historical selection as "detail only" leaves the display stuck on that remote child.
 * Deselection remains non-destructive, but every real selection retargets the cards.
 */
export function selectionUpdatesVisualization(job) {
  return !!job
}

/** Snapshot the active MD view before a job switch changes radio availability. */
export function mdVisualizationJobSwitchAction({
  display, flex, photoproduct, occupancy, trajectory,
} = {}) {
  if (trajectory) return 'trajectory'
  if (display) return 'display'
  if (flex) return 'flex'
  if (photoproduct) return 'photoproduct'
  if (occupancy) return 'occupancy'
  return 'none'
}

/** Execute a previously-snapshotted MD job-switch action. */
export async function applyMdVisualizationJobSwitch(action, handlers = {}) {
  if (action === 'off') return handlers.off?.()
  if (action === 'trajectory') return handlers.trajectory?.()
  if (action === 'display') return handlers.display?.()
  if (action === 'flex') return handlers.flex?.()
  if (action === 'photoproduct') return handlers.photoproduct?.()
  if (action === 'occupancy') return handlers.occupancy?.()
  return handlers.none?.()
}
