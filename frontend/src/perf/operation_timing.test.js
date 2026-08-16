import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  beginOperationTiming,
  finishOperationAfterRender,
  markOperationTiming,
  whenOperationIdle,
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

  it('releases background work only after the final rendered frame', async () => {
    const frames = []
    vi.stubGlobal('requestAnimationFrame', cb => { frames.push(cb); return frames.length })
    const trace = beginOperationTiming('optimistic extrude')
    let released = false
    const idle = whenOperationIdle().then(() => { released = true })
    finishOperationAfterRender(trace)

    frames.shift()(1)
    await Promise.resolve()
    expect(released).toBe(false)
    frames.shift()(2)
    await idle
    expect(released).toBe(true)
  })

  it('broadcasts a JSON-safe completed phase trace for Playwright diagnostics', () => {
    const frames = []
    vi.stubGlobal('requestAnimationFrame', cb => { frames.push(cb); return frames.length })
    const seen = []
    const onTiming = e => seen.push(e.detail)
    window.addEventListener('nadoc:operation-timing', onTiming)
    try {
      const trace = beginOperationTiming('POST /design/import')
      markOperationTiming('store-applied', { nucleotides: 14179 }, trace)
      finishOperationAfterRender(trace)
      frames.shift()(1)
      frames.shift()(2)
      expect(seen).toHaveLength(1)
      expect(seen[0]).toMatchObject({
        label: 'POST /design/import',
        marks: expect.arrayContaining([
          expect.objectContaining({ name: 'store-applied' }),
          expect.objectContaining({ name: 'final-render' }),
        ]),
      })
    } finally {
      window.removeEventListener('nadoc:operation-timing', onTiming)
    }
  })
})
