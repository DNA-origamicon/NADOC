/** Connectivity grammar for bundle origami previews, independent of the viewer.
 * Rules: extend a bundle, partition its lanes into two daughter bundles, repeat.
 * A connected acyclic tree is enforced: no mesh faces, braces or custom hubs.
 * HB counts are lane demands, not a claim of a routed/validated lattice section.
 */
const add = (a, b) => a.map((v, i) => v + b[i])
const sub = (a, b) => a.map((v, i) => v - b[i])
const mul = (a, s) => a.map(v => v * s)
const norm = a => Math.hypot(...a)
const unit = a => norm(a) > 1e-9 ? mul(a, 1 / norm(a)) : [1, 0, 0]
const mean = points => mul(points.reduce(add, [0, 0, 0]), 1 / points.length)
const distance = (a, b) => norm(sub(a, b))
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0)
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

export function nanoparticleSites(design) {
  return (design?.nanoparticles || []).filter(p => p.kind === 'gold_nanosphere').map((p, i) => {
    const v = p.pose?.values
    return { id: p.id, label: p.name || p.label || `NP ${i + 1}`, center: v ? [v[3], v[7], v[11]] : [NaN, NaN, NaN], radius: p.diameter_nm / 2 }
  })
}

// A bounded beam over merge histories discovers different binary topologies.
// Every particle is tried as the stem terminal; child order has no significance.
function hierarchies(leaves, width = 12) {
  let beam = [{ clusters: leaves.map(p => ({ key: p.id, leaves: [p], center: p.center })), cost: 0 }]
  while (beam[0].clusters.length > 1) {
    const next = new Map()
    for (const state of beam) {
      const cs = state.clusters
      for (let i = 0; i < cs.length; i++) for (let j = i + 1; j < cs.length; j++) {
        const children = [cs[i], cs[j]].sort((a, b) => a.key.localeCompare(b.key))
        const ps = children.flatMap(c => c.leaves)
        const merged = { key: `(${children.map(c => c.key).join('|')})`, children, leaves: ps, center: mean(ps.map(p => p.center)) }
        const clusters = [...cs.filter((_, k) => k !== i && k !== j), merged].sort((a, b) => a.key.localeCompare(b.key))
        const key = clusters.map(c => c.key).join(';')
        const cost = state.cost + distance(cs[i].center, cs[j].center)
        if (!next.has(key) || cost < next.get(key).cost) next.set(key, { clusters, cost })
      }
    }
    beam = [...next.values()].sort((a, b) => a.cost - b.cost).slice(0, width)
  }
  return beam.map(s => s.clusters[0])
}

export function sampleEdge(edge, steps = 32) {
  const [a, b, c, d] = edge.controlPoints
  return Array.from({ length: steps + 1 }, (_, i) => {
    const t = i / steps, u = 1 - t
    return a.map((v, k) => u*u*u*v + 3*u*u*t*b[k] + 3*u*t*t*c[k] + t*t*t*d[k])
  })
}

function buildCandidate(root, hierarchy, sites, setback, opposing = null) {
  const nodes = [], edges = []
  const rootAxis = unit(sub(hierarchy.center, root.center))
  const terminal = p => ({ id: `np:${p.id}`, kind: 'particle', particleId: p.id, label: p.label, position: p.center })
  const start = opposing ? {
    id: 'split:0', kind: 'split', position: root.center,
    motif: 'shared-section-split', sectionHB: opposing.leaves.length * 6,
    daughterHB: opposing.children.map(c => c.leaves.length * 6),
    label: `${opposing.leaves.length * 6}HB → ${opposing.children.map(c => c.leaves.length * 6 + 'HB').join(' + ')}`,
  } : terminal(root)
  nodes.push(start)
  // Shift each split upstream from its descendant centroid. Nested splits retain
  // a common tangent and have distinct straight stem regions; never join wires
  // at an arbitrary multi-way vertex.
  function grow(parent, cluster, incoming, depth) {
    const leaf = !cluster.children
    const center = cluster.center
    const position = leaf ? center : add(center, mul(unit(sub(center, parent.position)), -distance(center, parent.position) * setback))
    const node = leaf ? terminal(cluster.leaves[0]) : {
      id: `split:${nodes.length}`, kind: 'split', position,
      motif: 'shared-section-split', sectionHB: cluster.leaves.length * 6,
      daughterHB: cluster.children.map(c => c.leaves.length * 6),
      label: `${cluster.leaves.length * 6}HB → ${cluster.children.map(c => c.leaves.length * 6 + 'HB').join(' + ')}`,
    }
    nodes.push(node)
    const axis = unit(sub(position, parent.position)), hb = cluster.leaves.length * 6
    const from = parent.kind === 'particle' ? add(parent.position, mul(axis, root.radius + 2)) : parent.position
    const to = leaf ? add(position, mul(axis, -(cluster.leaves[0].radius + 2))) : position
    const length = distance(from, to), handle = Math.min(length * .32, 12)
    // Both daughter paths leave their shared section parallel to the parent.
    const direction = parent.kind === 'split' ? incoming : axis
    const edge = { id: `edge:${edges.length}`, source: parent.id, target: node.id, hb, depth,
      controlPoints: [from, add(from, mul(direction, handle)), add(to, mul(axis, -handle)), to] }
    edges.push(edge)
    if (!leaf) for (const child of cluster.children) grow(node, child, axis, depth + 1)
  }
  grow(start, hierarchy, rootAxis, 0)
  if (opposing) for (const child of opposing.children) grow(start, child, mul(rootAxis, -1), 1)
  let contourNm = 0, scaffoldNt = 0, complianceProxy = 0, clashes = 0, tightSplits = 0
  const radiusForHB = hb => 1.25 * Math.sqrt(hb)
  for (const edge of edges) {
    const points = sampleEdge(edge)
    edge.lengthNm = points.slice(1).reduce((s, p, i) => s + distance(p, points[i]), 0)
    contourNm += edge.lengthNm
    scaffoldNt += Math.ceil(edge.lengthNm / .34) * edge.hb
    // A ranking heuristic only: compact bundles have I roughly proportional to HB².
    complianceProxy += edge.lengthNm ** 3 / edge.hb ** 2
    for (const p of sites) {
      if (edge.source === `np:${p.id}` || edge.target === `np:${p.id}`) continue
      if (points.some(point => distance(point, p.center) < p.radius + radiusForHB(edge.hb))) clashes++
    }
    if (edge.lengthNm < 7 && nodes.find(n => n.id === edge.target).kind === 'split') tightSplits++
  }
  // Detect bundle/bundle intersections away from the shared-section transition.
  let crossings = 0
  for (let i = 0; i < edges.length; i++) for (let j = i + 1; j < edges.length; j++) {
    const a = edges[i], b = edges[j]
    if ([a.source, a.target].some(id => id === b.source || id === b.target)) continue
    if (sampleEdge(a, 12).some(p => sampleEdge(b, 12).some(q => distance(p, q) < radiusForHB(a.hb) + radiusForHB(b.hb)))) crossings++
  }
  const warnings = []
  if (clashes) warnings.push('Bundle path intersects another nanoparticle')
  if (crossings) warnings.push('Nonadjacent bundles overlap')
  if (tightSplits) warnings.push('Short common-section transition')
  const estimatedNt = Math.ceil(scaffoldNt)
  const budget = estimatedNt <= 7249 ? 7249 : estimatedNt <= 8064 ? 8064 : null
  if (!budget) warnings.push('Estimated bundle length exceeds 8064 nt')
  return { rootId: root.id, rootLabel: root.label, topology: hierarchy.key, setback, nodes, edges,
    estimatedNt, budget, contourNm, complianceProxy, warnings, family: opposing ? 'opposed-splits' : 'rooted-splits',
    // Geometric conflicts take priority; stiffness proxy differentiates only previews.
    score: clashes * 1e9 + crossings * 1e9 + tightSplits * 1e8 + (!budget ? 1e7 : 0) + complianceProxy }
}

