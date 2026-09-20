import { expect, it, vi } from 'vitest'
import { snapshotViewer } from './viewer_snapshot.js'

it('reads pixels after the normal render and removes its one-shot callback', async () => {
  const callbacks = new Set()
  let rendered = false
  const canvas = { width: 20, height: 10, toDataURL: () => { expect(rendered).toBe(true); return 'data:image/png;base64,AAAA' } }
  const pending = snapshotViewer({ canvas, addFrameCallback: fn => callbacks.add(fn), removeFrameCallback: fn => callbacks.delete(fn), inspect: () => ({ busy: false }) })
  for (const fn of callbacks) fn()
  rendered = true
  expect(await pending).toMatchObject({ width: 20, height: 10, status: { busy: false } })
  expect(callbacks.size).toBe(0)
})
it('times out and removes callbacks when rendering stalls', async () => {
  vi.useFakeTimers()
  try {
    const callbacks = new Set()
    const pending = snapshotViewer({ canvas: {}, addFrameCallback: fn => callbacks.add(fn), removeFrameCallback: fn => callbacks.delete(fn), inspect: () => ({}), timeoutMs: 100 })
    const rejection = expect(pending).rejects.toThrow('No rendered frame')
    await vi.advanceTimersByTimeAsync(100)
    await rejection
    expect(callbacks.size).toBe(0)
  } finally { vi.useRealTimers() }
})
