/** Merge pending writes: several edits can happen before the next GPU upload. */
export function markAttributeRange(attribute, start, count) {
  if (count <= 0) return
  let end = start + count
  for (const range of attribute.updateRanges) {
    start = Math.min(start, range.start)
    end = Math.max(end, range.start + range.count)
  }
  attribute.clearUpdateRanges()
  attribute.addUpdateRange(start, end - start)
  attribute.needsUpdate = true
}
