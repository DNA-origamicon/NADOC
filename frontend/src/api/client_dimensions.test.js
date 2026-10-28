import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getDimensions, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'

const response = (value, ok = true) => ({ ok, status: ok ? 200 : 503,
  headers: { get: () => null }, json: async () => value })
beforeEach(() => {
  resetRevisionWatermark()
  store.setState({ currentDesign: { id: 'part', dimensions: [] }, assemblyActive: false })
})
afterEach(() => { vi.unstubAllGlobals() })

it('discards a retired dimension read without reporting a save failure after same-ID reopen', async () => {
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => {
    finish = () => resolve(response({ document_id: 'part', dimensions: [{ id: 'old' }] }))
  })))
  const pending = getDimensions('design', 'part').then(value => ({ value }), error => ({ error: error.name }))
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  window.dispatchEvent(new Event('nadoc:document-reset'))
  finish()
  expect(await pending).toEqual({ value: null })
  expect(store.getState().currentDesign.dimensions).toEqual([])
})

it('still reports a failed dimension transport', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ detail: 'Unavailable' }, false)))
  await expect(getDimensions('design', 'part')).rejects.toThrow('Could not save or load dimensions')
})
