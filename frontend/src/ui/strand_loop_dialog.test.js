import { it, expect, vi, afterEach } from 'vitest'
import { loopAt, openStrandLoopDialog } from './strand_loop_dialog.js'
const anchor = { helix_id: 'h', bp_index: 10, direction: 'REVERSE' }
afterEach(() => document.body.replaceChildren())
it('resolves only the selected strand track', () => {
  const loop = { ...anchor, length: 30 }
  expect(loopAt({ loops: [loop] }, anchor)).toBe(loop)
  expect(loopAt({ loops: [loop] }, { ...anchor, direction: 'FORWARD' })).toBeUndefined()
})
it('saves count and aspect ratio with the clicked base identity', async () => {
  HTMLDialogElement.prototype.showModal = vi.fn()
  const save = vi.fn().mockResolvedValue({ design: {} })
  const dialog = openStrandLoopDialog({ strand: { id: 'staple' }, anchor, save })
  dialog.querySelector('[name="length"]').value = '42'
  dialog.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(dialog.isConnected).toBe(false))
  expect(save).toHaveBeenCalledWith({ strand_id: 'staple', ...anchor, length: 42, aspect_ratio: 3, rotation_deg: 0 })
})
it('keeps failed changes open and supports removal', async () => {
  HTMLDialogElement.prototype.showModal = vi.fn()
  const save = vi.fn().mockRejectedValue(new Error('No following nucleotide'))
  const dialog = openStrandLoopDialog({ strand: { id: 's', loops: [{ ...anchor, length: 30 }] }, anchor, save })
  dialog.querySelector('[data-action="remove"]').click()
  await vi.waitFor(() => expect(dialog.querySelector('[role="alert"]').textContent).toContain('No following'))
  expect(save.mock.calls[0][0].length).toBe(0)
  expect(dialog.isConnected).toBe(true)
})
