/** Uniform +X planar arcs. Count classes, not sequence/placement variants.
 * For an arc, Sweep's integrated strain reduces to delta_i = -r_i * theta / rise.
 * Its local warning bound is 7 * |r_i| * theta / arcLength <= 3.
 * Integer allocations also respect the native per-cell cap, including baseline
 * square-lattice compensation. Routing margins and scaffold completion are not certified.
 */
import limits from './yggdnasil_limits.json'
import { routingScreen } from './yggdnasil_routing.js'
export { limits as CURVATURE_LIMITS }
const EPS = 1e-9

export function curvatureFrame(entry, length) {
  const { rise_nm: rise, helix_pitch_nm: pitch, cell_bp: cell, max_delta_per_cell: cap, square_skip_period: period } = limits
  const centroid = entry.points.reduce((s, p) => s + p.x, 0) / entry.points.length
  const offsets = entry.points.map(p => (p.x - centroid) * pitch)
  const extent = Math.max(...offsets.map(Math.abs))
  const ordered = entry.points.map((p, i) => ({ id: `h_XY_${p.row}_${p.col}`, i })).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  const baseline = entry.points.map(() => Array(Math.ceil(length / cell)).fill(0))
  if (entry.lattice === 'square') for (const [rank, { i }] of ordered.entries()) {
    for (let bp = Math.floor(rank * period / entry.helices); bp < length; bp += period) baseline[i][Math.floor(bp / cell)]++
  }
  const capacities = baseline.map(cells => cells.map((count, j) => Math.max(0, Math.min(cap, Math.min(cell, length - j * cell)) - count)))
  const baselineSkips = baseline.flat().reduce((s, n) => s + n, 0)
  const arcLength = length * rise
  const maxAngleRad = extent > EPS ? Math.min(2 * Math.PI, cap * arcLength / (cell * extent)) : 0
  return { offsets, extent, baseline, capacities, capacityTotals: capacities.map(cells => cells.reduce((s, n) => s + n, 0)), baselineSkips, arcLength, maxAngleRad,
    minRadiusNm: extent > EPS ? cell * extent / cap : null }
}

function quantized(frame, angle) {
  // Event representatives lie inside rounding intervals; endpoints use deterministic half-up rounding.
  const counts = frame.offsets.map(r => Math.sign(-r) * Math.floor(Math.abs(r) * angle / limits.rise_nm + 0.5 + 1e-10))
  const loops = counts.reduce((s, d) => s + Math.max(0, d), 0)
  const bendSkips = counts.reduce((s, d) => s + Math.max(0, -d), 0)
  return { counts, loops, bendSkips, skips: bendSkips + frame.baselineSkips }
}

export function curvatureCatalog(entry, length, { reserve = 0 } = {}) {
  if (!Number.isInteger(length) || length < 21 || length > 7249 || !Number.isInteger(reserve) || reserve < 0 || reserve >= 7249) throw new Error('Invalid curvature budget')
  const frame = curvatureFrame(entry, length)
  const events = [0, frame.maxAngleRad]
  for (const r of frame.offsets) if (Math.abs(r) > EPS) {
    const rate = Math.abs(r) / limits.rise_nm
    for (let n = 0; (n + 0.5) / rate < frame.maxAngleRad - EPS; n++) events.push((n + 0.5) / rate)
  }
  const breaks = [...new Set(events.map(x => Math.round(x * 1e11) / 1e11))].sort((a, b) => a - b)
  const grouped = new Map()
  const add = (angle, low, high) => {
    const q = quantized(frame, angle), key = `${q.loops}:${q.skips}`
    const existing = grouped.get(key)
    if (existing) {
      existing.angleMinRad = Math.min(existing.angleMinRad, low); existing.angleMaxRad = Math.max(existing.angleMaxRad, high)
      if (Math.abs(angle - frame.maxAngleRad) < EPS && q.loops + q.bendSkips > 0) {
        existing.angleRad = angle; existing.maxDeltaPerCell = limits.cell_bp * frame.extent * angle / frame.arcLength
      }
      return
    }
    const used = entry.helices * length + q.loops - q.skips
    const capacityOK = q.counts.every((n, i) => Math.abs(n) <= frame.capacityTotals[i])
    const maxDensity = limits.cell_bp * frame.extent * angle / frame.arcLength
    grouped.set(key, { key, ...q, angleRad: q.loops + q.bendSkips === 0 ? 0 : angle,
      angleMinRad: low, angleMaxRad: high, used, remainder: 7249 - used,
      maxDeltaPerCell: maxDensity, baselineSkips: frame.baselineSkips,
      eligible: capacityOK && used + reserve <= 7249 && maxDensity <= limits.max_delta_per_cell + 1e-7,
      rejection: !capacityOK ? 'Insufficient per-cell capacity after square compensation' : used + reserve > 7249 ? 'Exceeds 7249-nt budget' : null })
  }
  add(0, 0, 0)
  for (let i = 1; i < breaks.length; i++) add((breaks[i - 1] + breaks[i]) / 2, breaks[i - 1], breaks[i])
  // Include a 360°/density-bound endpoint if it quantizes to a new count class.
  add(frame.maxAngleRad, frame.maxAngleRad, frame.maxAngleRad)
  const classes = [...grouped.values()].map((state, index) => ({ ...state, index,
    angleDeg: state.angleRad * 180 / Math.PI,
    radiusNm: state.angleRad > EPS ? frame.arcLength / state.angleRad : null }))
  return { entry, length, reserve, frame, classes, states: classes.filter(s => s.eligible),
    maxAngleDeg: frame.maxAngleRad * 180 / Math.PI,
    excluded: classes.filter(s => !s.eligible).length,
    scope: 'Uniform planar +X arcs, no added twist. Separate total inserted/deleted bases define classes; allocation and sequence differences are ignored. Square baseline compensation is counted. Preview angles represent one canonical allocation; exact routing and physical relaxation remain unverified.' }
}

