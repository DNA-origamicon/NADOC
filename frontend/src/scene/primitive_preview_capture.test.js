/**
 * Pure-function tests for buildCameraPath — the camera-path planner behind the
 * primitive hover previews. (capturePosesGif is the stateful renderer shell,
 * exercised by the build-primitives pipeline, not unit-tested here.)
 */
import { describe, it, expect } from 'vitest'
import { buildCameraPath } from './primitive_preview_capture.js'

const P0 = { position: [0, 0, 10], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
const P1 = { position: [10, 0, 0], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }
const P2 = { position: [0, 10, 0], target: [0, 0, 0], up: [0, 1, 0], fov: 55 }

describe('buildCameraPath', () => {
  it('returns [] for no poses (caller falls back to a static thumbnail)', () => {
    expect(buildCameraPath([])).toEqual([])
    expect(buildCameraPath(undefined)).toEqual([])
  })

  it('returns a single static state for one pose', () => {
    const path = buildCameraPath([P0])
    expect(path).toHaveLength(1)
    expect(path[0].position).toEqual([0, 0, 10])
  })

  it('ping-pongs two poses there-and-back across two segments', () => {
    const path = buildCameraPath([P0, P1], { stepsPerSegment: 6 })
    // 2 segments (p0→p1, p1→p0) × 6 steps
    expect(path).toHaveLength(12)
    // First frame is exactly p0 (segment start, t=0).
    expect(path[0].position).toEqual([0, 0, 10])
    // Frame 6 is the start of the return segment = p1.
    expect(path[6].position[0]).toBeCloseTo(10, 5)
    expect(path[6].position[2]).toBeCloseTo(0, 5)
    // It never re-emits the closing p0 (that's the loop wrap to frame 0).
    expect(path[path.length - 1].position).not.toEqual([0, 0, 10])
  })

  it('loops a one-way cycle when pingPong is false', () => {
    const path = buildCameraPath([P0, P1, P2], { stepsPerSegment: 5, pingPong: false })
    // keys = p0,p1,p2,p0 → 3 segments × 5
    expect(path).toHaveLength(15)
    expect(path[0].position).toEqual([0, 0, 10])
  })

  it('ping-pong over 3 poses uses 4 segments (p0→p1→p2→p1→p0)', () => {
    const path = buildCameraPath([P0, P1, P2], { stepsPerSegment: 3 })
    expect(path).toHaveLength(12) // 4 segments × 3
  })

  it('interpolates position monotonically within a segment', () => {
    const path = buildCameraPath([P0, P1], { stepsPerSegment: 10 })
    const xs = path.slice(0, 10).map((s) => s.position[0])
    for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThanOrEqual(xs[i - 1])
  })

  it('defaults a missing up vector to +Y', () => {
    const path = buildCameraPath([{ position: [0, 0, 5], target: [0, 0, 0] }])
    expect(path[0].up).toEqual([0, 1, 0])
  })
})
