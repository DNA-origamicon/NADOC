import { describe, expect, it } from 'vitest'
import { frameCoordinates, frameLabel } from './peg_playback.js'

describe('recorded PEG frames', () => {
  it('selects exact saved coordinates and rejects truncated data', () => {
    const data = new Float32Array([1, 2, 3, 4, 5, 6])
    expect([...frameCoordinates(data, { frames: 2, particles: 1 }, 1)]).toEqual([4, 5, 6])
    expect(() => frameCoordinates(data, { frames: 3, particles: 1 }, 0)).toThrow()
    expect(() => frameCoordinates(data, { frames: 2, particles: 1 }, 2)).toThrow()
  })
  it('uses MD time only for MD, and labels MC sweeps', () => {
    expect(frameLabel({ sampling: 'md', dtFs: 2, steps: [1000000] }, 0)).toContain('2.000 ns')
    expect(frameLabel({ sampling: 'pivot', dtFs: 2, steps: [1000000] }, 0)).toContain('MC sweeps')
    expect(frameLabel({ sampling: 'pivot', steps: [100] }, 0)).not.toContain('ns')
  })
})
