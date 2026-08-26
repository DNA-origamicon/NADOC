import { describe, expect, it } from 'vitest'
import {
  buildOccupancyHull,
  hullSpansIgnoringSkips,
  latticeCrossSections,
  supportedLatticeOccupancy,
  usesOccupancyHull,
} from './joint_renderer.js'

const squarePoint = cell => ({ x: cell.col * 2.25, z: cell.row * 2.25 })
const honeycombPoint = cell => ({
  x: cell.col * 1.125 * Math.sqrt(3),
  z: cell.row * 3.375 + (((cell.row & 1) ^ (cell.col & 1)) ? 1.125 : 0),
})
const rectangle = (rows, cols) => {
  const cells = []
  for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) cells.push({ row, col })
  return cells
}

describe('general lattice-union hull', () => {
  it('selects occupancy for imports, including imports later extended in NADOC', () => {
    expect(usesOccupancyHull({ feature_log: [] })).toBe(true)
    expect(usesOccupancyHull({ feature_log: [{ op_kind: 'extrude-continuation' }] })).toBe(true)
    expect(usesOccupancyHull({ feature_log: [
      { op_kind: 'bundle-create' }, { op_kind: 'extrude-continuation' },
    ] })).toBe(false)
  })

  it('bridges explicit skips but preserves deliberate domain gaps', () => {
    expect(hullSpansIgnoringSkips([31, 32, 34, 35, 41], new Set([33]))).toEqual([[31, 36], [41, 42]])
    expect(hullSpansIgnoringSkips([31, 34], new Set([32]))).toEqual([[31, 32], [34, 35]])
  })

  it.each([[3, 6], [2, 10], [5, 5]])('reduces a %ix%i square core to one rectangle', (rows, cols) => {
    const cells = rectangle(rows, cols)
    const sections = latticeCrossSections(cells, cells.map(squarePoint), 'SQUARE')
    expect(sections).toHaveLength(1)
    expect(sections[0].outer).toHaveLength(4)
    expect(sections[0].holes).toHaveLength(0)
  })

  it('preserves an irregular L-shaped square core without rectangularizing it', () => {
    const cells = [[0,0],[0,1],[0,2],[1,0],[2,0]].map(([row, col]) => ({ row, col }))
    const section = latticeCrossSections(cells, cells.map(squarePoint), 'SQUARE')[0]
    expect(section.outer).toHaveLength(6)
    expect(section.holes).toHaveLength(0)
  })

  it('preserves genuine unoccupied square lattice cells as holes', () => {
    const cells = rectangle(3, 3).filter(cell => cell.row !== 1 || cell.col !== 1)
    const section = latticeCrossSections(cells, cells.map(squarePoint), 'SQUARE')[0]
    expect(section.outer).toHaveLength(4)
    expect(section.holes).toHaveLength(1)
    expect(section.holes[0]).toHaveLength(4)
  })

  it('fills a honeycomb interstice that contains no valid lattice site', () => {
    const cells = [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]].map(([row, col]) => ({ row, col }))
    const section = latticeCrossSections(cells, cells.map(honeycombPoint), 'HONEYCOMB')[0]
    expect(section.outer).toHaveLength(6)
    expect(section.holes).toHaveLength(0)
    const sides = section.outer.map((p, i) => {
      const q = section.outer[(i + 1) % section.outer.length]
      return Math.hypot(q.x - p.x, q.z - p.z)
    })
    expect(Math.max(...sides) - Math.min(...sides)).toBeLessThan(1e-8)
  })

  it('sweeps the same topology-derived section through a bend', () => {
    const cells = [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]].map(([row, col]) => ({ row, col }))
    const helices = cells.map((cell, i) => ({ id: `h${i}`, grid_pos: [cell.row, cell.col], bp_start: 0, loop_skips: [] }))
    const axes = {}, geometry = []
    cells.forEach((cell, i) => {
      const p = honeycombPoint(cell)
      axes[`h${i}`] = {
        start: [p.x, p.z, 0], end: [p.x, p.z + 5, 10],
        samples: [[p.x, p.z, 0], [p.x, p.z + 1.5, 5], [p.x, p.z + 5, 10]],
      }
      for (let bp = 0; bp < 15; bp++) for (const strand of ['s', 't']) geometry.push({
        helix_id: `h${i}`, bp_index: bp, strand_id: `${strand}${i}`,
        backbone_position: [p.x, p.z, bp],
      })
    })
    const hull = buildOccupancyHull({ lattice_type: 'HONEYCOMB', helices, strands: [], metadata: {} }, geometry, axes)
    expect(hull.userData.hullAuditVersion).toBe('candidate-general-lattice-union')
    expect(hull.children.find(child => child.isMesh).geometry.attributes.position.count).toBeGreaterThan(0)
    hull.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
  })

  it('derives the reviewed 10HB octagon from occupancy without recognizing a motif', () => {
    const cells = []
    for (const row of [0, 1]) for (let col = -1; col <= 3; col++) cells.push({ row, col })
    const section = latticeCrossSections(cells, cells.map(honeycombPoint), 'HONEYCOMB')[0]
    expect(section.outer).toHaveLength(8)
    expect(section.holes).toHaveLength(0)
  })

  it('reduces a fully occupied 24HB topology to one minimal hexagonal shell', () => {
    const cells = [
      [1,4],[1,3],[1,2],[2,2],[2,3],[2,4],[0,3],[0,2],
      [0,1],[1,1],[1,0],[2,0],[2,1],[3,1],[3,2],[3,3],
      [3,4],[3,5],[2,5],[2,6],[1,6],[1,5],[0,5],[0,4],
    ].map(([row, col]) => ({ row, col }))
    const section = latticeCrossSections(cells, cells.map(honeycombPoint), 'HONEYCOMB')[0]
    expect(section.outer).toHaveLength(6)
    expect(section.holes).toHaveLength(0)
  })

  it('derives Gear_test concavity and its bore from the same boundary rules', () => {
    const cells = [
      [-1,0],[-1,1],[-1,2],[-1,6],[-1,7],[-1,8],
      ...Array.from({ length: 9 }, (_, col) => [0,col]), ...Array.from({ length: 9 }, (_, col) => [1,col]),
      ...[-3,-2,-1,0,1,2,6,7,8,9,10,11].map(col => [2,col]),
      ...[-3,-2,-1,0,1,2,6,7,8,9,10,11].map(col => [3,col]),
      ...Array.from({ length: 9 }, (_, col) => [4,col]), ...Array.from({ length: 9 }, (_, col) => [5,col]),
      [6,0],[6,1],[6,2],[6,6],[6,7],[6,8],
    ].map(([row, col]) => ({ row, col }))
    const section = latticeCrossSections(cells, cells.map(honeycombPoint), 'HONEYCOMB')[0]
    expect(section.outer.length).toBeGreaterThan(6)
    expect(section.holes).toHaveLength(1)
    expect(section.holes[0]).toHaveLength(6)
    const center = {
      x: cells.map(honeycombPoint).reduce((sum, point) => sum + point.x, 0) / cells.length,
      z: cells.map(honeycombPoint).reduce((sum, point) => sum + point.z, 0) / cells.length,
    }
    const angle = Math.PI / 3, ca = Math.cos(angle), sa = Math.sin(angle)
    for (const point of section.outer) {
      const x = point.x - center.x, z = point.z - center.z
      const rotated = { x: center.x + ca * x - sa * z, z: center.z + sa * x + ca * z }
      expect(Math.min(...section.outer.map(candidate =>
        Math.hypot(candidate.x - rotated.x, candidate.z - rotated.z)))).toBeLessThan(1e-8)
    }
    for (const point of section.outer) {
      const reflected = { x: point.x, z: 2 * center.z - point.z }
      expect(Math.min(...section.outer.map(candidate =>
        Math.hypot(candidate.x - reflected.x, candidate.z - reflected.z)))).toBeLessThan(1e-8)
    }
    expect(section.outer).toHaveLength(30)
  })

  it('retains a non-degenerate shell when the bundle frame reflects a symmetric lattice', () => {
    const cells = [
      [-1,0],[-1,1],[-1,2],[-1,6],[-1,7],[-1,8],
      ...Array.from({ length: 9 }, (_, col) => [0,col]), ...Array.from({ length: 9 }, (_, col) => [1,col]),
      ...[-3,-2,-1,0,1,2,6,7,8,9,10,11].map(col => [2,col]),
      ...[-3,-2,-1,0,1,2,6,7,8,9,10,11].map(col => [3,col]),
      ...Array.from({ length: 9 }, (_, col) => [4,col]), ...Array.from({ length: 9 }, (_, col) => [5,col]),
      [6,0],[6,1],[6,2],[6,6],[6,7],[6,8],
    ].map(([row, col]) => ({ row, col }))
    const reflectedPoints = cells.map(cell => {
      const point = honeycombPoint(cell)
      return { x: 12 - point.x, z: point.z - 7 }
    })
    const section = latticeCrossSections(cells, reflectedPoints, 'HONEYCOMB')[0]
    const allPoints = [section.outer, ...section.holes].flat()
    const xs = allPoints.map(point => point.x), zs = allPoints.map(point => point.z)
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(20)
    expect(Math.max(...zs) - Math.min(...zs)).toBeGreaterThan(20)
    expect(section.holes).toHaveLength(1)
  })

  it('fills only locally supported routing interruptions', () => {
    const helices = rectangle(3, 3).map((cell, index) => ({
      ...cell, id: `h${index}`, lo: 0, hi: 20, spans: [[0, 20]],
    }))
    helices.find(h => h.row === 1 && h.col === 1).spans = [[0, 8], [12, 20]]
    const filled = supportedLatticeOccupancy(helices, 10, 'SQUARE')
    expect(filled).toHaveLength(9)
    for (const helix of helices) helix.spans = [[0, 8], [12, 20]]
    expect(supportedLatticeOccupancy(helices, 10, 'SQUARE')).toHaveLength(0)
  })

  it('tags generated geometry as the general lattice-union candidate', () => {
    const helices = rectangle(2, 2).map((cell, i) => ({ id: `h${i}`, grid_pos: [cell.row, cell.col], loop_skips: [] }))
    const axes = {}, geometry = []
    helices.forEach((helix, i) => {
      axes[helix.id] = { start: [i % 2 * 2.25, Math.floor(i / 2) * 2.25, 0], end: [i % 2 * 2.25, Math.floor(i / 2) * 2.25, 1] }
      for (const bp of [0, 1]) for (const strand of ['s', 't']) geometry.push({
        helix_id: helix.id, bp_index: bp, strand_id: `${strand}${i}`, backbone_position: [...axes[helix.id].start],
      })
    })
    const hull = buildOccupancyHull({ lattice_type: 'SQUARE', helices, strands: [], metadata: {} }, geometry, axes)
    expect(hull.userData.hullAuditVersion).toBe('candidate-general-lattice-union')
    hull.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
  })
})
