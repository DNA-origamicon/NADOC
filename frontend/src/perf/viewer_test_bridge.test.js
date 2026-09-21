import { expect, it, vi, afterEach } from 'vitest'
import { connectViewerTestBridge } from './viewer_test_bridge.js'
afterEach(() => vi.unstubAllGlobals())

it('leaves optional automation inert when LAN HTTP lacks secure-context UUIDs', () => {
  vi.stubGlobal('crypto', { getRandomValues: vi.fn() })
  const hot = { send: vi.fn(), on: vi.fn(), off: vi.fn() }, inspect = vi.fn()
  const dispose = connectViewerTestBridge({ hot, api: {}, inspect })
  expect(hot.on).not.toHaveBeenCalled()
  expect(hot.send).not.toHaveBeenCalled()
  expect(inspect).not.toHaveBeenCalled()
  expect(() => dispose()).not.toThrow()
})

function fixture() {
  const handlers = new Map(), callbacks = new Set()
  const hot = { send: vi.fn(), on: (key, fn) => handlers.set(key, fn), off: key => handlers.delete(key) }
  const api = { busy: false, latest: null, start: vi.fn(async () => { api.busy = true }),
    subscribe: fn => { callbacks.add(fn); return () => callbacks.delete(fn) } }
  const snapshot = vi.fn(async () => ({ png: 'pixels' }))
  const doc = { hidden: false, querySelector: () => null }
  const dispose = connectViewerTestBridge({ hot, api, snapshot, inspect: () => ({ visible: !doc.hidden }), document: doc })
  return { hot, api, snapshot, doc, dispose, handlers, callbacks, command: value => handlers.get('nadoc:viewer-command')(value) }
}
it('uses manual capture API and returns completed metrics and restoration evidence', async () => {
  const f = fixture()
  const pending = f.command({ id: 'run', action: 'capture', options: { durationMs: 1000 } })
  await Promise.resolve()
  expect(f.api.start).toHaveBeenCalledWith({ durationMs: 1000 })
  expect(f.hot.send).not.toHaveBeenCalledWith('nadoc:viewer-result', expect.anything())
  f.api.busy = false; f.api.latest = { valid: true }
  for (const callback of f.callbacks) callback()
  await pending
  expect(f.hot.send).toHaveBeenCalledWith('nadoc:viewer-result', { id: 'run', result: { metrics: { valid: true }, after: { visible: true } } })
  expect(f.snapshot).not.toHaveBeenCalled()
  f.dispose(); expect(f.handlers.size).toBe(0); expect(f.callbacks.size).toBe(0)
})
it('rejects hidden tabs, manual capture conflicts and unsupported commands', async () => {
  const f = fixture()
  f.doc.hidden = true
  await f.command({ id: 'hidden', action: 'capture' })
  expect(f.api.start).not.toHaveBeenCalled()
  expect(f.hot.send).toHaveBeenLastCalledWith('nadoc:viewer-result', expect.objectContaining({ error: expect.stringContaining('visible') }))
  f.doc.hidden = false; f.api.busy = true
  await f.command({ id: 'busy', action: 'snapshot' })
  expect(f.snapshot).not.toHaveBeenCalled()
  f.api.busy = false
  await f.command({ id: 'unsafe', action: 'eval' })
  expect(f.hot.send).toHaveBeenLastCalledWith('nadoc:viewer-result', { id: 'unsafe', error: 'Unsupported viewer command' })
  f.dispose()
})
it('registers on reconnect and snapshots only on explicit request', async () => {
  const f = fixture()
  f.handlers.get('vite:ws:connect')()
  expect(f.hot.send).toHaveBeenCalledTimes(2)
  await f.command({ id: 'image', action: 'snapshot' })
  expect(f.snapshot).toHaveBeenCalledTimes(1)
  f.dispose()
})
