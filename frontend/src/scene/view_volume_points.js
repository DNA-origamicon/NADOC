/** Supply display-only sample points for deleted columns spanned by cylinders.
 * Skips have no nucleotide to test against a volume. Interpolate their column
 * centers from the surrounding live geometry, including consecutive skips.
 */
export function withSkippedColumnPoints(points, helices = []) {
  const byHelix = new Map()
  for (const point of points) {
    const split = point.key.lastIndexOf(':'), id = point.key.slice(0, split), bp = Number(point.key.slice(split + 1))
    if (!byHelix.has(id)) byHelix.set(id, new Map())
    const columns = byHelix.get(id), column = columns.get(bp) ?? { bp, sum: [0, 0, 0], count: 0 }
    point.position.forEach((x, i) => { column.sum[i] += x })
    column.count++; columns.set(bp, column)
  }
  const result = [...points]
  for (const helix of helices) {
    const columns = byHelix.get(helix.id)
    if (!columns) continue
    const sorted = [...columns.values()].sort((a, b) => a.bp - b.bp)
    for (const skip of helix.loop_skips ?? []) {
      if (skip.delta >= 0 || columns.has(skip.bp_index)) continue
      const upper = sorted.findIndex(column => column.bp > skip.bp_index)
      if (upper <= 0) continue
      const a = sorted[upper - 1], b = sorted[upper], t = (skip.bp_index - a.bp) / (b.bp - a.bp)
      result.push({ key: `${helix.id}:${skip.bp_index}`,
        position: a.sum.map((x, i) => x / a.count * (1 - t) + b.sum[i] / b.count * t) })
    }
  }
  return result
}
