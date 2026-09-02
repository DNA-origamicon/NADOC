import { describe, expect, it } from 'vitest'
import { createLatestFrameScheduler, normalizeBounds, pointInVolume, resolveViewVolumeLayers, segmentsForKeys } from './view_volumes.js'

describe('view volume spatial resolution', () => {
  const a = { id: 'a', min_corner: [0, 0, 0], max_corner: [5, 5, 5], representation: 'surface', opacity: .4 }
  const b = { id: 'b', min_corner: [3, 3, 3], max_corner: [8, 8, 8], representation: 'stick', opacity: 1 }
  it('keeps intersecting representations as independent layers', () => {
    const layers = resolveViewVolumeLayers([a, b], [{ key: 'h:4', position: [4, 4, 4] }])
    expect(layers.map(layer => [...layer.keys])).toEqual([['h:4'], ['h:4']])
    expect(layers.map(layer => layer.volume.representation)).toEqual(['surface', 'stick'])
  })
  it('uses inclusive normalized bounds and compresses columns', () => {
    expect(normalizeBounds([5, 2, 9], [1, 4, 3])).toEqual({ min_corner: [1, 2, 3], max_corner: [5, 4, 9] })
    expect(pointInVolume([5, 4, 9], { min_corner: [1, 2, 3], max_corner: [5, 4, 9] })).toBe(true)
    expect(segmentsForKeys(new Set(['h:1', 'h:2', 'h:4']))).toEqual([
      { helix_id: 'h', bp_start: 1, bp_end: 2 }, { helix_id: 'h', bp_start: 4, bp_end: 4 },
    ])
  })
  it('tests membership in the rotated local box frame', () => {
    const quarterTurnZ = [0, 0, Math.sin(Math.PI / 4), Math.cos(Math.PI / 4)]
    const volume = { min_corner: [-2, -.5, -.5], max_corner: [2, .5, .5], rotation: quarterTurnZ }
    expect(pointInVolume([0, 1.8, 0], volume)).toBe(true)
    expect(pointInVolume([1.8, 0, 0], volume)).toBe(false)
  })
  it('tests membership in a regular hexagonal prism', () => {
    const volume = { shape: 'hexagonal', min_corner: [-3, -2, -2], max_corner: [3, 2, 2] }
    expect(pointInVolume([0, 1.7, 1.9], volume)).toBe(true)
    expect(pointInVolume([1.9, 1, 0], volume)).toBe(false)
    expect(pointInVolume([0, 0, 3.1], volume)).toBe(false)
  })
  it('coalesces rapid preview work and aborts the superseded revision', async () => {
    const frames = new Map(), seen = []
    let id = 0
    const scheduler = createLatestFrameScheduler((value, context) => seen.push([value, context.revision]), {
      requestFrame: callback => { frames.set(++id, callback); return id },
      cancelFrame: frame => frames.delete(frame),
    })
    scheduler.schedule('old')
    scheduler.schedule('latest')
    expect(frames.size).toBe(1)
    await [...frames.values()][0]()
    expect(seen).toEqual([['latest', 2]])
  })
})
