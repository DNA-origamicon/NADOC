import { describe, it, expect } from 'vitest'
import { loadedPreviewFrames, previewIndices, previewPair } from './trajectory_preview.js'

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

it('copies compact resident preview frames and leaves missing or other layouts for download',()=>{
 const source=new Float32Array([1,2,3,4,5,6])
 const cached=loadedPreviewFrames([source,undefined,new Float32Array(12)],[0,1,2],1)
 expect([...cached.keys()]).toEqual([0])
 expect(cached.get(0)).toEqual(source)
 source[0]=100
 expect(cached.get(0)[0]).toBe(1)
})

it('packs current oxDNA frames identically to the six-value preview layout',()=>{
 const source=new Float32Array([1,2,3,4,5,6,70,80,90, 11,12,13,14,15,16,170,180,190])
 const result=loadedPreviewFrames([source],[0],2).get(0)
 expect(Array.from(result)).toEqual([1,2,3,4,5,6,11,12,13,14,15,16])
 expect(source[6]).toBe(70)
})
