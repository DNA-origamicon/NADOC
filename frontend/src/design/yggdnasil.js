/** YggDNAsil v1: connected closed disks about three symmetry centers.
 * Coordinates match backend/core/lattice.py, in units of the 2.25 nm pitch.
 * Counts describe occupancy only, not routed or physically qualified origami.
 */
export const SCAFFOLDS = [7249, 7560, 8064]
export const CENTERS = {
  square: [['Helix', 0, 0], ['Bond', 0.5, 0], ['Cell', 0.5, 0.5]],
  honeycomb: [['Helix', 0, 0], ['Bond', Math.sqrt(3) / 4, 0.25], ['Cell', 0, 1]],
}
const key = (x, y) => `${Math.round(x * 1e6)},${Math.round(y * 1e6)}`
export function position(lattice, row, col) {
  return lattice === 'square' ? [col, row] : [col * Math.sqrt(3) / 2, row * 1.5 + ((row + col) % 2 !== 0 ? 0.5 : 0)]
}
// Proper lattice rotations and translation only; IDs exclude routing/sequence.
export function footprintKey(lattice, points) {
  const rotations = lattice === 'square' ? 4 : 6
  const candidates = []
  for (let i = 0; i < rotations; i++) {
    const a = i * 2 * Math.PI / rotations
    const p = points.map(({ x, y }) => [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)])
    const minX = Math.min(...p.map(v => v[0])), minY = Math.min(...p.map(v => v[1]))
    candidates.push(p.map(([x, y]) => key(x - minX, y - minY)).sort().join(';'))
  }
  return `${lattice}:${candidates.sort()[0]}`
}
function connected(points, lattice) {
  const remaining = new Set(points.map(p => key(p.x, p.y)))
  const queue = [points[0]]
  remaining.delete(key(points[0].x, points[0].y))
  const directions = lattice === 'square' ? [[1, 0], [-1, 0], [0, 1], [0, -1]] :
    [[0, 1], [0, -1], [Math.sqrt(3) / 2, 0.5], [-Math.sqrt(3) / 2, 0.5], [Math.sqrt(3) / 2, -0.5], [-Math.sqrt(3) / 2, -0.5]]
  for (let i = 0; i < queue.length; i++) for (const [dx, dy] of directions) {
    const x = queue[i].x + dx, y = queue[i].y + dy
    if (remaining.delete(key(x, y))) queue.push({ x, y })
  }
  return remaining.size === 0
}
export function enumerateRods({ scaffold = 7249, minLength = 21, reserve = 0 } = {}) {
  if (!SCAFFOLDS.includes(scaffold) || !Number.isInteger(minLength) || minLength < 21 || minLength > scaffold || !Number.isInteger(reserve) || reserve < 0 || reserve >= scaffold) throw new Error('Invalid atlas budget')
  const maxH = Math.floor((scaffold - reserve) / minLength)
  const entries = [], known = new Map()
  for (const lattice of Object.keys(CENTERS)) {
    // A disk containing >maxH sites terminates growth. This generous window
    // encloses such a disk for both lattices, including every boundary shell.
    const radius = Math.ceil(2 * Math.sqrt(maxH) + 4)
    for (const [center, cx, cy] of CENTERS[lattice]) {
      const sites = []
      for (let r = -radius; r <= radius; r++) for (let c = -radius; c <= radius; c++) {
        const [x, y] = position(lattice, r, c)
        const d2 = (x - cx) ** 2 + (y - cy) ** 2
        if (d2 <= radius ** 2 / 4) sites.push({ row: r, col: c, x, y, d2 })
      }
      sites.sort((a, b) => a.d2 - b.d2)
      const points = []
      for (let i = 0; i < sites.length;) {
        const d2 = sites[i].d2
        do { points.push(sites[i++]) } while (i < sites.length && Math.abs(sites[i].d2 - d2) < 1e-7)
        if (points.length > maxH) break
        if (!connected(points, lattice)) continue
        const canonical = footprintKey(lattice, points)
        const source = { center, radiusNm: Math.sqrt(d2) * 2.25 }
        if (known.has(canonical)) { known.get(canonical).sources.push(source); continue }
        const entry = { id: `${lattice}-${entries.filter(e => e.lattice === lattice).length + 1}`, lattice, canonical,
          points: points.map(({ row, col, x, y }) => ({ row, col, x, y })), sources: [source],
          helices: points.length, minLength, maxLength: Math.floor((scaffold - reserve) / points.length) }
        entry.count = entry.maxLength - minLength + 1
        known.set(canonical, entry); entries.push(entry)
      }
    }
  }
  entries.sort((a, b) => a.lattice.localeCompare(b.lattice) || a.helices - b.helices || a.id.localeCompare(b.id))
  return { version: 1, scaffold, minLength, reserve,
    scope: 'Straight connected disk footprints at helix, bond and cell symmetry centers; integer bp lengths; no bends, twists, routings, sequences or arbitrary off-center disks. IDs are local; canonical keys identify footprints.',
    count: entries.reduce((s, e) => s + e.count, 0), entries }
}
