/** Only display settings and bounded legend values cross the presentation boundary. */
export const VIEW_TOOLS = {
  lengthHeatmap: 'Strand length', sequences: 'Sequences', undefinedBases: 'Undefined bases',
  loopSkips: 'Loops / skips', overhangNames: 'Overhang names', grid: 'Grid', clashes: 'Clashes / piercings',
}
export function captureViewTools(doc) {
  const value = Object.fromEntries(Object.keys(VIEW_TOOLS).map(key => [key, !!doc.querySelector?.(`.vt-btn[data-vt="${key}"]`)?.classList.contains('active')]))
  const legend = doc.getElementById('clash-legend')
  const count = /^([0-9]+) clashes?$/.exec(doc.getElementById('clash-legend-text')?.textContent?.trim() ?? '')
  value.clashCount = value.clashes && legend?.classList.contains('visible') && count && Number.isSafeInteger(Number(count[1])) ? Number(count[1]) : null
  const piercing = /^([0-9]+)(\+)? piercings?$/.exec(doc.getElementById('piercing-legend-text')?.textContent?.trim() ?? '')
  value.piercingCount = value.clashes && legend?.classList.contains('visible') && piercing && Number.isSafeInteger(Number(piercing[1])) ? Number(piercing[1]) : null
  value.piercingTruncated = value.piercingCount !== null && !!piercing?.[2]
  return value
}
export function validateViewTools(value) {
  if (value == null) return
  if (typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !['clashCount', 'piercingCount', 'piercingTruncated'].includes(k) && !Object.hasOwn(VIEW_TOOLS, k)) ||
      Object.keys(VIEW_TOOLS).some(k => typeof value[k] !== 'boolean') ||
      (value.clashCount !== null && (!Number.isSafeInteger(value.clashCount) || value.clashCount < 0))) throw new Error('Invalid shared view tools')
  // Optional for older saved presentations, which contain only a clash count.
  if ((value.piercingCount != null && (!Number.isSafeInteger(value.piercingCount) || value.piercingCount < 0)) ||
      (value.piercingTruncated !== undefined && typeof value.piercingTruncated !== 'boolean')) throw new Error('Invalid shared piercing report')
}
