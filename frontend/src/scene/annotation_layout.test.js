import { describe, it, expect } from 'vitest'
import { buildOccupancy, coverage } from './annotation_occupancy.js'
import { MARGIN, attachPoint, clampRect, elbowPoints, layoutCallouts, leaderPoints, preferredRect } from './annotation_layout.js'

const vp = { width: 800, height: 600 }
const size = { w: 120, h: 40 }
const inside = r => r.x >= MARGIN && r.y >= MARGIN && r.x + r.w <= vp.width - MARGIN && r.y + r.h <= vp.height - MARGIN
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h

describe('preferredRect', () => {
  it('sits up-and-right of the anchor', () => {
    const r = preferredRect({ x: 300, y: 300 }, size, vp)
    expect(r.x).toBeGreaterThan(300)
    expect(r.y + r.h).toBeLessThan(300)
  })
  it('flips left near the right edge and below near the top, always inside the viewport', () => {
    const r = preferredRect({ x: 790, y: 5 }, size, vp)
    expect(r.x + r.w).toBeLessThan(790)
    expect(r.y).toBeGreaterThan(5)
    expect(inside(r)).toBe(true)
  })
})

describe('layoutCallouts', () => {
  it('keeps manual boxes exactly where placed and auto boxes clear of them', () => {
    const items = [
      { id: 'a', size, anchor: { x: 300, y: 300 }, manualRect: null },
      { id: 'm', size, anchor: { x: 300, y: 300 }, manualRect: { x: 336, y: 212 } },
    ]
    const out = layoutCallouts(items, vp)
    expect(out.get('m')).toMatchObject({ x: 336, y: 212 })
    expect(overlap(out.get('a'), out.get('m'))).toBe(false)
  })
  it('separates auto boxes that would collide', () => {
    const items = ['a', 'b', 'c'].map(id => ({ id, size, anchor: { x: 400, y: 300 }, manualRect: null }))
    const out = [...layoutCallouts(items, vp).values()]
    for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) expect(overlap(out[i], out[j])).toBe(false)
    expect(out.every(inside)).toBe(true)
  })
  it('stacks anchorless callouts in the top-left instead of dropping them', () => {
    const out = layoutCallouts([{ id: 'a', size, anchor: null, manualRect: null }, { id: 'b', size, anchor: null, manualRect: null }], vp)
    expect(out.get('a').x).toBeLessThan(40)
    expect(overlap(out.get('a'), out.get('b'))).toBe(false)
  })
  it('clamps a manual box dragged off-screen', () => {
    const out = layoutCallouts([{ id: 'm', size, anchor: null, manualRect: { x: 5000, y: -50 } }], vp)
    expect(inside(out.get('m'))).toBe(true)
  })
})

describe('leaders', () => {
  const rect = { x: 100, y: 100, w: 100, h: 40 }
  it('attach on the box side facing the anchor', () => {
    expect(attachPoint(rect, { x: 400, y: 120 }, 'elbow')).toEqual({ x: 200, y: 120 })
    expect(attachPoint(rect, { x: 0, y: 120 }, 'elbow')).toEqual({ x: 100, y: 120 })
    expect(attachPoint(rect, { x: 150, y: 400 }, 'line')).toEqual({ x: 150, y: 140 })
    expect(attachPoint(rect, { x: 400, y: 400 }, 'shelf')).toEqual({ x: 200, y: 140 })
  })
  it('elbow runs horizontally then 45° and ends on the anchor', () => {
    const [s, e, a] = elbowPoints({ x: 0, y: 0 }, { x: 100, y: 40 })
    expect(s).toEqual({ x: 0, y: 0 })
    expect(e).toEqual({ x: 60, y: 0 })
    expect(a).toEqual({ x: 100, y: 40 })
    expect(Math.abs(a.x - e.x)).toBe(Math.abs(a.y - e.y))
  })
  it('elbow goes vertical last when the anchor is mostly below', () => {
    const pts = elbowPoints({ x: 0, y: 0 }, { x: 10, y: 100 })
    expect(pts.at(-1)).toEqual({ x: 10, y: 100 })
    expect(pts[1]).toEqual({ x: 10, y: 10 })
  })
  it('straight types produce a two-point line', () => {
    expect(leaderPoints('line', rect, { x: 400, y: 120 })).toHaveLength(2)
    expect(leaderPoints('elbow', rect, { x: 400, y: 300 })).toHaveLength(3)
  })
})

