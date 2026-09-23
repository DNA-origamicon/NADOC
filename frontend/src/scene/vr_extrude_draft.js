/** Transport validation, independent of topology/placement/commit readiness. */
export function normalizePaintedFootprint(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'cells,lattice_type' ||
      !['HONEYCOMB', 'SQUARE'].includes(value.lattice_type) ||
      !Array.isArray(value.cells) || value.cells.length > 16641) return null
  const seen = new Set()
  const cells = []
  for (const cell of value.cells) {
    if (!Array.isArray(cell) || cell.length !== 2 ||
        !cell.every(v => Number.isSafeInteger(v) && Math.abs(v) <= 100000)) return null
    const key = cell.join(':')
    if (seen.has(key)) return null
    seen.add(key)
    cells.push([...cell])
  }
  return { lattice_type: value.lattice_type, cells }
}
