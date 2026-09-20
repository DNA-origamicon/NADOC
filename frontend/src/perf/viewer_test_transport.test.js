import { expect, it, vi } from 'vitest'
import { createViewerTestTransport, viewerTestDestination } from './viewer_test_transport.js'

it('is inert without explicit benchmark opt-in', () => {
  const EventSource = vi.fn()
  expect(createViewerTestTransport({ id: 'a', location: { search: '' }, EventSource })).toBeNull()
  expect(EventSource).not.toHaveBeenCalled()
})
it('waits for the event connection, dispatches commands, and cleans up', async () => {
  let source
  class EventSource { constructor() { source = this; this.close = vi.fn() } }
  const fetch = vi.fn(async () => ({ ok: true }))
  const hot = createViewerTestTransport({ id: 'session', location: { search: '?viewer-test=1' }, EventSource, fetch })
  const callback = vi.fn()
  hot.on('nadoc:viewer-command', callback)
  const pending = hot.send('nadoc:viewer-register', { id: 'session' })
  expect(fetch).not.toHaveBeenCalled()
  source.onopen(); await pending
  source.onmessage({ data: JSON.stringify({ event: 'nadoc:viewer-command', data: { action: 'capture' } }) })
  expect(callback).toHaveBeenCalledWith({ action: 'capture' })
  expect(JSON.parse(fetch.mock.calls[0][1].body).session).toBe('session')
  hot.close(); expect(source.close).toHaveBeenCalledOnce()
})
it('only permits the fixed local benchmark destinations', () => {
  expect(viewerTestDestination('http://127.0.0.1:5180/?viewer-test=1&doc=a')).toContain(':5180/')
  for (const url of ['https://evil.example/', 'http://localhost:8000/', 'http://localhost:5180/api/design', 'http://x@y:5180/', 'http://localhost:5180/?redirect=evil']) expect(() => viewerTestDestination(url)).toThrow()
})
