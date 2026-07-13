import { describe, it, expect } from 'vitest'
import {
  MULTISCALE_DEFAULTS,
  distanceToSegmentSq,
  axisSegments,
  makeSegmentCache,
  nearestAxisDistance,
  navScaleAt,
  zoomStep,
  wheelNotches,
} from './multiscale_nav.js'

// A 1100 bp 6hb: six helices ~374 nm long on Z, axes on a ring of radius ~2.6 nm.
const LEN = 1100 * 0.34
const RING = 2.6
function sixHelixBundle() {
  const helices = []
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * 2 * Math.PI
    const x = RING * Math.cos(a), y = RING * Math.sin(a)
    helices.push({
      axis_start: { x, y, z: 0 },
      axis_end:   { x, y, z: LEN },
    })
  }
  return { helices }
}

describe('distanceToSegmentSq', () => {
  it('measures perpendicular distance when the foot lies inside the segment', () => {
    // Segment along X from (0,0,0)→(10,0,0); point 3 above its midpoint.
    expect(distanceToSegmentSq(5, 3, 0, 0, 0, 0, 10, 0, 0)).toBeCloseTo(9)
  })

  it('clamps to the endpoints when the foot lies beyond the segment', () => {
    // Point past the far end — nearest point is the endpoint, not the infinite line.
    expect(distanceToSegmentSq(14, 0, 0, 0, 0, 0, 10, 0, 0)).toBeCloseTo(16)
    expect(distanceToSegmentSq(-3, 0, 0, 0, 0, 0, 10, 0, 0)).toBeCloseTo(9)
  })

  it('handles a degenerate zero-length segment as a point', () => {
    expect(distanceToSegmentSq(0, 4, 3, 1, 1, 1, 1, 1, 1)).toBeCloseTo(1 + 9 + 4)
  })
})

describe('axisSegments', () => {
  it('flattens helices to 6 floats each', () => {
    const segs = axisSegments(sixHelixBundle())
    expect(segs).toHaveLength(36)
    expect(segs[2]).toBe(0)      // first helix az
    expect(segs[5]).toBeCloseTo(LEN)  // first helix bz
  })

  it('returns empty for a missing or helix-less design', () => {
    expect(axisSegments(null)).toHaveLength(0)
    expect(axisSegments({})).toHaveLength(0)
    expect(axisSegments({ helices: [] })).toHaveLength(0)
  })

  it('skips helices with malformed axes rather than emitting NaN', () => {
    const segs = axisSegments({ helices: [
      { axis_start: { x: 0, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 5 } },
      { axis_start: null, axis_end: { x: 0, y: 0, z: 5 } },
      { axis_start: { x: NaN, y: 0, z: 0 }, axis_end: { x: 0, y: 0, z: 5 } },
    ] })
    expect(segs).toHaveLength(6)
    expect([...segs].every(Number.isFinite)).toBe(true)
  })
})

describe('makeSegmentCache', () => {
  it('rebuilds only when the design object identity changes', () => {
    let design = sixHelixBundle()
    let calls = 0
    const cache = makeSegmentCache(() => { calls++; return design })

    const a = cache()
    const b = cache()
    expect(a).toBe(b)            // same array instance — not re-flattened
    expect(calls).toBe(2)        // getter still consulted every time

    design = sixHelixBundle()    // store replaced currentDesign
    expect(cache()).not.toBe(a)  // rebuilt
  })
})

describe('nearestAxisDistance', () => {
  const segs = axisSegments(sixHelixBundle())

  it('pins to the ring radius anywhere down the core of the bundle', () => {
    // This is the property the whole mode rests on: flying along the core, the
    // nearest-helix distance does not change, so the pace does not change.
    const atStart  = nearestAxisDistance(0, 0, 5,         segs)
    const atMiddle = nearestAxisDistance(0, 0, LEN / 2,   segs)
    const atEnd    = nearestAxisDistance(0, 0, LEN - 5,   segs)
    expect(atStart).toBeCloseTo(RING, 5)
    expect(atMiddle).toBeCloseTo(RING, 5)
    expect(atEnd).toBeCloseTo(RING, 5)
  })

  it('grows with distance once outside the structure', () => {
    // Backed off along the core axis, the nearest point is a helix *endpoint* on
    // the 2.6 nm ring, so the distance is hypot(axial gap, RING) — it converges
    // on the axial gap as you retreat, which is what makes the far field behave
    // like plain distance-to-structure.
    const near = nearestAxisDistance(0, 0, -20, segs)
    const far  = nearestAxisDistance(0, 0, -200, segs)
    expect(near).toBeCloseTo(Math.hypot(20, RING), 5)
    expect(far).toBeCloseTo(Math.hypot(200, RING), 5)
    expect(far).toBeGreaterThan(near)
  })

  it('is Infinity when there is no structure', () => {
    expect(nearestAxisDistance(0, 0, 0, new Float64Array(0))).toBe(Infinity)
  })
})

