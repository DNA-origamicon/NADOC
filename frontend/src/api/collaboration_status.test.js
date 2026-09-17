import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../state/store.js', () => ({
  store: { getState: () => ({}), setState: vi.fn() },
}))
vi.mock('../ui/op_progress.js', () => ({
  showOpProgress: vi.fn(), hideOpProgress: vi.fn(), setOpProgressLabel: vi.fn(),
}))

import { getCollaborationPeerStatuses } from './client.js'
import { showOpProgress, hideOpProgress } from '../ui/op_progress.js'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('an offline peer probe never opens or closes the editor operation modal', async () => {
  vi.useFakeTimers()
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  const request = getCollaborationPeerStatuses()
  await vi.advanceTimersByTimeAsync(10_000)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(showOpProgress).not.toHaveBeenCalled()
  finish({ ok: true, status: 200, headers: new Headers(), json: async () => ({ peers: [] }) })
  await expect(request).resolves.toEqual({ peers: [] })
  expect(hideOpProgress).not.toHaveBeenCalled()
})
