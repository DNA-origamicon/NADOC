/** Short-lived serial -> atom row lookup for renderer construction.
 * Numeric, reasonably dense IDs use a bounded array; arbitrary Map keys retain
 * their exact identity and last-row-wins semantics through the fallback.
 */
export function buildAtomSerialIndex(table) {
  let lo = Infinity, hi = -Infinity
  const limit = Math.min(table.count * 16, 4 * 1024 * 1024)
  let dense = table.count > 0 && table.count <= 0x7fffffff
  for (let row = 0; row < table.count && dense; row++) {
    const serial = table.serial(row)
    if (!Number.isSafeInteger(serial)) { dense = false; break }
    lo = Math.min(lo, serial); hi = Math.max(hi, serial)
    if (hi - lo + 1 > limit) dense = false
  }
  if (!dense) {
    const index = new Map()
    for (let row = 0; row < table.count; row++) index.set(table.serial(row), row)
    return index
  }
  // At most 16 MiB, independent of the absolute serial offset. Missing IDs
  // stay -1; row zero and duplicate IDs must behave exactly like Map.get().
  const rows = new Int32Array(hi - lo + 1).fill(-1)
  for (let row = 0; row < table.count; row++) rows[table.serial(row) - lo] = row
  return {
    get(serial) {
      if (!Number.isSafeInteger(serial) || serial < lo || serial > hi) return undefined
      const row = rows[serial - lo]
      return row < 0 ? undefined : row
    },
  }
}