export function discoverConnectivity(sites) {
  if (sites.length < 2) return { candidates: [], message: 'Add at least two gold nanoparticles to see connectivity.' }
  if (sites.length > 8) return { candidates: [], message: 'This first grammar pass supports 2–8 gold nanoparticles.' }
  if (new Set(sites.map(p => p.id)).size !== sites.length || sites.some(p => !p.id || !p.center?.every(Number.isFinite) || p.center.length !== 3 || !Number.isFinite(p.radius) || p.radius <= 0)) {
    return { candidates: [], message: 'Nanoparticles need unique IDs, finite positions and positive diameters.' }
  }
  if (sites.some((a, i) => sites.slice(i + 1).some(b => distance(a.center, b.center) <= a.radius + b.radius + 4))) {
    return { candidates: [], message: 'Nanoparticles overlap or leave less than 4 nm between surfaces. Separate them to preview bundle connectivity.' }
  }
  const candidates = []
  for (const root of sites) for (const h of hierarchies(sites.filter(p => p !== root))) {
    for (const setback of [.25, .45]) candidates.push(buildCandidate(root, h, sites, setback))
  }
  // A common stem can split at BOTH ends (the I family). Equal lane demands
  // keep the same section all along the connecting stem, without custom hubs.
  if (sites.length >= 4 && sites.length % 2 === 0) {
    for (const tree of hierarchies(sites)) {
      const [left, right] = tree.children
      if (left.leaves.length !== right.leaves.length) continue
      for (const setback of [.25, .45]) {
        const center = add(left.center, mul(sub(right.center, left.center), setback / 2))
        const root = { id: `stem:${left.key}`, label: 'common central stem', center, radius: 0 }
        const c = buildCandidate(root, right, sites, setback, left)
        c.topology = tree.key; candidates.push(c)
      }
    }
  }
  candidates.sort((a, b) => a.score - b.score || a.rootId.localeCompare(b.rootId) || a.topology.localeCompare(b.topology) || a.setback - b.setback)
  // Keep the best geometry for each rooted topology, then show a small diverse set.
  const seen = new Set()
  const unique = candidates.filter(c => {
    const key = `${c.rootId}:${c.topology}`
    if (seen.has(key)) return false
    seen.add(key); return true
  })
  return { candidates: unique.slice(0, 12), evaluated: candidates.length,
    message: 'Bundle-tree proposals · shared-section splits · no wireframe faces' }
}

/** Stable geometry-derived display basis, including collinear and nonplanar inputs. */
export function graphProjection(sites) {
  const origin = mean(sites.map(p => p.center))
  let far = [sites[0].center, sites[1].center], longest = 0
  for (const a of sites) for (const b of sites) if (distance(a.center, b.center) > longest) { far = [a.center, b.center]; longest = distance(...far) }
  const x = unit(sub(far[1], far[0]))
  const residuals = sites.map(p => { const d = sub(p.center, origin); return sub(d, mul(x, dot(d, x))) })
  let y = residuals.sort((a, b) => norm(b) - norm(a))[0]
  if (norm(y) < 1e-8) y = cross(x, Math.abs(x[1]) < .9 ? [0, 1, 0] : [1, 0, 0])
  y = unit(y)
  return p => { const d = sub(p, origin); return [dot(d, x), dot(d, y)] }
}
