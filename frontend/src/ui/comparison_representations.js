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
