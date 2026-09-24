import { it, expect, vi, afterEach } from 'vitest'
import { mountGuestSharedViews } from './guest_shared_views.js'
afterEach(() => { document.body.innerHTML = '' })
it('uploads only on explicit clicks, replaces the pose on re-share, and confirms with one ping', async () => {
  const fetch = vi.fn(async () => ({ ok: true })), onPublished = vi.fn(), captureCamera = vi.fn(() => ({ position: [1, 2, 3] }))
  const ui = mountGuestSharedViews({ parent: document.body, viewer: { captureCamera }, getRevision: () => 'revision', ready: () => true, beforeMove: vi.fn(), base: '/meeting/room', fetch, onPublished })
  ui.update(); expect(fetch).not.toHaveBeenCalled()
  document.querySelector('button').click(); await vi.waitFor(() => expect(onPublished).toHaveBeenCalledOnce())
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ revision: 'revision', camera: { position: [1, 2, 3] } })
  captureCamera.mockReturnValue({ position: [4, 5, 6] }); ui.update(); expect(fetch).toHaveBeenCalledOnce()
  document.querySelector('button').click(); await vi.waitFor(() => expect(onPublished).toHaveBeenCalledTimes(2))
  expect(JSON.parse(fetch.mock.calls[1][1].body).camera.position).toEqual([4, 5, 6]); ui.dispose()
})
