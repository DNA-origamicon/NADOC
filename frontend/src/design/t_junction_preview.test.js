import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { buildTJunctionPreviewModel, traceScaffoldCycles } from './t_junction_preview.js'
import { buildTJunctionPreviewGroup, disposeTJunctionPreviewGroup } from '../scene/t_junction_preview.js'

const sub = (a, b) => a.map((value, i) => value - b[i])
const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0)
const norm = a => Math.hypot(...a)
const unit = a => a.map(value => value / norm(a))
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const distance = (a, b) => norm(sub(a, b))

// Independent graph oracle: do not trust the model's cycle count or its tracer.
function auditDirectedCycles(nodes, edges) {
  const ids = new Set(nodes.map(node => node.id))
  expect(ids.size).toBe(nodes.length)
  expect(new Set(edges.map(edge => edge.id)).size).toBe(edges.length)
  const outgoing = new Map(), incoming = new Map()
  for (const edge of edges) {
    expect(ids.has(edge.from) && ids.has(edge.to)).toBe(true)
    expect(outgoing.has(edge.from)).toBe(false)
    expect(incoming.has(edge.to)).toBe(false)
    outgoing.set(edge.from, edge)
    incoming.set(edge.to, edge)
  }
  expect(outgoing.size).toBe(nodes.length)
  expect(incoming.size).toBe(nodes.length)
  const visited = new Set(), cycles = []
  for (const start of ids) {
    if (visited.has(start)) continue
    const cycle = []
    let current = start
    do {
      expect(visited.has(current)).toBe(false)
      visited.add(current)
      cycle.push(current)
      current = outgoing.get(current).to
    } while (current !== start)
    cycles.push(cycle)
  }
  expect(visited.size).toBe(nodes.length)
  return cycles
}

