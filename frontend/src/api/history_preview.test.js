import { afterEach, expect, it, vi } from 'vitest'
import { cancelHistoryPreview, registerHistoryPreviewCanceller } from './history_preview.js'
import { undo, redo, undoAssembly, redoAssembly } from './client.js'

afterEach(() => { registerHistoryPreviewCanceller(null); vi.unstubAllGlobals() })

it.each([undo, redo, undoAssembly, redoAssembly])('history waits for preview restoration and stops if it fails: %s', async history => {
  let fail
  const restore = vi.fn(() => new Promise((_resolve, reject) => { fail = reject }))
  registerHistoryPreviewCanceller(restore)
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
  const pending = history()
  const rejected = expect(pending).rejects.toThrow('restore failed')
  await vi.waitFor(() => expect(restore).toHaveBeenCalledOnce())
  expect(fetch).not.toHaveBeenCalled()
  fail(new Error('restore failed'))
  await rejected
  expect(fetch).not.toHaveBeenCalled()
})

it('coalesces concurrent restoration and releases the boundary after completion', async () => {
  let finish
  const restore = vi.fn(() => new Promise(resolve => { finish = resolve }))
  const unregister = registerHistoryPreviewCanceller(restore)
  const a = cancelHistoryPreview(), b = cancelHistoryPreview()
  await vi.waitFor(() => expect(restore).toHaveBeenCalledOnce())
  finish(); await Promise.all([a, b])
  unregister()
  await cancelHistoryPreview()
  expect(restore).toHaveBeenCalledOnce()
})
