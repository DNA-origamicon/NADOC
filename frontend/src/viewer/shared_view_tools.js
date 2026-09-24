/** Only display settings and bounded legend values cross the presentation boundary. */
export const VIEW_TOOLS = {
  lengthHeatmap: 'Strand length', sequences: 'Sequences', undefinedBases: 'Undefined bases',
  loopSkips: 'Loops / skips', overhangNames: 'Overhang names', grid: 'Grid', clashes: 'Clashes',
}
export function captureViewTools(doc) {
  const value = Object.fromEntries(Object.keys(VIEW_TOOLS).map(key => [key, !!doc.querySelector?.(`.vt-btn[data-vt="${key}"]`)?.classList.contains('active')]))
  const legend = doc.getElementById('clash-legend')
  const count = /^([0-9]+) clashes?$/.exec(doc.getElementById('clash-legend-text')?.textContent?.trim() ?? '')
  value.clashCount = value.clashes && legend?.classList.contains('visible') && count && Number.isSafeInteger(Number(count[1])) ? Number(count[1]) : null
  return value
}
export function validateViewTools(value) {
  if (value == null) return
  if (typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => k !== 'clashCount' && !Object.hasOwn(VIEW_TOOLS, k)) ||
      Object.keys(VIEW_TOOLS).some(k => typeof value[k] !== 'boolean') ||
      (value.clashCount !== null && (!Number.isSafeInteger(value.clashCount) || value.clashCount < 0))) throw new Error('Invalid shared view tools')
}