describe('clampRect', () => {
  it('never returns a rect outside the margin', () => {
    expect(inside(clampRect({ x: -10, y: 999, w: 50, h: 50 }, vp))).toBe(true)
  })
})

describe('occupancy-aware auto placement', () => {
  const size = { w: 120, h: 40 }
  const wall = Array.from({ length: 50 }, (_, i) => ({ x: 400, y: 10 + i * 12 }))
  const cover = (occ, r) => coverage(occ, r)

  it('lands on empty space instead of on top of the design', () => {
    // Anchor on the wall: the default up-right spot would sit over dense design.
    const occ = buildOccupancy([...wall, ...Array.from({ length: 30 }, (_, i) => ({ x: 400 + i * 8, y: 250 }))], [], vp)
    const anchor = { x: 400, y: 250 }
    const rect = layoutCallouts([{ id: 'a', size, anchor, manualRect: null }], vp, { occupancy: occ }).get('a')
    expect(cover(occ, rect)).toBe(0)
    expect(inside(rect)).toBe(true)
    // Close to its target rather than on the far side of the view.
    expect(Math.hypot(rect.x + rect.w / 2 - anchor.x, rect.y + rect.h / 2 - anchor.y)).toBeLessThan(300)
  })

  it('an anchorless callout goes to the middle of the emptiest region', () => {
    // Design fills the left 60 % of the view; the roomy pocket is on the right.
    const pts = []
    for (let x = 0; x < 480; x += 8) for (let y = 0; y < vp.height; y += 8) pts.push({ x, y })
    const occ = buildOccupancy(pts, [], vp)
    const rect = layoutCallouts([{ id: 'n', size, anchor: null, manualRect: null }], vp, { occupancy: occ }).get('n')
    expect(rect.x + rect.w / 2).toBeGreaterThan(560 - 40)
    expect(cover(occ, rect)).toBe(0)
  })

  it('an empty view centres an anchorless callout', () => {
    const occ = buildOccupancy([], [], vp)
    const rect = layoutCallouts([{ id: 'n', size, anchor: null, manualRect: null }], vp, { occupancy: occ }).get('n')
    expect(rect.x + rect.w / 2).toBeCloseTo(400, -1)
    expect(rect.y + rect.h / 2).toBeCloseTo(300, -1)
  })

  it('chooses a different side of the box for the leader when the box lands elsewhere', () => {
    const anchor = { x: 200, y: 300 }
    const sideOf = rect => attachPoint(rect, anchor, 'elbow').x >= rect.x + rect.w / 2 ? 'right' : 'left'
    expect(sideOf({ x: 300, y: 200, w: 100, h: 40 })).toBe('left')   // box right of the anchor → leaves its left side
    expect(sideOf({ x: 20, y: 200, w: 100, h: 40 })).toBe('right')   // box left of the anchor → leaves its right side
    // Directly above: leaves the bottom centre.
    expect(attachPoint({ x: 150, y: 200, w: 100, h: 40 }, anchor, 'elbow')).toEqual({ x: 200, y: 240 })
  })

  it('keeps several auto callouts apart and off the design', () => {
    const occ = buildOccupancy(wall, [], vp)
    const items = ['a', 'b', 'c'].map(id => ({ id, size, anchor: { x: 400, y: 300 }, manualRect: null }))
    const out = [...layoutCallouts(items, vp, { occupancy: occ }).values()]
    for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) expect(overlap(out[i], out[j])).toBe(false)
    expect(out.every(r => cover(occ, r) === 0)).toBe(true)
  })

  it('does not jitter: a still-good previous position is kept', () => {
    const occ = buildOccupancy(wall, [], vp)
    const first = layoutCallouts([{ id: 'a', size, anchor: { x: 400, y: 300 }, manualRect: null }], vp, { occupancy: occ }).get('a')
    const nudged = layoutCallouts([{ id: 'a', size, anchor: { x: 410, y: 306 }, manualRect: null }], vp, { occupancy: occ, previous: new Map([['a', first]]) }).get('a')
    expect(nudged).toEqual(first)
  })

  it('abandons the previous position once it lands on the design', () => {
    const occ = buildOccupancy(wall, [], vp)
    const bad = { x: 380, y: 100, w: 120, h: 40 }
    const rect = layoutCallouts([{ id: 'a', size, anchor: { x: 200, y: 300 }, manualRect: null }], vp, { occupancy: occ, previous: new Map([['a', bad]]) }).get('a')
    expect(cover(occ, rect)).toBe(0)
  })
})
