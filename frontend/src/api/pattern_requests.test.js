import { afterEach, expect, it, vi } from 'vitest'
import { createCircularPattern, createLinearPattern } from './client.js'
import { store } from '../state/store.js'

afterEach(() => vi.unstubAllGlobals())

it.each([createCircularPattern, createLinearPattern])('rejects failed pattern requests so tools keep their preview open', async createPattern => {
  const design = { id: 'source', helices: [], strands: [] }
  store.setState({ currentDesign: design, assemblyActive: false })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, status: 400, headers: { get: () => null },
    json: async () => ({ detail: 'Source cluster no longer exists' }),
  }))
  await expect(createPattern({})).rejects.toThrow('Source cluster no longer exists')
  expect(store.getState().currentDesign).toBe(design)
})
