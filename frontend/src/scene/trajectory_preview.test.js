import { describe, it, expect } from 'vitest'
import { previewIndices, previewPair } from './trajectory_preview.js'

describe('bounded stage-aware trajectory previews', () => {
  it('covers both endpoints of every stage within a fixed budget', () => {
    const markers = [{ frame: 0 }, { frame: 37 }, { frame: 900 }]
    const grid = previewIndices(1000, markers, 16)
    expect(grid).toHaveLength(16)
    for (const i of [0, 36, 37, 899, 900, 999]) expect(grid).toContain(i)
    for (let i = 0; i < 1000; i += .25) {
      const [a, b, t] = previewPair(grid, i, markers)
      expect(markers.some(m => m.frame > a && m.frame <= b)).toBe(false)
      expect(t).toBeGreaterThanOrEqual(0); expect(t).toBeLessThanOrEqual(1)
    }
  })
  it('declines rather than exceeding memory when mandatory stage endpoints do not fit', () => {
    expect(previewIndices(100, [{ frame: 50 }], 3)).toEqual([])
    expect(previewIndices(1, [], 16)).toEqual([0])
    expect(previewIndices(1000000, [], 16)).toHaveLength(16)
  })
})

it('batches sparse samples without requesting intermediate frames', async () => {
  const { previewRuns } = await import('./trajectory_preview.js')
  const ids = previewIndices(501)
  const runs = previewRuns(ids)
  expect(runs.length).toBeLessThan(ids.length)
  expect(runs.flatMap(r => Array.from({ length: (r.end - r.start) / r.step + 1 }, (_, j) => r.start + j * r.step))).toEqual(ids)
})