/** Five-degree target grid, retaining one representative per I/D count class.
 * A nominal angle is not a claim of exact relaxed curvature after quantization.
 */
export function curvatureSamples(catalog) {
  const { entry, length, reserve, frame } = catalog, step = 5, grouped = new Map()
  const maxSampleAngleDeg = Math.floor((catalog.maxAngleDeg + 1e-8) / step) * step
  for (let degrees = 0; degrees <= maxSampleAngleDeg; degrees += step) {
    const angle = degrees * Math.PI / 180, q = quantized(frame, angle)
    const key = `${q.loops}:${q.skips}`, used = entry.helices * length + q.loops - q.skips
    const capacityOK = q.counts.every((n, i) => Math.abs(n) <= frame.capacityTotals[i])
    const density = limits.cell_bp * frame.extent * angle / frame.arcLength
    const eligible = capacityOK && used + reserve <= 7249 && density <= limits.max_delta_per_cell + 1e-7
    const state = { key, ...q, angleRad: angle, angleDeg: degrees, angleMinRad: angle, angleMaxRad: angle,
      radiusNm: degrees ? frame.arcLength / angle : null, used, remainder: 7249 - used,
      maxDeltaPerCell: density, baselineSkips: frame.baselineSkips, eligible,
      rejection: !capacityOK ? 'Insufficient per-cell capacity after square compensation' : used + reserve > 7249 ? 'Exceeds 7249-nt budget' : null }
    // Keep the true straight junction. For other repeated classes prefer the
    // largest target on the grid, including 360 degrees when it is admissible.
    if (!grouped.has(key) || grouped.get(key).angleDeg !== 0) grouped.set(key, state)
    if (!eligible) break
  }
  const classes = [...grouped.values()].map((state, index) => ({ ...state, index }))
  return { ...catalog, classes, states: classes.filter(s => s.eligible),
    excluded: classes.filter(s => !s.eligible).length, angleStepDeg: step, maxSampleAngleDeg,
    scope: catalog.scope + ' Tree pruned to 5-degree nominal targets up to the local cap; duplicate I/D classes are merged, keeping the largest grid target except that the zero-modification class stays straight. No off-grid limit endpoint is appended.' }
}

export function cellAllocation(catalog, state) {
  const rows = []
  for (const [helix, total] of state.counts.entries()) {
    const capacities = catalog.frame.capacities[helix], available = capacities.reduce((s, c) => s + c, 0)
    let prefix = 0, previous = 0
    for (const [cell, capacity] of capacities.entries()) {
      prefix += capacity
      const next = available ? Math.floor(Math.abs(total) * prefix / available + EPS) : 0
      const count = next - previous; previous = next
      rows.push({ helix, startBp: cell * limits.cell_bp, length: Math.min(limits.cell_bp, catalog.length - cell * limits.cell_bp),
        loops: total > 0 ? count : 0, skips: catalog.frame.baseline[helix][cell] + (total < 0 ? count : 0) })
    }
  }
  return rows
}

export function curvatureTree(catalog) {
  const { entry, length } = catalog, sign = entry.lattice === 'square' ? -1 : 1
  const nodes = catalog.states.map(state => ({ id: `${entry.id}:curve:${length}:${state.key}`, entry, length, center: 'Curvature', lattice: entry.lattice,
    index: state.index, curvature: state, label: `${state.angleDeg.toFixed(1)}°`, routing: routingScreen(entry),
    position: [sign * (7 + 16 * state.index / Math.max(1, catalog.classes.length - 1)), 3 + 27 * state.index / Math.max(1, catalog.classes.length - 1), 0] }))
  const edges = []
  for (let i = 1; i < nodes.length; i++) if (nodes[i].index === nodes[i - 1].index + 1) {
    const a = nodes[i - 1], b = nodes[i]
    edges.push({ from: a.id, to: b.id, parameter: 'curvature-counts', lattice: entry.lattice, center: 'Curvature', length,
      deltaLoops: b.curvature.loops - a.curvature.loops, deltaSkips: b.curvature.skips - a.curvature.skips,
      label: `ΔI ${b.curvature.loops - a.curvature.loops}, ΔD ${b.curvature.skips - a.curvature.skips}` })
  }
  return { nodes, edges, stems: nodes.length ? [{ to: nodes[0].id, lattice: entry.lattice }] : [], length, structureCount: nodes.length, filter: 'curvature-budget' }
}

export function curvatureWindow(model, selectedId, size = 41) {
  const selected = Math.max(0, model.nodes.findIndex(n => n.id === selectedId))
  const start = Math.max(0, Math.min(selected - Math.floor(size / 2), model.nodes.length - size))
  const nodes = model.nodes.slice(start, start + size).map((n, i, all) => {
    const t = i / Math.max(1, all.length - 1), sign = n.lattice === 'square' ? -1 : 1
    return { ...n, position: [sign * (7 + 17 * t), 3 + 27 * t, Math.sin(t * Math.PI) * 5] }
  })
  const ids = new Set(nodes.map(n => n.id))
  return { ...model, nodes, edges: model.edges.filter(e => ids.has(e.from) && ids.has(e.to)),
    stems: nodes.length ? [{ to: nodes[0].id, lattice: nodes[0].lattice }] : [], windowStart: start, totalNodes: model.nodes.length }
}
