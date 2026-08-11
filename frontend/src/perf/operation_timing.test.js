import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  beginOperationTiming,
  finishOperationAfterRender,
  markOperationTiming,
} from './operation_timing.js'

describe('operation timing', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.__nadocOperationTiming.clear()
  })

  it('finishes only after two animation frames and records phase deltas', () => {
    const frames = []
    vi.stubGlobal('requestAnimationFrame', cb => { frames.push(cb); return frames.length })
    const trace = beginOperationTiming('extrude')
    markOperationTiming('response-received', { status: 200 }, trace)
    finishOperationAfterRender(trace)

    expect(window.__nadocOperationTiming.recent()).toHaveLength(0)
    frames.shift()(1)
    expect(window.__nadocOperationTiming.recent()).toHaveLength(0)
    frames.shift()(2)

    const [finished] = window.__nadocOperationTiming.recent()
    expect(finished.label).toBe('extrude')
    expect(finished.finished).toBe(true)
    expect(finished.marks.map(m => m.name)).toEqual([
      'operation-start', 'response-received', 'final-render',
    ])
    expect(finished.totalMs).toBeGreaterThanOrEqual(0)
  })
})
