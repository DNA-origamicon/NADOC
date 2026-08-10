// Pure helpers for the scaffold-size chips in the Extrude panel.

export const EXTRUDE_END_MARGIN_BP = 7

/**
 * Per-helix length that makes this extrusion consume the target scaffold size.
 * Existing design content is deliberately irrelevant: the chips size the segment
 * being created, not the eventual combined structure.
 */
export function recommendedExtrudeBp({ targetNt, selectedCount, endMarginBp = EXTRUDE_END_MARGIN_BP }) {
  if (selectedCount <= 0) return 0
  return Math.max(1, Math.floor(targetNt / selectedCount) - 2 * endMarginBp)
}