describe('T-junction scaffold topology audit', () => {
  it('exchanges two directed successors and visits every original site exactly once', () => {
    const separate = buildTJunctionPreviewModel({ joined: false })
    const joined = buildTJunctionPreviewModel()
    const { nodes, edges, originalEdges, removedEdges, proposedBridges } = joined.topology
    expect(auditDirectedCycles(nodes, originalEdges)).toHaveLength(2)
    expect(auditDirectedCycles(nodes, edges)).toHaveLength(1)
    expect(joined.routes).toHaveLength(1)
    expect(separate.routes).toHaveLength(2)
    expect(nodes).toEqual(separate.topology.nodes)
    expect(removedEdges).toHaveLength(2)
    expect(proposedBridges).toHaveLength(2)
    const [bodyCut, branchCut] = removedEdges
    expect(proposedBridges.map(edge => [edge.from, edge.to])).toEqual([
      [bodyCut.from, branchCut.to], [branchCut.from, bodyCut.to],
    ])
    const retained = originalEdges.filter(edge => !removedEdges.some(cut => cut.id === edge.id))
    expect(edges.filter(edge => edge.kind !== 'junction')).toEqual(retained)
    expect(edges.filter(edge => edge.kind === 'junction')).toEqual(proposedBridges)
    expect(edges).toHaveLength(originalEdges.length)
    expect(new Set(joined.routes[0].nodeIds)).toEqual(new Set(nodes.map(node => node.id)))
    expect(joined.routes[0].nodeIds).toHaveLength(nodes.length)
    expect(new Set(joined.routes[0].edgeIds)).toEqual(new Set(edges.map(edge => edge.id)))
  })

  it('opens one interior body backbone and one donor end turn without cutting duplex axes', () => {
    const model = buildTJunctionPreviewModel()
    const before = buildTJunctionPreviewModel({ joined: false })
    expect(model.helices).toEqual(before.helices)
    expect(model.helices.filter(helix => helix.bundle === 'body')).toHaveLength(6)
    const nodes = new Map(model.topology.nodes.map(node => [node.id, node]))
    const [bodyCut, branchCut] = model.topology.removedEdges
    const [a, b, c, d] = [bodyCut.from, bodyCut.to, branchCut.from, branchCut.to].map(id => nodes.get(id))
    expect(bodyCut.kind).toBe('backbone')
    expect(a.bundle).toBe('body')
    expect(a.helixId).toBe(b.helixId)
    expect(b.bpIndex - a.bpIndex).toBe(a.direction === 'FORWARD' ? 1 : -1)
    const indices = model.topology.nodes.filter(node => node.helixId === a.helixId).map(node => node.bpIndex)
    expect(Math.min(a.bpIndex, b.bpIndex)).toBeGreaterThan(Math.min(...indices))
    expect(Math.max(a.bpIndex, b.bpIndex)).toBeLessThan(Math.max(...indices))
    expect(branchCut.kind).toBe('end-turn')
    expect(c.bundle).toBe('branch')
    expect(d.bundle).toBe('branch')
    expect(c.helixId).not.toBe(d.helixId)
    expect(c.bpIndex).toBe(d.bpIndex)
    expect(c.direction).not.toBe(d.direction)
    expect(model.ports.map(port => port.nodeId)).toEqual([a.id, b.id, c.id, d.id])
    for (const port of model.ports) expect(port.position).toEqual(nodes.get(port.nodeId).position)
  })

  it('aligns every rendered edge with its directed endpoints and route order', () => {
    const model = buildTJunctionPreviewModel({ angleDeg: 57, azimuthDeg: -37, attachment: .73 })
    const nodes = new Map(model.topology.nodes.map(node => [node.id, node]))
    const edges = new Map(model.topology.edges.map(edge => [edge.id, edge]))
    for (const edge of edges.values()) {
      expect(distance(edge.points[0], nodes.get(edge.from).position)).toBeLessThan(1e-10)
      expect(distance(edge.points.at(-1), nodes.get(edge.to).position)).toBeLessThan(1e-10)
    }
    for (const route of model.routes) {
      for (let i = 0; i < route.nodeIds.length; i++) {
        const edge = edges.get(route.edgeIds[i])
        expect(edge.from).toBe(route.nodeIds[i])
        expect(edge.to).toBe(route.nodeIds[(i + 1) % route.nodeIds.length])
      }
      expect(distance(route.points[0], route.points.at(-1))).toBeLessThan(1e-10)
    }
    const group = buildTJunctionPreviewGroup(model, { representation: 'scaffold' })
    try {
      const arrows = group.children.filter(object => object.userData.kind === 'bridge-direction')
      expect(arrows).toHaveLength(2)
      arrows.forEach((arrow, index) => {
        const bridge = model.bridges[index]
        const directedChord = unit(sub(bridge.points.at(-1), bridge.points[0]))
        const renderedDirection = new THREE.Vector3(0, 1, 0).applyQuaternion(arrow.quaternion).toArray()
        expect(dot(renderedDirection, directedChord)).toBeGreaterThan(.999999)
      })
    } finally { disposeTJunctionPreviewGroup(group) }
  })

  it('detects the wrong-polarity splice rather than mistaking it for a joined route', () => {
    const model = buildTJunctionPreviewModel()
    const malformed = model.topology.edges.map(edge => edge.id === 'return'
      ? { ...edge, from: edge.to, to: edge.from } : edge)
    expect(() => traceScaffoldCycles(model.topology.nodes, malformed)).toThrow()
    expect(() => traceScaffoldCycles(model.topology.nodes, model.topology.edges.slice(1))).toThrow()
    const unknown = model.topology.edges.map((edge, index) => index ? edge : { ...edge, to: 'unknown-site' })
    expect(() => traceScaffoldCycles(model.topology.nodes, unknown)).toThrow()
  })
})

