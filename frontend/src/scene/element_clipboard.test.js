import { expect, it, vi } from 'vitest'
import { initElementClipboard } from './element_clipboard.js'

it('snapshots at copy time, increments successful offsets, and selects pasted owners', async () => {
  const state = { currentDesign: { nanoparticles: [{ id: 'n', diameter_nm: 10 }] }, selection: { items: [{ kind: 'nanoparticle', id: 'n' }] } }
  const api = { pasteElements: vi.fn().mockResolvedValue({ pasted_refs: [{ kind: 'nanoparticle', id: 'copy' }] }) }
  const selectionController = { replace: vi.fn() }
  const cb = initElementClipboard({ store: { getState: () => state }, api, selectionController, showToast: vi.fn() })
  expect(cb.copy()).toBe(true)
  state.currentDesign.nanoparticles[0].diameter_nm = 20
  await cb.paste()
  await cb.paste()
  expect(api.pasteElements.mock.calls[0][0].source.nanoparticles[0].diameter_nm).toBe(10)
  expect(api.pasteElements.mock.calls.map(c => c[0].paste_index)).toEqual([1, 2])
  expect(selectionController.replace).toHaveBeenCalledWith([{ kind: 'nanoparticle', id: 'copy' }])
  cb.clear()
  expect(cb.hasCopy()).toBe(false)
})

it('prevents overlapping pastes and retries failures at the same offset', async () => {
  let finish
  const api = { pasteElements: vi.fn(() => new Promise(resolve => { finish = resolve })) }
  const store = { getState: () => ({ currentDesign: {}, selection: { items: [{ kind: 'protein', id: 'p' }] } }) }
  const cb = initElementClipboard({ store, api, selectionController: { replace: vi.fn() }, showToast: vi.fn() })
  cb.copy()
  const first = cb.paste()
  expect(await cb.paste()).toBe(false)
  finish(null)
  expect(await first).toBe(false)
  const retry = cb.paste()
  finish({ pasted_refs: [] })
  await retry
  expect(api.pasteElements.mock.calls.map(c => c[0].paste_index)).toEqual([1, 1])
})
