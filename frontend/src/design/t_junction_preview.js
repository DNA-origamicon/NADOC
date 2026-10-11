/**
 * Read-only end-to-side scaffold splice examples for Help > T-junctions.
 *
 * MagicDNA exposes a side node by opening one scaffold backbone between two
 * adjacent bases on the SAME helix. An end node opens a turn between DIFFERENT
 * helices. Exchanging their directed successors joins two cycles:
 *   remove a -> b and c -> d; add a -> d and c -> b.
 *
 * This is an independently implemented educational model, not a port of the
 * MagicDNA router or a native NADOC design. Duplex axes stay intact at the side
 * port. Helix phase, linker contour, staples and mechanics are not validated.
 * The single DSCC illustrates topology; it does not make a rigid 6HB weld.
 */

export const T_JUNCTION_SOURCES = Object.freeze({
  paper: 'https://doi.org/10.1038/s41563-021-00978-5',
  supplement: 'https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-021-00978-5/MediaObjects/41563_2021_978_MOESM1_ESM.pdf',
  code: 'https://github.com/cmhuang2011/MagicDNA/blob/fd09b660b542e03a6d3f87dc2f5ff871219c8eab/class/hyperbundle.m#L6146',
})

const add = (a, b) => a.map((v, i) => v + b[i])
const sub = (a, b) => a.map((v, i) => v - b[i])
const mul = (a, t) => a.map(v => v * t)
const length = a => Math.hypot(...a)
const mix = (a, b, t) => add(mul(a, 1 - t), mul(b, t))
const TAU = 2 * Math.PI
const RISE = .334
const BODY_BP = 176
const BRANCH_BP = 96
const BUNDLE_RADIUS = 2.25
const BACKBONE_RADIUS = .86

function parameter(value, fallback, low, high) {
  const n = Number(value ?? fallback)
  return Math.max(low, Math.min(high, Number.isFinite(n) ? n : fallback))
}

function cubic(p0, p1, p2, p3, samples = 12) {
  return Array.from({ length: samples + 1 }, (_, i) => {
    const t = i / samples, s = 1 - t
    return add(add(mul(p0, s ** 3), mul(p1, 3 * s * s * t)), add(mul(p2, 3 * s * t * t), mul(p3, t ** 3)))
  })
}

function bundleCycle(id, origin, axis, u, v, bpCount) {
  const helices = [], nodes = [], edges = []
  for (let h = 0; h < 6; h++) {
    const beta = TAU * h / 6
    const offset = add(mul(u, BUNDLE_RADIUS * Math.cos(beta)), mul(v, BUNDLE_RADIUS * Math.sin(beta)))
    const start = add(origin, offset), end = add(start, mul(axis, bpCount * RISE))
    const helixId = `${id}-h${h}`
    helices.push({ id: helixId, bundle: id, start, end, radiusNm: 1 })
    const indices = Array.from({ length: bpCount + 1 }, (_, i) => h % 2 ? bpCount - i : i)
    for (const bpIndex of indices) {
      // A readable ideal helix trace, not a solved junction phase assignment.
      const phase = TAU * bpIndex / 10.5 + h * Math.PI
      const radial = add(mul(u, BACKBONE_RADIUS * Math.cos(phase)), mul(v, BACKBONE_RADIUS * Math.sin(phase)))
      nodes.push({ id: `${helixId}:${bpIndex}`, bundle: id, helixId, bpIndex,
        direction: h % 2 ? 'REVERSE' : 'FORWARD', position: add(add(start, mul(axis, bpIndex * RISE)), radial) })
    }
  }
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i], b = nodes[(i + 1) % nodes.length]
    const turn = a.helixId !== b.helixId
    const outward = mul(axis, a.bpIndex === 0 ? -1 : 1)
    const points = turn
      ? cubic(a.position, add(a.position, mul(outward, 1.1)), add(b.position, mul(outward, 1.1)), b.position)
      : [a.position, b.position]
    edges.push({ id: `${a.id}->${b.id}`, from: a.id, to: b.id, kind: turn ? 'end-turn' : 'backbone', points })
  }
  return { helices, nodes, edges }
}

/** Trace and check a directed union of cycles without relying on point proximity. */
export function traceScaffoldCycles(nodes, edges) {
  const outgoing = new Map(), incoming = new Map(), byId = new Map(nodes.map(n => [n.id, n]))
  if (byId.size !== nodes.length) throw new Error('Duplicate scaffold node')
  for (const edge of edges) {
    if (!byId.has(edge.from) || !byId.has(edge.to)) throw new Error('Unknown scaffold endpoint')
    if (outgoing.has(edge.from) || incoming.has(edge.to)) throw new Error('Scaffold branches or terminates at a duplicated endpoint')
    outgoing.set(edge.from, edge); incoming.set(edge.to, edge)
  }
  if (outgoing.size !== nodes.length || incoming.size !== nodes.length) throw new Error('Scaffold has an open end')
  const visited = new Set(), cycles = []
  for (const first of nodes) {
    if (visited.has(first.id)) continue
    const nodeIds = [], edgeIds = [], points = []
    let id = first.id
    do {
      if (visited.has(id)) throw new Error('Scaffold cycle enters a previously visited path')
      visited.add(id); nodeIds.push(id)
      const edge = outgoing.get(id)
      edgeIds.push(edge.id)
      points.push(...(points.length ? edge.points.slice(1) : edge.points))
      id = edge.to
    } while (id !== first.id)
    cycles.push({ nodeIds, edgeIds, points })
  }
  return cycles
}