describe('T-junction geometry audit', () => {
  it.each([
    { angleDeg: 30, azimuthDeg: -60, attachment: .2 },
    { angleDeg: 30, azimuthDeg: 60, attachment: .8 },
    { angleDeg: 90, azimuthDeg: 0, attachment: .5 },
    { angleDeg: 150, azimuthDeg: -60, attachment: .8 },
    { angleDeg: 150, azimuthDeg: 60, attachment: .2 },
  ])('preserves topology and donor-face clearance at %o', params => {
    const model = buildTJunctionPreviewModel(params)
    expect(auditDirectedCycles(model.topology.nodes, model.topology.edges)).toHaveLength(1)
    expect(model.topology.nodes.flatMap(node => node.position).every(Number.isFinite)).toBe(true)
    expect(model.routes.flatMap(route => route.points.flat()).every(Number.isFinite)).toBe(true)
    const phi = params.azimuthDeg * Math.PI / 180
    const normal = [0, Math.cos(phi), Math.sin(phi)]
    const body = model.helices.filter(helix => helix.bundle === 'body')
    const branch = model.helices.filter(helix => helix.bundle === 'branch')
    const bodyOuterSupport = Math.max(...body.flatMap(helix => [helix.start, helix.end].map(p => dot(p, normal) + helix.radiusNm)))
    const branchInnerSupport = Math.min(...branch.flatMap(helix => [helix.start, helix.end].map(p => dot(p, normal) - helix.radiusNm)))
    expect(branchInnerSupport).toBeGreaterThan(bodyOuterSupport)
    const bodyAxis = unit(sub(body[0].end, body[0].start))
    const branchAxis = unit(sub(branch[0].end, branch[0].start))
    expect(Math.acos(Math.max(-1, Math.min(1, dot(bodyAxis, branchAxis)))) * 180 / Math.PI).toBeCloseTo(params.angleDeg, 8)
  })

  it('uses the same right-handed helical trace in both bundle frames', () => {
    for (const angleDeg of [30, 90, 150]) {
      const model = buildTJunctionPreviewModel({ angleDeg, azimuthDeg: 41 })
      for (const helix of model.helices) {
        const axis = unit(sub(helix.end, helix.start))
        const nodes = model.topology.nodes.filter(node => node.helixId === helix.id).sort((a, b) => a.bpIndex - b.bpIndex)
        const radial = node => {
          const fromStart = sub(node.position, helix.start)
          return sub(fromStart, axis.map(value => value * dot(fromStart, axis)))
        }
        expect(dot(cross(radial(nodes[20]), radial(nodes[21])), axis)).toBeGreaterThan(0)
      }
    }
  })

  it('selects the nearest exposed discrete side port and keeps the host axes fixed while sliding', () => {
    let previous = null
    const selected = new Set()
    for (const attachment of [.2, .25, .4, .5, .50001, .62, .8]) {
      const model = buildTJunctionPreviewModel({ attachment })
      const [cut] = model.topology.removedEdges
      const byId = new Map(model.topology.nodes.map(node => [node.id, node]))
      const helix = model.helices.find(h => h.id === byId.get(cut.from).helixId)
      const sites = model.topology.nodes.filter(node => node.helixId === helix.id)
      const minBp = Math.min(...sites.map(node => node.bpIndex)), maxBp = Math.max(...sites.map(node => node.bpIndex))
      const axis = unit(sub(helix.end, helix.start)), normal = [0, 1, 0]
      const isExposed = node => {
        const offset = sub(node.position, helix.start)
        const radial = sub(offset, axis.map(value => value * dot(offset, axis)))
        return dot(radial, normal) > .5 * norm(radial)
      }
      const candidates = model.topology.originalEdges.filter(edge => {
        const a = byId.get(edge.from), b = byId.get(edge.to)
        return a.helixId === helix.id && b.helixId === helix.id
          && a.bpIndex > minBp && b.bpIndex < maxBp && isExposed(a) && isExposed(b)
      })
      const miss = edge => Math.abs((byId.get(edge.from).bpIndex + byId.get(edge.to).bpIndex) / 2 - attachment * maxBp)
      expect(miss(cut)).toBeCloseTo(Math.min(...candidates.map(miss)), 9)
      const body = model.helices.filter(h => h.bundle === 'body')
      if (previous) expect(body).toEqual(previous)
      previous = body
      selected.add(model.params.portBp)
    }
    expect(selected.size).toBeGreaterThan(3)
    expect(buildTJunctionPreviewModel({ attachment: .5 }).params.portBp)
      .toBe(buildTJunctionPreviewModel({ attachment: .50001 }).params.portBp)
  })

  it('bounds malformed controls and remains a conceptual example without editing inputs', () => {
    const input = { angleDeg: Infinity, azimuthDeg: 'bad', attachment: -2, joined: false }
    const copy = { ...input }
    const model = buildTJunctionPreviewModel(input)
    expect(input).toEqual(copy)
    expect(model.params.angleDeg).toBe(90)
    expect(model.params.azimuthDeg).toBe(0)
    expect(model.params.attachment).toBe(.2)
    expect(model.bridges).toHaveLength(0)
    expect(model.metrics.connectionPairs).toBe(0)
    expect(model.routes).toHaveLength(2)
    expect(model.warnings.join(' ')).toMatch(/not.*rigid|does not establish a rigid/)
    expect(model.warnings.join(' ')).toMatch(/not validated/)
  })
})
