/**
 * Unit tests for the lattice-type picker modal (jsdom).
 *
 * pickLattice() builds an overlay, returns a Promise resolving to the chosen
 * lattice string or null. Drive it by querying the DOM it appends and clicking
 * / dispatching keys, then await the returned promise.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { pickLattice } from './lattice_picker.js'

const btn = label => [...document.querySelectorAll('button')].find(b => b.textContent === label)
const radio = val => document.querySelector(`input[name=pick-lattice][value=${val}]`)
const box = () => document.querySelector('div[tabindex]')        // the focusable dialog box
const overlay = () => box()?.parentElement ?? null               // its fixed full-screen backdrop
const sendKey = key => box().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))

beforeEach(() => { document.body.innerHTML = '' })

describe('pickLattice', () => {
  it('mounts an overlay with both lattice options, Honeycomb checked by default', () => {
    pickLattice()
    expect(overlay()).toBeTruthy()
    expect(radio('HONEYCOMB').checked).toBe(true)
    expect(radio('SQUARE').checked).toBe(false)
  })

  it('Create resolves with the default (HONEYCOMB) and removes the overlay', async () => {
    const p = pickLattice()
    btn('Create').click()
    await expect(p).resolves.toBe('HONEYCOMB')
    expect(overlay()).toBeNull()
  })

  it('selecting Square then Create resolves with SQUARE', async () => {
    const p = pickLattice()
    const sq = radio('SQUARE')
    sq.checked = true
    sq.dispatchEvent(new Event('change'))
    btn('Create').click()
    await expect(p).resolves.toBe('SQUARE')
  })

  it('Cancel resolves with null', async () => {
    const p = pickLattice()
    btn('Cancel').click()
    await expect(p).resolves.toBeNull()
    expect(overlay()).toBeNull()
  })

  it('Enter accepts the current selection', async () => {
    const p = pickLattice()
    const sq = radio('SQUARE')
    sq.checked = true
    sq.dispatchEvent(new Event('change'))
    sendKey('Enter')
    await expect(p).resolves.toBe('SQUARE')
  })

  it('Escape cancels (resolves null)', async () => {
    const p = pickLattice()
    sendKey('Escape')
    await expect(p).resolves.toBeNull()
  })

  it('highlights the selected option border on change', () => {
    pickLattice()
    const sq = radio('SQUARE')
    sq.checked = true
    sq.dispatchEvent(new Event('change'))
    const labels = [...document.querySelectorAll('label')]
    // Honeycomb label de-emphasized, Square label highlighted (#388bfd)
    expect(labels[0].style.borderColor).toBe('rgb(33, 38, 45)')   // #21262d
    expect(labels[1].style.borderColor).toBe('rgb(56, 139, 253)') // #388bfd
  })
})
