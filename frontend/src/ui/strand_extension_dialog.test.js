// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { openStrandExtensionDialog } from './strand_extension_dialog.js'

let dialog
afterEach(() => { dialog?.close(); dialog = null; document.body.innerHTML = ''; vi.restoreAllMocks() })
function fixture(options = {}) {
  const context = { source: 'original' }
  const api = { captureExtensionContext: vi.fn(() => context),
    upsertStrandExtensionsBatch: vi.fn(async () => ({ design: {} })),
    deleteStrandExtensionsBatch: vi.fn(async () => ({ design: {} })) }
  dialog = openStrandExtensionDialog({ x: 10, y: 10, strandIds: ['s'],
    existingByStrand: new Map(), api, getError: () => ({ message: 'The part changed' }), ...options })
  return { api, context, node: document.querySelector('#__ext-dialog'),
    button: text => [...document.querySelectorAll('button')].find(node => node.textContent === text) }
}
const settle = async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }

describe('ordinary terminal extension dialog ownership', () => {
  it('captures on open, sends both termini with complete values, then closes only after acceptance', async () => {
    const f = fixture({ strandIds: ['s', 'other'] })
    f.node.querySelector('[name="sequence"]').value = ' at '
    f.node.querySelector('[name="modification"]').value = 'cy3'
    f.node.querySelector('[name="label"]').value = ' label '
    f.node.querySelector('input[value="both"]').click()
    f.button('Apply').click(); await settle()
    expect(f.api.captureExtensionContext).toHaveBeenCalledTimes(1)
    expect(f.api.upsertStrandExtensionsBatch).toHaveBeenCalledExactlyOnceWith([
      { strandId: 's', end: 'five_prime', sequence: 'AT', modification: 'cy3', label: 'label' },
      { strandId: 's', end: 'three_prime', sequence: 'AT', modification: 'cy3', label: 'label' },
      { strandId: 'other', end: 'five_prime', sequence: 'AT', modification: 'cy3', label: 'label' },
      { strandId: 'other', end: 'three_prime', sequence: 'AT', modification: 'cy3', label: 'label' },
    ], f.context)
    expect(f.node.isConnected).toBe(false)
  })
  it.each(['null', 'throw'])('retains entered values and displays %s failure', async kind => {
    const f = fixture(); f.node.querySelector('[name="sequence"]').value = 'AT'
    if (kind === 'null') f.api.upsertStrandExtensionsBatch.mockResolvedValue(null)
    else f.api.upsertStrandExtensionsBatch.mockRejectedValue(new Error('The part changed'))
    f.button('Apply').click(); await settle()
    expect(f.node.isConnected).toBe(true)
    expect(f.node.textContent).toContain('The part changed')
    expect(f.button('Apply').disabled).toBe(false)
    expect(f.node.querySelector('[name="sequence"]').value).toBe('AT')
  })
  it('batch edit explicitly clears modification and label while retaining entered sequence', async () => {
    const f = fixture({ existingByStrand: new Map([['s', { three_prime: {
      id: 'e', sequence: 'TT', modification: 'cy3', label: 'old' }, five_prime: null }]]) })
    expect(f.node.querySelector('input[value="three_prime"]').checked).toBe(true)
    f.node.querySelector('[name="modification"]').value = ''
    f.node.querySelector('[name="label"]').value = ''
    f.button('Apply').click(); await settle()
    expect(f.api.upsertStrandExtensionsBatch).toHaveBeenCalledWith([
      { strandId: 's', end: 'three_prime', sequence: 'TT', modification: null, label: null },
    ], f.context)
  })
  it('does not submit an empty annotation or invalid sequence', async () => {
    const f = fixture(); f.button('Apply').click(); await settle()
    f.node.querySelector('[name="sequence"]').value = 'AX'; f.button('Apply').click(); await settle()
    expect(f.api.upsertStrandExtensionsBatch).not.toHaveBeenCalled()
    expect(f.node.isConnected).toBe(true)
  })
  it('retains the 2D remove dialog on refusal, then removes once on acceptance', async () => {
    const f = fixture({ allowRemove: true, existingByStrand: new Map([['s', { five_prime: { id: 'e', sequence: 'A' } }]]) })
    f.api.deleteStrandExtensionsBatch.mockResolvedValueOnce(null)
    f.button('Remove all extensions').click(); await settle()
    expect(f.node.isConnected).toBe(true); expect(f.node.textContent).toContain('The part changed')
    f.button('Remove all extensions').click(); await settle()
    expect(f.api.deleteStrandExtensionsBatch).toHaveBeenCalledWith(['e'], f.context)
    expect(f.node.isConnected).toBe(false)
  })
  it.each(['cancel', 'reset', 'escape'])('%s closes without submitting and removes keyboard listeners', async kind => {
    const f = fixture(); f.node.querySelector('[name="sequence"]').value = 'AT'
    if (kind === 'cancel') f.button('Cancel').click()
    if (kind === 'reset') window.dispatchEvent(new Event('nadoc:document-reset'))
    if (kind === 'escape') document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' })); await settle()
    expect(f.node.isConnected).toBe(false); expect(f.api.upsertStrandExtensionsBatch).not.toHaveBeenCalled()
  })
  it('late completion cannot close a replacement dialog and repeated Apply does not resubmit', async () => {
    const first = fixture(); let finish
    first.api.upsertStrandExtensionsBatch.mockReturnValue(new Promise(resolve => { finish = resolve }))
    first.node.querySelector('[name="sequence"]').value = 'AT'
    const apply = first.button('Apply')
    apply.click(); apply.click()
    const second = fixture()
    finish({ design: {} }); await settle()
    expect(first.api.upsertStrandExtensionsBatch).toHaveBeenCalledTimes(1)
    expect(first.node.isConnected).toBe(false); expect(second.node.isConnected).toBe(true)
  })
})
