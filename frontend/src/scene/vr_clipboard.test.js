import { it, expect, vi } from 'vitest'
import { createVRClipboard } from './vr_clipboard.js'
const matrix = [1,0,0,0,0,1,0,0,0,0,1,0,8,9,10,1]
const owners = [encodeURIComponent('["cluster","a"]'), encodeURIComponent('["cluster","b"]')]
function fixture() {
  const state = { currentDesign: { id: 'doc', helices: [{ id: 'h' }], feature_log: ['history'] }, selection: { items: [{ kind: 'cluster', id: 'a' }, { kind: 'cluster', id: 'b' }] } }
  const api = { validateVRClipboard: vi.fn().mockResolvedValue({ accepted: true }), pasteVRClipboard: vi.fn().mockResolvedValue({}) }
  return { state, api, clipboard: createVRClipboard({ getState: () => state, api }) }
}
it('copies the complete acknowledged selection and freezes content before validation', async () => {
  const { state, api, clipboard } = fixture()
  const pending = clipboard.copy({ owners })
  state.currentDesign.helices[0].id = 'changed'
  state.selection.items = []
  await pending
  await clipboard.paste({ matrix })
  expect(api.pasteVRClipboard.mock.calls[0][0]).toEqual({ source: { id: 'doc', helices: [{ id: 'h' }] }, refs: [{ kind: 'cluster', id: 'a' }, { kind: 'cluster', id: 'b' }], matrix })
})
it('refuses stale selection, empty clipboard and cross-document reuse', async () => {
  const { state, api, clipboard } = fixture()
  await expect(clipboard.copy({ owners: owners.slice(0, 1) })).rejects.toThrow('Selection changed')
  expect(api.validateVRClipboard).not.toHaveBeenCalled()
  await expect(clipboard.paste({ matrix })).rejects.toThrow('Copy first')
  await clipboard.copy({ owners })
  state.currentDesign.id = 'other'
  await expect(clipboard.paste({ matrix })).rejects.toThrow('Copy first')
})
it('keeps snapshot for retry after failed paste and clears on session reset', async () => {
  const { api, clipboard } = fixture()
  await clipboard.copy({ owners })
  api.pasteVRClipboard.mockRejectedValueOnce(new Error('failed'))
  await expect(clipboard.paste({ matrix })).rejects.toThrow('failed')
  await clipboard.paste({ matrix })
  clipboard.reset()
  await expect(clipboard.paste({ matrix })).rejects.toThrow('Copy first')
})
it('does not resurrect an in-flight copy after ending the session', async () => {
  const { api, clipboard } = fixture()
  let finish
  api.validateVRClipboard.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const copying = clipboard.copy({ owners })
  clipboard.reset()
  finish({ accepted: true })
  await expect(copying).rejects.toThrow('Design changed')
  await expect(clipboard.paste({ matrix })).rejects.toThrow('Copy first')
})
it('consumes a committed paste even if desktop synchronization subsequently fails', async () => {
  const { api, clipboard } = fixture()
  await clipboard.copy({ owners })
  api.pasteVRClipboard.mockImplementation(async (_, options) => {
    options.onCommitted({ design: { id: 'doc' }, revision: 2 })
    throw new Error('refresh failed')
  })
  await expect(clipboard.paste({ matrix })).rejects.toThrow('refresh failed')
  await expect(clipboard.paste({ matrix })).rejects.toThrow('Copy first')
})
