/**
 * Tests for background_modal — the View → "Background Settings…" subsystem.
 * Pure core `computeBackgroundStyle` + factory wiring (jsdom).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// createModal/createButton create real overlay DOM we don't need to assert on;
// stub them so opening the modal is observable without dragging in their markup.
const modalOpen = vi.fn()
const modalClose = vi.fn()
vi.mock('./primitives/modal.js', () => ({
  createModal: vi.fn(() => ({ open: modalOpen, close: modalClose })),
}))
vi.mock('./primitives/button.js', () => ({
  createButton: vi.fn(({ onClick }) => ({ __onClick: onClick })),
}))

import { computeBackgroundStyle, initBackgroundModal } from './background_modal.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'

const ID_TAGS = {
  'viewport-container': 'div',
  'background-modal-body': 'div',
  'bg-color-input': 'input',
  'bg-color-hex': 'input',
  'bg-image-input': 'input',
  'bg-image-fit': 'select',
  'bg-image-name': 'div',
  'bg-preview': 'div',
  'menu-view-background': 'button',
  'background-modal-aqueous': 'button',
}

describe('computeBackgroundStyle (pure)', () => {
  it('solid colour: image none, size untouched (null), preview names colour', () => {
    const s = computeBackgroundStyle({ mode: 'color', color: '#123456', imageUrl: '', imageName: '', imageFit: 'cover' })
    expect(s.backgroundImage).toBe('none')
    expect(s.backgroundSize).toBeNull()
    expect(s.backgroundColor).toBe('#123456')
    expect(s.previewText).toBe('Solid color background: #123456')
  })

  it('image with cover fit: url() image, size = fit, colour preserved', () => {
    const s = computeBackgroundStyle({ mode: 'image', color: '#000000', imageUrl: 'data:img', imageName: 'pic.png', imageFit: 'cover' })
    expect(s.backgroundImage).toBe('url("data:img")')
    expect(s.backgroundSize).toBe('cover')
    expect(s.backgroundColor).toBe('#000000')
    expect(s.previewText).toBe('Image background: pic.png')
  })

  it('image with stretch fit maps to 100% 100% and falls back to "selected image"', () => {
    const s = computeBackgroundStyle({ mode: 'image', color: '#000', imageUrl: 'data:x', imageName: '', imageFit: 'stretch' })
    expect(s.backgroundSize).toBe('100% 100%')
    expect(s.previewText).toBe('Image background: selected image')
  })

  it('image mode but no url falls through to solid-colour branch', () => {
    const s = computeBackgroundStyle({ mode: 'image', color: '#abcdef', imageUrl: '', imageName: 'unused', imageFit: 'cover' })
    expect(s.backgroundImage).toBe('none')
    expect(s.backgroundSize).toBeNull()
    expect(s.previewText).toBe('Solid color background: #abcdef')
  })

  it('aqueous: gradient image, cover, fixed teal colour, aqueous preview', () => {
    const s = computeBackgroundStyle({ mode: 'aqueous', color: '#0d1117', imageUrl: '', imageName: '', imageFit: 'cover' })
    expect(s.backgroundImage).toContain('linear-gradient')
    expect(s.backgroundSize).toBe('cover')
    expect(s.backgroundColor).toBe('#07324a')
    expect(s.previewText).toMatch(/Aqueous theme/)
  })
})

describe('initBackgroundModal (factory)', () => {
  let els
  beforeEach(() => {
    vi.clearAllMocks()
    els = mountIds(ID_TAGS)
  })
  afterEach(() => clearDom())

  it('applies the default solid-colour style to the container on init', () => {
    const { getState } = initBackgroundModal()
    expect(getState().mode).toBe('color')
    expect(els['viewport-container'].style.backgroundImage).toBe('none')
    expect(els['viewport-container'].style.backgroundColor).toBe('rgb(13, 17, 23)') // #0d1117
    expect(els['bg-preview'].textContent).toBe('Solid color background: #0d1117')
  })

  it('colour input event updates state + container + mirrors to hex field', () => {
    initBackgroundModal()
    els['bg-color-input'].value = '#ff0000'
    els['bg-color-input'].dispatchEvent(new Event('input'))
    expect(els['viewport-container'].style.backgroundColor).toBe('rgb(255, 0, 0)')
    expect(els['bg-color-hex'].value).toBe('#ff0000')
  })

  it('hex input applies only on a valid 6-digit hex', () => {
    const { getState } = initBackgroundModal()
    els['bg-color-hex'].value = 'nothex'
    els['bg-color-hex'].dispatchEvent(new Event('input'))
    expect(getState().color).toBe('#0d1117') // unchanged
    els['bg-color-hex'].value = '#00ff00'
    els['bg-color-hex'].dispatchEvent(new Event('input'))
    expect(getState().color).toBe('#00ff00')
    expect(els['bg-color-input'].value).toBe('#00ff00')
  })

  it('aqueous button switches mode + applies gradient', () => {
    const { getState } = initBackgroundModal()
    els['background-modal-aqueous'].dispatchEvent(new Event('click'))
    expect(getState().mode).toBe('aqueous')
    expect(els['viewport-container'].style.backgroundImage).toContain('linear-gradient')
    expect(els['bg-preview'].textContent).toMatch(/Aqueous theme/)
  })

  it('image-fit change re-applies only when in image mode', () => {
    const { getState } = initBackgroundModal()
    const opt = document.createElement('option')
    opt.value = 'contain'
    els['bg-image-fit'].appendChild(opt)
    els['bg-image-fit'].value = 'contain'
    els['bg-image-fit'].dispatchEvent(new Event('change'))
    expect(getState().imageFit).toBe('contain')
    expect(els['viewport-container'].style.backgroundImage).toBe('none') // still color mode
  })

  it('opening the menu lazily builds the modal once and opens it', () => {
    initBackgroundModal()
    els['menu-view-background'].dispatchEvent(new Event('click'))
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(1)
    expect(els['background-modal-body'].hasAttribute('hidden')).toBe(false)
    // second open reuses the existing controller (no rebuild)
    els['menu-view-background'].dispatchEvent(new Event('click'))
    expect(createModal).toHaveBeenCalledTimes(1)
    expect(modalOpen).toHaveBeenCalledTimes(2)
  })

  it('Reset button (2nd createButton) restores defaults', () => {
    const { getState } = initBackgroundModal()
    els['background-modal-aqueous'].dispatchEvent(new Event('click'))
    els['menu-view-background'].dispatchEvent(new Event('click'))
    // createButton order in buildModalOnce: Cancel, Reset, Apply
    expect(createButton.mock.calls[1][0].label).toBe('Reset')
    createButton.mock.results[1].value.__onClick()
    expect(getState().mode).toBe('color')
    expect(getState().color).toBe('#0d1117')
    expect(els['viewport-container'].style.backgroundImage).toBe('none')
  })
})
