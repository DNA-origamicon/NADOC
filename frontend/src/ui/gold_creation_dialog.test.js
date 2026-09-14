import { beforeEach, describe, expect, it, vi } from 'vitest'
import { openGoldCreationDialog } from './gold_creation_dialog.js'

beforeEach(() => {
  document.body.innerHTML = ''
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event('close')) }
})
const input = value => { const el = document.getElementById('gold-diameter'); el.value = value; el.dispatchEvent(new Event('input')) }

describe('gold creation popup', () => {
  it('keeps the popup open when the API reports failure by returning null', async () => {
    openGoldCreationDialog({ create: vi.fn().mockResolvedValue(null) })
    document.getElementById('gold-create').click()
    await vi.waitFor(() => expect(document.getElementById('gold-error').textContent).toContain('Could not create'))
    expect(document.getElementById('gold-creation-dialog').open).toBe(true)
    expect(document.getElementById('gold-create').disabled).toBe(false)
  })
  it('updates spectra without conjugation controls', () => {
    openGoldCreationDialog()
    const initial = document.getElementById('gold-epsilon').textContent
    input('80')
    expect(document.getElementById('gold-epsilon').textContent).not.toBe(initial)
    expect(document.querySelectorAll('#gold-spectrum polyline')).toHaveLength(3)
    expect(document.getElementById('gold-coating')).toBeNull()
    input('200')
    expect(document.getElementById('gold-optics-content').hidden).toBe(true)
    expect(document.getElementById('gold-create').disabled).toBe(false)
    input('0')
    expect(document.getElementById('gold-create').disabled).toBe(true)
  })
  it('creates exactly once with the entered size and selects the result', async () => {
    let resolve
    const create = vi.fn(() => new Promise(r => { resolve = r })), onCreated = vi.fn()
    openGoldCreationDialog({ create, onCreated })
    input('23.5')
    const button = document.getElementById('gold-create')
    button.click(); button.click()
    expect(create).toHaveBeenCalledExactlyOnceWith(23.5)
    resolve({ nanoparticle_id: 'gold1' })
    await vi.waitFor(() => expect(onCreated).toHaveBeenCalledWith('gold1'))
    expect(document.getElementById('gold-creation-dialog')).toBeNull()
  })
  it('retains the size and allows retry after an API error; cancel creates nothing', async () => {
    const create = vi.fn().mockRejectedValue(new Error('Connection lost'))
    openGoldCreationDialog({ create })
    input('42')
    document.getElementById('gold-create').click()
    await vi.waitFor(() => expect(document.getElementById('gold-error').textContent).toBe('Connection lost'))
    expect(document.getElementById('gold-diameter').value).toBe('42')
    expect(document.getElementById('gold-create').disabled).toBe(false)
    document.getElementById('gold-cancel').click()
    expect(create).toHaveBeenCalledTimes(1)
  })
})