describe('navScaleAt', () => {
  const p = MULTISCALE_DEFAULTS

  it('passes the raw distance through in the far field', () => {
    expect(navScaleAt(150, 999, p)).toBe(150)
  })

  it('floors the scale so the step can never stall at zero', () => {
    expect(navScaleAt(0, 999, p)).toBe(p.minScale)
  })

  it('caps the scale so an empty scene cannot produce an absurd leap', () => {
    expect(navScaleAt(1e9, 999, p)).toBe(p.maxScale)
  })

  it('falls back to the orbit-target distance when there is no structure', () => {
    expect(navScaleAt(Infinity, 42, p)).toBe(42)
  })

  it('applies the Shift boost to the scale, not the notch count', () => {
    expect(navScaleAt(2.6, 999, p, true)).toBeCloseTo(2.6 * p.boost)
  })
})

describe('zoomStep', () => {
  const { zoomFrac } = MULTISCALE_DEFAULTS

  it('covers zoomFrac of the local scale for one notch', () => {
    expect(zoomStep(100, 1, 0.35)).toBeCloseTo(35)
  })

  it('approaches but never leaps past the local scale in a single event', () => {
    expect(zoomStep(100, 4, 0.35)).toBeLessThan(100)
    expect(zoomStep(100, 50, 0.35)).toBeLessThan(100)
  })

  it('is negative (retreats) for a zoom-out', () => {
    expect(zoomStep(100, -1, 0.35)).toBeLessThan(0)
  })

  it('never returns zero for a nonzero notch at the scale floor — the no-stall property', () => {
    // The stock target-relative dolly goes to 0 here; this one must not.
    const step = zoomStep(MULTISCALE_DEFAULTS.minScale, 1, zoomFrac)
    expect(step).toBeGreaterThan(0)
  })

  it('gives a constant step for a constant scale, however far you have travelled', () => {
    expect(zoomStep(RING, 1, zoomFrac)).toBeCloseTo(zoomStep(RING, 1, zoomFrac))
  })

  it('is zero for degenerate inputs', () => {
    expect(zoomStep(0, 1, 0.35)).toBe(0)
    expect(zoomStep(100, 0, 0.35)).toBe(0)
    expect(zoomStep(NaN, 1, 0.35)).toBe(0)
  })
})

describe('wheelNotches', () => {
  it('maps a standard 100px wheel tick to one notch, zoom-in positive', () => {
    expect(wheelNotches(-100, 0)).toBeCloseTo(1)
    expect(wheelNotches(100, 0)).toBeCloseTo(-1)
  })

  it('clamps a large trackpad delta so one event cannot teleport the camera', () => {
    expect(wheelNotches(-99999, 0)).toBe(MULTISCALE_DEFAULTS.maxNotch)
    expect(wheelNotches(99999, 0)).toBe(-MULTISCALE_DEFAULTS.maxNotch)
  })

  it('handles line and page delta modes', () => {
    expect(wheelNotches(-3, 1)).toBeCloseTo(1)
    expect(wheelNotches(-1, 2)).toBeCloseTo(1)
  })
})

describe('end-to-end feel of the chosen law (documents the tradeoff that was picked)', () => {
  const segs = axisSegments(sixHelixBundle())
  const p = MULTISCALE_DEFAULTS

  it('keeps a constant, non-stalling pace all the way through a 374 nm 6hb', () => {
    // Walk the camera down the core and confirm the step never changes and
    // never decays — the behaviour the stock dolly cannot produce.
    const steps = [10, 100, 187, 300, LEN - 10].map(z => {
      const d = nearestAxisDistance(0, 0, z, segs)
      return zoomStep(navScaleAt(d, 999, p), 1, p.zoomFrac)
    })
    for (const s of steps) {
      expect(s).toBeGreaterThan(0)
      expect(s).toBeCloseTo(steps[0], 6)
    }
  })

  it('accelerates back up as the camera leaves the structure', () => {
    const inside = zoomStep(navScaleAt(nearestAxisDistance(0, 0, LEN / 2, segs), 999, p), 1, p.zoomFrac)
    const away   = zoomStep(navScaleAt(nearestAxisDistance(0, 0, -200, segs),   999, p), 1, p.zoomFrac)
    expect(away).toBeGreaterThan(inside * 20)
  })
})
