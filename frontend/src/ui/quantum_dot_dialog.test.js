// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import catalog from '../../../backend/data/quantum_dots/catalog.json'
import { openQuantumDotDialog } from './quantum_dot_dialog.js'

const $ = id => document.getElementById(id)
let dialog
const settle = async () => { for (let i=0;i<10;i++) await Promise.resolve() }
async function open(options = {}) {
  dialog = openQuantumDotDialog({ loadCatalog: async () => structuredClone(catalog), ...options })
  await dialog.ready
  return dialog
}
afterEach(() => { dialog?.close(); document.body.replaceChildren(); vi.restoreAllMocks() })

describe('quantum dot catalog popup', () => {
  it('shows vendor spectra and actual size ranges before importing the selected dot', async () => {
    const importDot = vi.fn(async () => ({ nanoparticle_id:'qd1' })), onImported = vi.fn()
    await open({ importDot, onImported })
    expect(document.querySelector('[role="dialog"]').getAttribute('aria-modal')).toBe('true')
    expect($('qd-rows').children.length).toBe(catalog.entries.length)
    expect(importDot).not.toHaveBeenCalled()
    document.querySelector('[data-catalog-id="nn-hecz-600"]').click()
    expect($('qd-spectra').src).toMatch(/^data:image\/png;base64,/)
    expect($('qd-spectra-link').href).toContain('#page=8')
    expect($('qd-diameter').value).toBe('9.5')
    expect($('qd-size-note').textContent).toContain('3.5–4 nm')
    $('qd-diameter').value = '9.3'
    $('qd-diameter').dispatchEvent(new Event('input'))
    $('qd-import').click()
    await settle()
    expect(importDot).toHaveBeenCalledExactlyOnceWith('nn-hecz-600',9.3)
    expect(onImported).toHaveBeenCalledWith('qd1')
    expect($('quantum-dot-dialog')).toBeNull()
  })

  it('lets users inspect streptavidin while keeping functionalized import disabled', async () => {
    const importDot = vi.fn()
    await open({ importDot })
    const row = document.querySelector('[data-catalog-id="thermo-qdot-655-streptavidin"]')
    expect(row.textContent).toContain('Streptavidin')
    row.click()
    expect($('qd-spectra').src).toMatch(/^data:image\/png;base64,/)
    expect($('qd-size-note').textContent).toContain('hydrodynamic')
    expect($('qd-import').disabled).toBe(true)
    expect($('qd-diameter').disabled).toBe(true)
    $('qd-import').click()
    expect(importDot).not.toHaveBeenCalled()
  })

  it('rejects out-of-range sizes and prevents importing a filtered-out selection', async () => {
    await open()
    $('qd-diameter').value = '100'
    $('qd-diameter').dispatchEvent(new Event('input'))
    expect($('qd-import').disabled).toBe(true)
    $('qd-search').value = 'streptavidin'
    $('qd-search').dispatchEvent(new Event('input'))
    expect($('qd-rows').children.length).toBe(8)
    expect($('qd-detail').hidden).toBe(true)
    expect($('qd-import').disabled).toBe(true)
    $('qd-search').value = 'no such dot'
    $('qd-search').dispatchEvent(new Event('input'))
    expect($('qd-status').textContent).toContain('No matching')
  })

  it('cancels without importing and restores focus, including a late catalog response', async () => {
    const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
    let resolve
    const importDot = vi.fn()
    dialog = openQuantumDotDialog({ loadCatalog: () => new Promise(r => { resolve=r }), importDot })
    await settle()
    document.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true }))
    resolve(catalog)
    await dialog.ready
    expect($('quantum-dot-dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(importDot).not.toHaveBeenCalled()
  })

  it('shows load/import errors and suppresses duplicate imports while pending', async () => {
    let resolve
    const importDot = vi.fn(() => new Promise(r => { resolve=r }))
    await open({ importDot })
    $('qd-import').click()
    $('qd-import').click()
    expect(importDot).toHaveBeenCalledTimes(1)
    expect($('qd-cancel').disabled).toBe(true)
    resolve(null)
    await settle()
    expect($('qd-error').textContent).toContain('could not be confirmed')
    expect($('qd-import').disabled).toBe(false)
    dialog.close()
    dialog = openQuantumDotDialog({ loadCatalog: async () => null })
    await dialog.ready
    expect($('qd-status').textContent).toContain('could not be loaded')
    expect($('qd-import').disabled).toBe(true)
  })
})
