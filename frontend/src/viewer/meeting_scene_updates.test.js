import { it, expect, vi } from 'vitest'
import { loadMeetingRevision } from './meeting_scene_updates.js'
it('downloads the exact announced revision and preserves the guest camera', async () => {
  const viewer = { loadFile: vi.fn(async () => true) }, isCurrent = () => true
  const fetch = vi.fn(async () => ({ ok: true, headers: new Headers({ 'Content-Length': '8' }), blob: async () => new Blob(['NADOCVW1']) }))
  expect(await loadMeetingRevision({ viewer, base: '/meeting/room', revision: 'new', fetch, isCurrent })).toBe(true)
  expect(fetch.mock.calls[0][0]).toBe('/meeting/room/scene?revision=new')
  expect(viewer.loadFile.mock.calls[0][1]).toEqual({ preserveCamera: true, expectedHash: 'new', isCurrent })
  viewer.loadFile.mockClear()
  expect(await loadMeetingRevision({ viewer, base: '/meeting/room', revision: 'old', fetch, isCurrent: () => false })).toBe(false)
  expect(viewer.loadFile).not.toHaveBeenCalled()
})
