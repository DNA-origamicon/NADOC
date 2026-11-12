import { expect, it, vi } from 'vitest'
import { createPresentationLibrary } from './presentation_library.js'
import { presentationHTML } from './compiled_presentation.js'
const clips = [{ name: 'Clip', video: 'data:video/webm;base64,AA==', first: 'data:image/jpeg;base64,AA==', last: 'data:image/jpeg;base64,AA==', duration: 1 }]
function setup() {
  const blob = new Blob([presentationHTML('Talk', clips)], { type: 'text/html' })
  // jsdom's Blob does not implement text(); browsers exercise the actual Blob API.
  blob.text = async () => presentationHTML('Talk', clips)
  const entry = { id: 'a'.repeat(64), name: 'Talk', size: blob.size, created_at: '2026-11-11T00:00:00Z', kind: 'presentation' }
  const cache = { list: vi.fn(async () => []), get: vi.fn(async () => null), put: vi.fn(async () => {}) }
  const request = vi.fn(async url => url.endsWith('/content') ? { ok: true, blob: async () => blob } : { ok: true, json: async () => ({ items: [entry] }) })
  return { blob, entry, cache, request, library: createPresentationLibrary({ cache, request }) }
}
it('downloads and validates the whole presentation before saving it on this device', async () => {
  const f = setup(), progress = vi.fn()
  const opened = await f.library.open(f.entry, { onProgress: progress })
  expect(opened.data.clips).toEqual(clips)
  expect(opened.deviceSaved).toBe(true)
  expect(f.cache.put).toHaveBeenCalledWith(f.entry, f.blob)
  expect(f.request).toHaveBeenCalledOnce()
})
it('opens a cached presentation without any network request and lists it offline', async () => {
  const f = setup()
  f.cache.get.mockResolvedValue(f.blob); f.cache.list.mockResolvedValue([f.entry])
  expect((await f.library.open(f.entry)).data.title).toBe('Talk')
  expect(f.request).not.toHaveBeenCalled()
  expect(f.cache.put).not.toHaveBeenCalled()
  f.request.mockRejectedValue(new Error('offline'))
  const result = await f.library.list()
  expect(result.entries[0].deviceSaved).toBe(true)
  expect(result.notice).toContain('Server unavailable')
})
it('reports cache failure honestly while preserving playable content', async () => {
  const f = setup(); f.cache.put.mockRejectedValue(new Error('quota exceeded'))
  const result = await f.library.open(f.entry)
  expect(result.deviceSaved).toBe(false)
  expect(result.data.title).toBe('Talk')
  expect(result.notice).toContain('download the offline HTML')
})
it('rejects truncated downloads without caching them', async () => {
  const f = setup()
  await expect(f.library.open({ ...f.entry, size: f.entry.size + 1 })).rejects.toThrow('Incomplete')
  expect(f.cache.put).not.toHaveBeenCalled()
})
it('keeps a device copy if server saving fails, without claiming server availability', async () => {
  const f = setup(); f.request.mockRejectedValue(new Error('offline'))
  const saved = await f.library.save(f.blob, 'Talk', 'presentation')
  expect(saved.serverSaved).toBe(false)
  expect(saved.deviceSaved).toBe(true)
  expect(saved.notice).toContain('not available on other machines')
})
it('merges server and device entries without duplicate rows', async () => {
  const f = setup(); f.cache.list.mockResolvedValue([f.entry])
  const result = await f.library.list()
  expect(result.entries).toEqual([{ ...f.entry, deviceSaved: true, serverSaved: true }])
})
