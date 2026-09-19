import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createAnnotationController } from '../scene/annotation_controller.js'
import { initAnnotationPanel } from './annotation_panel.js'

let root, controller, store, panel
const design = { strands: [{ id: 's1', name: 'Scaffold' }] }

beforeEach(() => {
  root = document.createElement('div')
  document.body.append(root)
  controller = createAnnotationController()
  controller.syncFromDesign({ id: 'd1', annotations: [] })
  store = createMockStore({ currentDesign: design, selection: { context: 'design', items: [], primary: null } })
  panel = initAnnotationPanel({ root, controller, store, getDesign: () => store.getState().currentDesign })
})
afterEach(() => { panel.dispose(); root.remove() })

const cards = () => [...root.querySelectorAll('.anno-card')]
const field = (card, name) => card.querySelector(`[data-field="${name}"]`)
const input = (el, value) => { el.value = value; el.dispatchEvent(new window.Event('input', { bubbles: true })) }

describe('annotation panel', () => {
  it('starts empty, adds entries into a scrollable list and focuses the new text box', () => {
    expect(root.querySelector('.anno-empty')).toBeTruthy()
    root.querySelector('.anno-add').click()
    root.querySelector('.anno-add').click()
    expect(cards()).toHaveLength(2)
    expect(root.querySelector('.anno-count').textContent).toBe('2')
    expect(root.querySelector('.anno-list')).toBeTruthy()
    expect(document.activeElement).toBe(field(cards()[1], 'text'))
  })

  it('exposes every requested control on each entry, in order', () => {
    root.querySelector('.anno-add').click()
    const card = cards()[0]
    const order = [...card.querySelectorAll('[data-field]')].map(e => e.dataset.field)
    const wanted = ['text', 'icon', 'calloutType', 'color', 'transparency', 'size', 'manual', 'useSelection']
    expect(wanted.map(f => order.indexOf(f))).toEqual([...wanted.map(f => order.indexOf(f))].sort((a, b) => a - b))
    for (const f of wanted) expect(order).toContain(f)
  })

  it('edits write through to the controller without re-rendering (focus survives typing)', () => {
    root.querySelector('.anno-add').click()
    const card = cards()[0]
    const id = card.dataset.annotationId
    const text = field(card, 'text')
    text.focus()
    input(text, 'Check this')
    input(field(card, 'size'), '1.5')
    input(field(card, 'transparency'), '0.4')
    input(field(card, 'color'), '#123456')
    field(card, 'calloutType').value = 'rounded'
    field(card, 'calloutType').dispatchEvent(new window.Event('change'))
    const e = controller.get(id)
    expect(e).toMatchObject({ text: 'Check this', size: 1.5, transparency: 0.4, color: '#123456', calloutType: 'rounded' })
    expect(cards()[0]).toBe(card)
    expect(document.activeElement).toBe(text)
  })

  it('warns until the entry has text or an icon', () => {
    root.querySelector('.anno-add').click()
    const card = cards()[0]
    expect(card.querySelector('.anno-warn').hidden).toBe(false)
    input(field(card, 'text'), 'x')
    expect(card.querySelector('.anno-warn').hidden).toBe(true)
    input(field(card, 'text'), '')
    expect(card.querySelector('.anno-warn').hidden).toBe(false)
  })

  it('icon popup offers the standard icons and None, applies the pick and closes', () => {
    root.querySelector('.anno-add').click()
    const card = cards()[0]
    field(card, 'icon').click()
    const pop = root.querySelector('.anno-icon-pop')
    const labels = [...pop.querySelectorAll('button')].map(b => b.title)
    expect(labels).toEqual(expect.arrayContaining(['Warning', 'Attention', 'Green check', 'Red X']))
    pop.querySelector('[title="Green check"]').click()
    expect(controller.get(card.dataset.annotationId).icon).toBe('check')
    expect(root.querySelector('.anno-icon-pop')).toBeNull()
    expect(card.querySelector('.anno-warn').hidden).toBe(true)
    field(card, 'icon').click()
    root.querySelector('.anno-icon-none').click()
    expect(controller.get(card.dataset.annotationId).icon).toBeNull()
  })

  it('icon popup closes on Escape and on an outside press', () => {
    root.querySelector('.anno-add').click()
    field(cards()[0], 'icon').click()
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(root.querySelector('.anno-icon-pop')).toBeNull()
    field(cards()[0], 'icon').click()
    document.body.dispatchEvent(new window.MouseEvent('pointerdown', { bubbles: true }))
    expect(root.querySelector('.anno-icon-pop')).toBeNull()
  })

  it('keeps the icon popup on screen when its button sits at the right edge', () => {
    Object.defineProperty(window, 'innerWidth', { value: 1000, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 700, configurable: true })
    const original = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = function () {
      return this.classList?.contains('anno-icon-btn') ? { left: 940, right: 1000, top: 300, bottom: 326, width: 60, height: 26 } : original.call(this)
    }
    const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get() { return this.classList?.contains('anno-icon-pop') ? 208 : 0 } })
    try {
      root.querySelector('.anno-add').click()
      field(cards()[0], 'icon').click()
      const left = parseFloat(root.querySelector('.anno-icon-pop').style.left)
      expect(left + 208).toBeLessThanOrEqual(1000 - 8)
      expect(left).toBeGreaterThanOrEqual(8)
    } finally {
      HTMLElement.prototype.getBoundingClientRect = original
      if (width) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', width); else delete HTMLElement.prototype.offsetWidth
    }
  })

  it('flips the icon popup above its button near the bottom edge', () => {
    Object.defineProperty(window, 'innerWidth', { value: 1000, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 500, configurable: true })
    const original = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = function () {
      return this.classList?.contains('anno-icon-btn') ? { left: 100, right: 160, top: 470, bottom: 496, width: 60, height: 26 } : original.call(this)
    }
    try {
      root.querySelector('.anno-add').click()
      field(cards()[0], 'icon').click()
      expect(parseFloat(root.querySelector('.anno-icon-pop').style.top)).toBeLessThan(470)
    } finally { HTMLElement.prototype.getBoundingClientRect = original }
  })

  it('manual toggle persists to the entry', () => {
    root.querySelector('.anno-add').click()
    const box = field(cards()[0], 'manual')
    box.checked = true
    box.dispatchEvent(new window.Event('change'))
    expect(controller.get(cards()[0].dataset.annotationId).manual).toBe(true)
  })

  it('accepts protein and nanoparticle selections as targets', () => {
    store.setState({ currentDesign: { ...design, nanoparticles: [{ id: 'n1', kind: 'gold_nanosphere', diameter_nm: 20 }] } })
    root.querySelector('.anno-add').click()
    store.setState({ selection: { context: 'design', items: [{ kind: 'nanoparticle', id: 'n1' }, { kind: 'protein', id: 'p1' }], primary: null } })
    field(cards()[0], 'useSelection').click()
    expect(controller.list()[0].refs).toEqual([{ kind: 'nanoparticle', id: 'n1' }, { kind: 'protein', id: 'p1' }])
    expect(cards()[0].querySelector('.anno-target').textContent).toBe('2 items · 1 nanoparticle, 1 protein')
    expect(cards()[0].textContent).not.toContain('no backbone')
  })

  it('Use selection needs a selection, then attaches every selected ref and shows a label', () => {
    root.querySelector('.anno-add').click()
    const use = () => field(cards()[0], 'useSelection')
    expect(use().disabled).toBe(true)
    store.setState({ selection: { context: 'design', items: [{ kind: 'strand', id: 's1' }], primary: { kind: 'strand', id: 's1' } } })
    expect(use().disabled).toBe(false)
    use().click()
    expect(controller.get(cards()[0].dataset.annotationId).refs).toEqual([{ kind: 'strand', id: 's1' }])
    expect(cards()[0].querySelector('.anno-target').textContent).toBe('Strand · Scaffold')
    field(cards()[0], 'clearTarget').click()
    expect(controller.list()[0].refs).toEqual([])
    expect(cards()[0].querySelector('.anno-target').textContent).toBe('No target')
  })

  it('global enable toggle mirrors the controller, disables the viewport layer switch and is kept when off', async () => {
    const box = root.querySelector('[data-field="enabled"]')
    expect(box.checked).toBe(true)
    root.querySelector('.anno-add').click()
    box.checked = false; box.dispatchEvent(new window.Event('change'))
    expect(controller.isEnabled()).toBe(false)
    expect(root.querySelector('.anno-list').classList.contains('is-globally-off')).toBe(true)
    expect(cards()).toHaveLength(1)                       // entries are kept, just hidden in the viewport
    await controller.flush()                                                              // saved…
    controller.syncFromDesign({ id: 'd1', annotations: [], annotations_enabled: true })   // …then an external change (file reload)
    expect(box.checked).toBe(true)
  })

  it('toggle visibility and delete', () => {
    root.querySelector('.anno-add').click()
    field(cards()[0], 'visible').click()
    expect(controller.list()[0].visible).toBe(false)
    field(cards()[0], 'delete').click()
    expect(cards()).toHaveLength(0)
    expect(root.querySelector('.anno-empty')).toBeTruthy()
  })

  it('reloads its list when the design changes and hides itself outside part mode', () => {
    root.querySelector('.anno-add').click()
    controller.syncFromDesign({ id: 'd2', annotations: [] })
    expect(cards()).toHaveLength(0)
    panel.setAvailable(false)
    expect(root.querySelector('.anno-list').hidden).toBe(true)
    expect(root.querySelector('.anno-unavailable').hidden).toBe(false)
    panel.setAvailable(true)
    expect(root.querySelector('.anno-list').hidden).toBe(false)
  })
})
