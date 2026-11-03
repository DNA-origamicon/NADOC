import { CENTERS, footprintKey, position } from './yggdnasil.js'
const siteKey = p => `${p.row},${p.col}`
function neighbors(lattice, p) {
  const out = []
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    const row = p.row + dr, col = p.col + dc, [x, y] = position(lattice, row, col)
    if (Math.abs((x - p.x) ** 2 + (y - p.y) ** 2 - 1) < 1e-7) out.push({ row, col, x, y })
  }
  return out
}
/** Connected lattice wall enclosing the removed sites (no open slits). */
export function closedCylinderWall(lattice, wall, removed) {
  if (!wall.length || !removed.length) return false
  const all = new Set([...wall, ...removed].map(siteKey))
  if (removed.some(p => neighbors(lattice, p).some(n => !all.has(siteKey(n))))) return false
  const remaining = new Set(wall.map(siteKey)), queue = [wall[0]]
  remaining.delete(siteKey(wall[0]))
  for (let i = 0; i < queue.length; i++) for (const n of neighbors(lattice, queue[i])) {
    if (remaining.delete(siteKey(n))) queue.push(n)
  }
  return remaining.size === 0
}

/** All concentric lattice annuli within a helix budget at a fixed axial length.
 * A connected H-site wall has diameter <= H-1 pitches. Each complete outer
 * shell contains an opposite pair (or a 120-degree pair at an HC helix center),
 * bounding its radius by (H-1)/2 (or (H-1)/sqrt(3)). No solid parent is needed.
 */
export function enumerateCylinders({ scaffold = 7249, length = 100, reserve = 0 } = {}) {
  if (!Number.isInteger(length) || length < 21 || length > scaffold || !Number.isInteger(reserve) || reserve < 0 || reserve >= scaffold || scaffold !== 7249) throw new Error('Invalid cylinder budget')
  const maxH = Math.floor((scaffold - reserve) / length), entries = [], known = new Map()
  for (const lattice of Object.keys(CENTERS)) for (const [center, cx, cy] of CENTERS[lattice]) {
    const radius = Math.max(0, (maxH - 1) / (lattice === 'honeycomb' && center === 'Helix' ? Math.sqrt(3) : 2))
    const rows = Math.ceil(radius / (lattice === 'square' ? 1 : 1.5) + 2)
    const cols = Math.ceil(radius / (lattice === 'square' ? 1 : Math.sqrt(3) / 2) + 2)
    const radialKey = p => Math.round(4 * ((p.x - cx) ** 2 + (p.y - cy) ** 2))
    const shells = new Map()
    for (let row = -rows; row <= rows; row++) for (let col = -cols; col <= cols; col++) {
      const [x, y] = position(lattice, row, col), p = { row, col, x, y }, d2 = radialKey(p)
      if (d2 / 4 > radius * radius + 1e-7) continue
      if (!shells.has(d2)) shells.set(d2, [])
      shells.get(d2).push(p)
    }
    const ordered = [...shells.keys()].sort((a, b) => a - b), counts = [], closure = []
    let count = 0, required = 0
    for (const shell of ordered) {
      const points = shells.get(shell); count += points.length
      for (const p of points) for (const n of neighbors(lattice, p)) required = Math.max(required, radialKey(n))
      counts.push(count); closure.push(required)
    }
    for (let outer = 1; outer < ordered.length; outer++) {
      const wall = []
      for (let inner = outer - 1; inner >= 0; inner--) {
        wall.push(...shells.get(ordered[inner + 1]))
        if (wall.length > maxH) break
        // Every removed site's neighbors must still lie inside the outer disk.
        if (closure[inner] > ordered[outer]) continue
        const remaining = new Set(wall.map(siteKey)), queue = [wall[0]]
        remaining.delete(siteKey(wall[0]))
        for (let i = 0; i < queue.length; i++) for (const n of neighbors(lattice, queue[i])) {
          if (remaining.delete(siteKey(n))) queue.push(n)
        }
        if (remaining.size) continue
        const outerShell = ordered[outer], innerShell = ordered[inner]
        const source = { center, radiusNm: Math.sqrt(outerShell / 4) * 2.25,
          outerRadiusNm: Math.sqrt(outerShell / 4) * 2.25, innerRadiusNm: Math.sqrt(innerShell / 4) * 2.25,
          innerShell, outerShell, shellIndex: inner, removedHelices: counts[inner],
          key: `${lattice}:${center}:${outerShell}:${innerShell}` }
        const canonical = footprintKey(lattice, wall)
        if (known.has(canonical)) { known.get(canonical).sources.push(source); continue }
        const entry = { id: `${lattice}-hollow-${entries.length + 1}`, shape: 'hollow', lattice,
          canonical, points: [...wall], sources: [source], helices: wall.length, minLength: length,
          maxLength: Math.floor((scaffold - reserve) / wall.length), count: 1 }
        known.set(canonical, entry); entries.push(entry)
      }
    }
  }
  return { version: 2, scaffold, length, minLength: length, reserve, entries, count: entries.length,
    scope: 'Straight connected closed annular lattice walls at helix, bond and cell centers; complete shells with Ri < r <= Ro. Includes outer disks exceeding the solid-rod budget. Exhaustive within this grammar at the selected length, using the connected-graph diameter bound. No curved cylinders. H × L + reserve <= 7249 is a preliminary paired-base budget; routing overhead and indels are unallocated.' }
}
