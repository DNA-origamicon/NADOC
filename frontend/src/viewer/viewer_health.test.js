import { it, expect } from 'vitest'
import { createViewerHealthSignals } from './viewer_health.js'
it('requires sustained slow transfers, recovers, and publishes only two flags', () => {
  const health = createViewerHealthSignals()
  health.transfer({ milliseconds: 3000, bytes: 100000 }); expect(health.snapshot().networkSlow).toBe(false)
  health.transfer({ milliseconds: 3000, bytes: 100000 }); expect(health.snapshot().networkSlow).toBe(true)
  for (let i = 0; i < 3; i++) health.transfer({ milliseconds: 100 })
  expect(health.snapshot()).toEqual({ networkSlow: false, renderSlow: false })
  health.transfer({ milliseconds: 3000, bytes: 10_000_000 }); expect(health.snapshot().networkSlow).toBe(false)
})
it('ignores hidden/loading/benchmark frames and flags sustained low foreground frame rate', () => {
  const health = createViewerHealthSignals()
  for (let time = 0; time <= 11000; time += 100) health.frame(time)
  expect(health.snapshot().renderSlow).toBe(true)
  health.frame(20000, false); expect(health.snapshot().renderSlow).toBe(false)
  for (let time = 21000; time < 40000; time += 16) health.frame(time)
  expect(health.snapshot().renderSlow).toBe(false)
})

it('measures existing payload reads, reports only flags, and disposes its sampling', async () => {
  const { vi } = await import('vitest'), { mountViewerHealth } = await import('./viewer_health.js')
  let time = 0, frame, report
  const changes = [], cancel = vi.fn(), remove = vi.fn()
  const request = vi.fn(async (url, options) => {
    if (options?.method === 'POST') return { ok: true }
    return { ok: true, arrayBuffer: async () => { time += 2000; return new ArrayBuffer(100) } }
  })
  const health = mountViewerHealth({ viewer: { current: {}, runtime: { addFrameCallback: fn => { frame = fn }, removeFrameCallback: remove } }, base: '/meeting/a', onChange: value => changes.push(value), document: { hidden: false, querySelector: () => null }, fetch: request, now: () => time, setInterval: fn => { report = fn; return 7 }, clearInterval: cancel })
  health.start(); await Promise.resolve()
  await (await health.fetch('/meeting/a/scene')).arrayBuffer()
  await (await health.fetch('/meeting/a/frame')).arrayBuffer()
  frame(); expect(changes.at(-1).networkSlow).toBe(true)
  await report()
  expect(JSON.parse(request.mock.calls.at(-1)[1].body)).toEqual({ networkSlow: true, renderSlow: false })
  health.dispose(); expect(cancel).toHaveBeenCalledWith(7); expect(remove).toHaveBeenCalledWith(frame)
  expect(request.mock.calls.at(-1)[1].signal.aborted).toBe(true)
})
