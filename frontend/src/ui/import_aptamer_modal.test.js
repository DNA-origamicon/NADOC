import { beforeEach, describe, expect, it, vi } from 'vitest'
import { openImportAptamerModal } from './import_aptamer_modal.js'

const templates = [{ id: '148D', name: 'TBA', description: 'Potassium-responsive G4', url: 'https://www.rcsb.org/structure/148D' }]
beforeEach(() => { document.body.innerHTML = '' })

describe('aptamer import', () => {
  it('shows provenance and imports the selected native template', async () => {
    const onImport = vi.fn().mockResolvedValue({ design: {} })
    await openImportAptamerModal({ api: { getAptamerCatalog: async () => ({ templates }) }, onImport })
    expect(document.querySelector('a').href).toBe(templates[0].url)
    document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(onImport).toHaveBeenCalledWith({ template_id: '148D' }))
    await vi.waitFor(() => expect(document.querySelector('[role=dialog]')).toBeNull())
  })
  it('retains the dialog and permits retry after a failed import', async () => {
    const onImport = vi.fn().mockResolvedValue(null)
    await openImportAptamerModal({ api: { getAptamerCatalog: async () => ({ templates }) }, onImport })
    document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
    await vi.waitFor(() => expect(document.querySelector('[role=status]').textContent).toContain('Import failed'))
    expect(document.querySelector('[type=submit]').disabled).toBe(false)
  })
  it('does not close or submit twice while the server is committing', async () => {
    let finish
    const onImport = vi.fn(() => new Promise(resolve => { finish = resolve }))
    await openImportAptamerModal({ api: { getAptamerCatalog: async () => ({ templates }) }, onImport })
    const form = document.querySelector('form')
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    form.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(onImport).toHaveBeenCalledTimes(1)
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    finish({ design: {} })
    await vi.waitFor(() => expect(document.querySelector('[role=dialog]')).toBeNull())
  })
})