export function buildTJunctionPreviewModel(input = {}) {
  const angleDeg = parameter(input.angleDeg, 90, 30, 150)
  const azimuthDeg = parameter(input.azimuthDeg, 0, -60, 60)
  const attachment = parameter(input.attachment, .5, .2, .8)
  const joined = input.joined !== false
  const theta = angleDeg * Math.PI / 180, phi = azimuthDeg * Math.PI / 180
  const xAxis = [1, 0, 0], normal = [0, Math.cos(phi), Math.sin(phi)], v = [0, -Math.sin(phi), Math.cos(phi)]
  const axis = add(mul(xAxis, Math.cos(theta)), mul(normal, Math.sin(theta)))
  const u = sub(mul(xAxis, Math.sin(theta)), mul(normal, Math.cos(theta)))
  const branchV = mul(v, -1) // axis × u = -v: keep both bundles' helices right-handed.
  const body = bundleCycle('body', [-BODY_BP * RISE / 2, 0, 0], xAxis, normal, v, BODY_BP)

  // Select a nearby outward-facing h0 site, illustrating the discrete nature of
  // a surface port. Moving the slider never cuts the physical duplex cylinder.
  const desiredBp = attachment * BODY_BP
  const candidates = Array.from({ length: BODY_BP - 2 }, (_, i) => i + 1)
    .filter(bp => Math.cos(TAU * bp / 10.5) > .5 && Math.cos(TAU * (bp + 1) / 10.5) > .5)
  const portBp = candidates.reduce((best, bp) => Math.abs(bp + .5 - desiredBp) < Math.abs(best + .5 - desiredBp) ? bp : best)
  const a = body.nodes.find(n => n.id === `body-h0:${portBp}`)
  const b = body.nodes.find(n => n.id === `body-h0:${portBp + 1}`)
  const bodyCut = body.edges.find(e => e.from === a.id && e.to === b.id)

  // Keep the entire donor blunt face outside the host envelope even for an
  // acute angle; two ssDNA bridges span the remaining gap. The displayed angle
  // is a pose, not an equilibrium prediction or a rigidity constraint.
  const radialClearance = BUNDLE_RADIUS + 2.8 + BUNDLE_RADIUS * Math.abs(Math.cos(theta))
  const target = add([mix(a.position, b.position, .5)[0], 0, 0], mul(normal, radialClearance))
  let branch = bundleCycle('branch', target, axis, u, branchV, BRANCH_BP)
  const firstTurn = branch.edges.at(-1)
  const turnMid = mix(firstTurn.points[0], firstTurn.points.at(-1), .5)
  const shift = add(mul(xAxis, target[0] - turnMid[0]), mul(v, -v.reduce((sum, value, i) => sum + value * turnMid[i], 0)))
  branch = bundleCycle('branch', add(target, shift), axis, u, branchV, BRANCH_BP)
  const branchCut = branch.edges.at(-1)
  const c = branch.nodes.find(n => n.id === branchCut.from), d = branch.nodes.find(n => n.id === branchCut.to)

  const bridge = (id, label, from, to, color) => ({ id, label, from: from.id, to: to.id, kind: 'junction', color,
    points: cubic(from.position, mix(from.position, to.position, .33), mix(from.position, to.position, .67), to.position) })
  const newEdges = [bridge('outbound', 'Body 3′ → branch 5′', a, d, '#ffb454'), bridge('return', 'Branch 3′ → body 5′', c, b, '#7ee8b1')]
  const nodes = [...body.nodes, ...branch.nodes], originalEdges = [...body.edges, ...branch.edges]
  const cutIds = new Set([bodyCut.id, branchCut.id])
  const edges = joined ? [...originalEdges.filter(e => !cutIds.has(e.id)), ...newEdges] : originalEdges
  const cycles = traceScaffoldCycles(nodes, edges)
  const routes = cycles.map((cycle, i) => ({ id: `scaffold-${i + 1}`, color: i ? '#c5a3ff' : '#67d5f5', closed: true, ...cycle }))
  const bridgeSpans = newEdges.map(e => length(sub(e.points.at(-1), e.points[0])))
  return {
    params: { angleDeg, azimuthDeg, attachment, joined, actualAttachment: (portBp + .5) / BODY_BP, portBp },
    helices: [...body.helices, ...branch.helices], routes,
    bridges: joined ? newEdges : [],
    cuts: [bodyCut, branchCut].map((edge, i) => ({ ...edge, label: i ? 'Opened donor end turn' : 'Opened body scaffold edge' })),
    ports: [
      { id: 'body-out', label: 'a · body 3′', position: a.position, nodeId: a.id },
      { id: 'body-return', label: 'b · body 5′', position: b.position, nodeId: b.id },
      { id: 'branch-return', label: 'c · branch 3′', position: c.position, nodeId: c.id },
      { id: 'branch-in', label: 'd · branch 5′', position: d.position, nodeId: d.id },
    ],
    metrics: { cyclesBefore: 2, cyclesAfter: cycles.length, helixCount: 12, bridgeCount: joined ? 2 : 0,
      maxBridgeSpanNm: Math.max(...bridgeSpans), scaffoldSites: nodes.length, connectionPairs: joined ? 1 : 0 },
    topology: { nodes, edges, originalEdges, removedEdges: [bodyCut, branchCut], proposedBridges: newEdges },
    warnings: ['One connection pair demonstrates routing; it does not establish a rigid joint.',
      'Linker lengths, helical phase, staple reinforcement and stability are not validated.'],
    explanation: joined
      ? 'Two scaffold links join the cycles: body → branch, then branch → body. The body duplex continues through the attachment site.'
      : 'Two separate scaffold cycles. The marked body-side edge and donor end turn are the two places opened when joining.',
  }
}
