/** Automatic callout branches. All geometry here is transient presentation state. */
import { orderStrandNucleotides } from './helix_renderer.js'
import { createTargetEntryMatcher } from './annotation_targets.js'
import { rotatedAnnotationLeader } from './annotation_box_math.js'
import { coverage } from './annotation_occupancy.js'

/** Use the renderer's existing strand ordering on the FULL source before filtering:
 * adjacent selected bases/domains share a branch, omitted bases separate runs.
 * Assembly refs keep instance ownership even when source strand IDs coincide.
 * Positions remain live; no topology or molecular geometry is authored here. */
export function annotationTargetGroups(refs, design, entries, resolve = null) {
  const match = createTargetEntryMatcher(), groups = []
  const resolved = resolve?.(refs)
  // An explicitly selected group/instance is one target, not an implicit request
  // to annotate every strand inside it. Spatial islands still split below.
  if (resolved != null) return refs.map(ref => (resolve([ref]) ?? []).map(e => e.pos)).filter(g => g.length)
  const aggregateKinds = new Set(['cluster', 'part_group'])
  const aggregates = refs.filter(ref => aggregateKinds.has(ref.kind))
  const covered = new Set()
  for (const ref of aggregates) {
    const selected = match([ref], design, entries).filter(e => !covered.has(e))
    for (const e of selected) covered.add(e)
    if (selected.length) groups.push(selected.map(e => e.pos))
  }
  const exact = refs.filter(ref => !aggregateKinds.has(ref.kind))
  const sources = [{ source: entries, selected: new Set(match(exact, design, entries).filter(e => !covered.has(e))) }]
  const seen = new Set()
  for (const { source, selected } of sources) {
    const strands = new Map(), byNuc = new Map()
    for (const e of source) {
      if (!e.nuc || !e.pos) continue
      const key = e.nuc.strand_id ?? ''
      if (!strands.has(key)) strands.set(key, [])
      strands.get(key).push(e.nuc); byNuc.set(e.nuc, e)
    }
    for (const nucs of strands.values()) {
      let run = null
      for (const nuc of orderStrandNucleotides(nucs)) {
        const e = byNuc.get(nuc)
        if (!selected.has(e)) { run = null; continue }
        if (seen.has(e)) continue
        seen.add(e)
        if (!run) { run = []; groups.push(run) }
        run.push(e.pos)
      }
    }
  }
  return groups
}

/** Spatial flood fill with a pixel grid: no branch cap, bounded spatial neighbourhoods.
 * Separate target groups never merge just because the camera overlaps them.
 * Split visible gaps above 48 CSS pixels, scaled above normal bead spacing
 * when zoomed in so an intact domain does not sprout one leader per base. */
export function annotationBranchAnchors(groups, project, gap = 48) {
  const anchors = []
  for (const group of groups) {
    const projected = group.map(project).filter(p => p && Number.isFinite(p.x) && Number.isFinite(p.y))
    const spacing = projected.slice(1).map((p, i) => Math.hypot(p.x - projected[i].x, p.y - projected[i].y)).filter(d => d > 0).sort((a, b) => a - b)
    const threshold = Math.max(gap, spacing.length >= 3 ? 3 * spacing[Math.floor((spacing.length - 1) / 2)] : 0)
    const cellSize = threshold / Math.SQRT2
    const cells = new Map()
    for (const p of projected) {
      const x = Math.floor(p.x / cellSize), y = Math.floor(p.y / cellSize), key = `${x}:${y}`
      if (!cells.has(key)) cells.set(key, { x, y, points: [] })
      cells.get(key).points.push(p)
    }
    // Cell neighbours are only connected if their actual points are within gap.
    for (const seed of cells.values()) {
      if (seed.visited) continue
      seed.visited = true
      const queue = [seed], points = []
      for (let i = 0; i < queue.length; i++) {
        const cell = queue[i]
        for (const p of cell.points) points.push(p)
        for (let y = cell.y - 2; y <= cell.y + 2; y++) for (let x = cell.x - 2; x <= cell.x + 2; x++) {
          const next = cells.get(`${x}:${y}`)
          if (!next || next.visited) continue
          if (!cell.points.some(a => next.points.some(b => Math.hypot(a.x - b.x, a.y - b.y) <= threshold))) continue
          next.visited = true; queue.push(next)
        }
      }
      const centre = points.reduce((a, p) => ({ x: a.x + p.x / points.length, y: a.y + p.y / points.length }), { x: 0, y: 0 })
      anchors.push(points.reduce((best, p) => Math.hypot(p.x - centre.x, p.y - centre.y) < Math.hypot(best.x - centre.x, best.y - centre.y) ? p : best))
    }
  }
  return anchors
}

const cross = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
const crosses = (a, b, c, d) => cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0

/** Deterministic bounded candidate search, not a claim of a global optimum.
 * Penalize model coverage, label collisions and previously routed crossings.
 * Keep endpoints on real selected members and starts on the rotated label edge. */
export function routeAnnotationBranches({ anchors, type, rect, size, angle = 0, occupancy = null, obstacles = [], previousRoutes = [] }) {
  const routes = []
  const radians = angle * Math.PI / 180, c = Math.cos(radians), s = Math.sin(radians)
  const insideLabel = p => {
    const dx = p.x - rect.x - rect.w / 2, dy = p.y - rect.y - rect.h / 2
    return Math.abs(dx * c + dy * s) < size.w / 2 - 1 && Math.abs(-dx * s + dy * c) < size.h / 2 - 1
  }
  const score = points => {
    let cost = 0
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], length = Math.hypot(b.x - a.x, b.y - a.y)
      cost += length
      const steps = Math.max(1, Math.ceil(length / 12))
      for (let j = 1; j < steps; j++) {
        const p = { x: a.x + (b.x - a.x) * j / steps, y: a.y + (b.y - a.y) * j / steps }
        cost += 3 * length / steps * coverage(occupancy, { ...p, w: 1, h: 1 })
        if (insideLabel(p) || obstacles.some(o => p.x > o.x && p.x < o.x + o.w && p.y > o.y && p.y < o.y + o.h)) cost += 1000
      }
      for (const route of [...previousRoutes, ...routes]) for (let k = 1; k < route.length; k++)
        if (crosses(a, b, route[k - 1], route[k])) cost += 300
    }
    return cost
  }
  for (const anchor of [...anchors].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const direct = rotatedAnnotationLeader(type, rect, size, angle, anchor)
    const candidates = [direct]
    // Straight/rounded/shelf styles keep their straight leaders. Elbow routes
    // can use either orthogonal bend or detour around occupied regions.
    if (type === 'elbow') {
      const start = direct[0]
      candidates.push([start, { x: start.x, y: anchor.y }, anchor], [start, { x: anchor.x, y: start.y }, anchor])
      for (const offset of [-48, 48, -96, 96]) {
        const y = Math.max(8, Math.min(occupancy?.height ? occupancy.height - 8 : Infinity, (start.y + anchor.y) / 2 + offset))
        candidates.push([start, { x: start.x, y }, { x: anchor.x, y }, anchor])
      }
    }
    routes.push(candidates.reduce((best, p) => score(p) < score(best) ? p : best))
  }
  return routes
}
