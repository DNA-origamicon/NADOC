/**
 * Screen-space occupancy of the visible design, for callout placement.
 * Pure: pixel points/discs in, grid queries out.
 *
 *   coverage(occ, rect)   fraction of the rect's cells that overlap design
 *   clearanceAt(occ, x,y) px from (x,y) to the nearest design cell
 *   emptyCentres(occ, n)  centres of the roomiest empty pockets, best first
 */

const CELL = 12

export function buildOccupancy(points, discs, viewport, cell = CELL) {
  const cols = Math.max(1, Math.ceil(viewport.width / cell))
  const rows = Math.max(1, Math.ceil(viewport.height / cell))
  const grid = new Uint8Array(cols * rows)
  const mark = (cx, cy) => { if (cx >= 0 && cy >= 0 && cx < cols && cy < rows) grid[cy * cols + cx] = 1 }
  for (const p of points) {
    const cx = Math.floor(p.x / cell), cy = Math.floor(p.y / cell)
    // 3×3 dilation: neighbouring beads are joined into the strand they draw.
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) mark(cx + dx, cy + dy)
  }
  for (const d of discs ?? []) {
    const r = Math.ceil(d.r / cell)
    const cx = Math.floor(d.x / cell), cy = Math.floor(d.y / cell)
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r) mark(cx + dx, cy + dy)
  }

  // Summed-area table (one extra row/column of zeros).
  const w1 = cols + 1
  const sat = new Int32Array(w1 * (rows + 1))
  for (let y = 0; y < rows; y++) {
    let run = 0
    for (let x = 0; x < cols; x++) {
      run += grid[y * cols + x]
      sat[(y + 1) * w1 + x + 1] = sat[y * w1 + x + 1] + run
    }
  }

  // Two-pass chamfer distance (in cells) to the nearest occupied cell.
  const INF = 1e6
  const dist = new Float32Array(cols * rows)
  for (let i = 0; i < dist.length; i++) dist[i] = grid[i] ? 0 : INF
  const D = 1, DD = 1.4142
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    const i = y * cols + x
    let v = dist[i]
    if (x > 0) v = Math.min(v, dist[i - 1] + D)
    if (y > 0) {
      v = Math.min(v, dist[i - cols] + D)
      if (x > 0) v = Math.min(v, dist[i - cols - 1] + DD)
      if (x < cols - 1) v = Math.min(v, dist[i - cols + 1] + DD)
    }
    dist[i] = v
  }
  for (let y = rows - 1; y >= 0; y--) for (let x = cols - 1; x >= 0; x--) {
    const i = y * cols + x
    let v = dist[i]
    if (x < cols - 1) v = Math.min(v, dist[i + 1] + D)
    if (y < rows - 1) {
      v = Math.min(v, dist[i + cols] + D)
      if (x < cols - 1) v = Math.min(v, dist[i + cols + 1] + DD)
      if (x > 0) v = Math.min(v, dist[i + cols - 1] + DD)
    }
    dist[i] = v
  }
  const empty = !grid.some(Boolean)
  return { cell, cols, rows, grid, sat, dist, empty, width: viewport.width, height: viewport.height }
}

const clampInt = (v, lo, hi) => Math.min(Math.max(v, lo), hi)

/** Occupied fraction (0–1) of the cells a rect touches. */
export function coverage(occ, rect) {
  if (!occ || occ.empty) return 0
  const x0 = clampInt(Math.floor(rect.x / occ.cell), 0, occ.cols)
  const y0 = clampInt(Math.floor(rect.y / occ.cell), 0, occ.rows)
  const x1 = clampInt(Math.ceil((rect.x + rect.w) / occ.cell), 0, occ.cols)
  const y1 = clampInt(Math.ceil((rect.y + rect.h) / occ.cell), 0, occ.rows)
  const area = (x1 - x0) * (y1 - y0)
  if (area <= 0) return 0
  const w1 = occ.cols + 1
  const hit = occ.sat[y1 * w1 + x1] - occ.sat[y0 * w1 + x1] - occ.sat[y1 * w1 + x0] + occ.sat[y0 * w1 + x0]
  return hit / area
}

/** Pixels from a point to the nearest design cell (large when the view is empty). */
export function clearanceAt(occ, x, y) {
  if (!occ || occ.empty) return Math.max(occ?.width ?? 0, occ?.height ?? 0)
  const cx = clampInt(Math.floor(x / occ.cell), 0, occ.cols - 1)
  const cy = clampInt(Math.floor(y / occ.cell), 0, occ.rows - 1)
  return occ.dist[cy * occ.cols + cx] * occ.cell
}

/**
 * Centres of the roomiest empty pockets: greedy pick of the maximum-clearance
 * cell, then suppress its neighbourhood so the next pick is a different pocket.
 * An entirely empty view yields the viewport centre.
 */
export function emptyCentres(occ, count = 4) {
  if (!occ) return []
  if (occ.empty) return [{ x: occ.width / 2, y: occ.height / 2, clearance: Math.max(occ.width, occ.height) }]
  const dist = Float32Array.from(occ.dist)
  const out = []
  for (let n = 0; n < count; n++) {
    let best = -1, bi = -1
    for (let i = 0; i < dist.length; i++) if (dist[i] > best) { best = dist[i]; bi = i }
    if (best <= 1) break
    const cx = bi % occ.cols, cy = Math.floor(bi / occ.cols)
    out.push({ x: (cx + 0.5) * occ.cell, y: (cy + 0.5) * occ.cell, clearance: best * occ.cell })
    const r = Math.ceil(best)
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
      const x = cx + dx, y = cy + dy
      if (x >= 0 && y >= 0 && x < occ.cols && y < occ.rows) dist[y * occ.cols + x] = 0
    }
  }
  return out
}
