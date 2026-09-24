import { describe, it, expect } from 'vitest'
import { buildOccupancy, clearanceAt, coverage, emptyCentres } from './annotation_occupancy.js'

const vp = { width: 600, height: 400 }
// A vertical wall of "beads" down the middle of the view.
const wall = Array.from({ length: 40 }, (_, i) => ({ x: 300, y: 10 + i * 10 }))

describe('occupancy grid', () => {
  it('reports coverage of a rect over the design vs over empty space', () => {
    const occ = buildOccupancy(wall, [], vp)
    expect(coverage(occ, { x: 270, y: 100, w: 60, h: 60 })).toBeGreaterThan(0.2)
    expect(coverage(occ, { x: 20, y: 100, w: 60, h: 60 })).toBe(0)
    expect(coverage(occ, { x: -500, y: -500, w: 10, h: 10 })).toBe(0)
  })
  it('joins neighbouring beads (dilation) so a box cannot slip between them', () => {
    const occ = buildOccupancy([{ x: 300, y: 100 }, { x: 300, y: 124 }], [], vp)
    expect(coverage(occ, { x: 290, y: 100, w: 20, h: 30 })).toBeGreaterThan(0.5)
  })
  it('marks discs (proteins / nanoparticles)', () => {
    const occ = buildOccupancy([], [{ x: 200, y: 200, r: 40 }], vp)
    expect(coverage(occ, { x: 180, y: 180, w: 40, h: 40 })).toBeGreaterThan(0.9)
    expect(coverage(occ, { x: 400, y: 20, w: 40, h: 40 })).toBe(0)
  })
  it('clearance grows with distance from the design', () => {
    const occ = buildOccupancy(wall, [], vp)
    expect(clearanceAt(occ, 300, 100)).toBe(0)
    expect(clearanceAt(occ, 400, 100)).toBeGreaterThan(clearanceAt(occ, 330, 100))
  })
  it('finds the roomiest pocket first and different pockets after', () => {
    const occ = buildOccupancy(wall, [], vp)
    const [a, b] = emptyCentres(occ, 2)
    expect(a.clearance).toBeGreaterThanOrEqual(b.clearance)
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(60)
    // Pockets are the two open halves, not the wall.
    expect(Math.abs(a.x - 300)).toBeGreaterThan(80)
  })
  it('an empty view centres on the viewport', () => {
    const occ = buildOccupancy([], [], vp)
    expect(emptyCentres(occ, 3)).toEqual([{ x: 300, y: 200, clearance: 600 }])
    expect(coverage(occ, { x: 0, y: 0, w: 50, h: 50 })).toBe(0)
  })
})

it('bounds rasterization to the viewport for enormous near-camera obstacles', () => {
  const occ = buildOccupancy([], [{ x: 300, y: 200, r: 1e12 }], vp)
  expect(coverage(occ, { x: 0, y: 0, w: 600, h: 400 })).toBe(1)
})
