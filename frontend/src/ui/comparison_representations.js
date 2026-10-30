export const MRDNA_COARSE_REPRESENTATION = 'mrdna-coarse'
export const MRDNA_FINE_REPRESENTATION = 'mrdna-fine'
export const OXDNA_REPRESENTATION = 'oxdna'

export function isMrdnaRepresentation(representation) {
  return representation === MRDNA_COARSE_REPRESENTATION || representation === MRDNA_FINE_REPRESENTATION
}

export function isComparisonRepresentation(representation) {
  return isMrdnaRepresentation(representation) || representation === OXDNA_REPRESENTATION
}

/** Apply a representation, including the current design's pre-run mrDNA abstractions. */
export async function applyComparisonRepresentation(representation, {
  setRepresentation, mrdnaDisplay, getCurrentGeometry, getCurrentDesign, getColoringMode,
  getHideReferenceGeometry, getColorState, onUnavailable,
}) {
  if (!isComparisonRepresentation(representation)) {
    mrdnaDisplay?.stopAndRestore?.()
    await setRepresentation(representation)
    return true
  }

  mrdnaDisplay?.stopAndRestore?.()
  if (representation === OXDNA_REPRESENTATION) {
    const result = await mrdnaDisplay?.showOxdnaInputPreview?.(
      getCurrentGeometry?.(), getCurrentDesign?.(), getColoringMode?.(), getHideReferenceGeometry?.(), getColorState?.())
    if (!result?.ok) onUnavailable?.('The current design has no geometry available for the oxDNA preview')
    return !!result?.ok
  }
  const resolution = representation === MRDNA_COARSE_REPRESENTATION ? 'coarse' : 'fine'
  const result = await mrdnaDisplay?.showInputPreview?.(getCurrentGeometry?.(), resolution)
  if (!result?.ok) {
    onUnavailable?.(`The current design has no geometry available for the mrDNA ${resolution} preview`)
    return false
  }
  return true
}

/** Only inputs consumed by the oxDNA frame builder, reference filter and palette.
 * Autosave acknowledgements can replace the entire Design with equal geometry
 * plus new loadout/history metadata; those must not restart a paused display.
 */
export function oxdnaPreviewInputsChanged(next, previous) {
  const changed = (a, b) => a !== b && JSON.stringify(a) !== JSON.stringify(b)
  if (next.currentGeometry !== previous.currentGeometry) return true
  for (const key of ['simulationTabActive', 'showReferenceGeometry', 'strandColors', 'strandGroups', 'loopStrandIds']) {
    if (changed(next[key], previous[key])) return true
  }
  for (const key of ['id', 'strands', 'crossovers', 'overhangs', 'extensions', 'cluster_transforms']) {
    if (changed(next.currentDesign?.[key], previous.currentDesign?.[key])) return true
  }
  return false
}
