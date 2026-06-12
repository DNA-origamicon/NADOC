/**
 * Factory-wiring tests for the Primitives sidebar panel.
 *
 * jsdom DOM (the #primitives-panel section + its list) + the real catalog.
 * Asserts the observable contract: hidden-until-activate, one card per
 * primitive, single-select highlight, collapse toggle, clean hide.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { PRIMITIVES } from './primitive_catalog.js'
import { initPrimitiveLibrary } from './primitive_library.js'

beforeEach(() => {
  clearDom()
  localStorage.clear()
  mountIds({
    'primitives-panel': 'div',
    'primitives-panel-heading': 'h2',
    'primitives-panel-arrow': 'span',
    'primitives-panel-body': 'div',
    'primitives-list': 'div',
    'viewport-container': 'div',   // hover-zoom anchors to this
    'filter-view-strip': 'div',
    'primitive-placement': 'div',
    'primitive-placement-name': 'div',
    'primitive-plane': 'select',
    'primitive-length': 'input',
    'primitive-place-cancel': 'button',
  })
  // origin-plane options for the dropdown (matches index.html)
  const sel = document.getElementById('primitive-plane')
  for (const v of ['XY', 'XZ', 'YZ']) {
    const o = document.createElement('option'); o.value = v; sel.appendChild(o)
  }
})

// A primitive card from the API, carrying a placement spec.
function apiCardWithPlacement(over = {}) {
  return {
    id: 'beam_6hb', name: '6-Helix Bundle', short_name: '6HB', description: 'd',
    lattice: 'HONEYCOMB', helix_count: 6,
    placement: {
      cells: [[0, 1], [1, 1], [1, 2]], anchor_cell: [0, 1], length_bp: 42,
      plane: 'XY', strand_filter: 'both', ligate_adjacent: true, lattice: 'HONEYCOMB',
    },
    ...over,
  }
}
const placeBox = () => document.getElementById('primitive-placement')

const zoom = () => document.getElementById('primitive-preview-zoom')

function cards() {
  return [...document.querySelectorAll('#primitives-list .primitive-card')]
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('initPrimitiveLibrary — list build', () => {
  it('renders the static catalog fallback immediately (svg thumb)', () => {
    initPrimitiveLibrary({})
    expect(cards().length).toBe(PRIMITIVES.length)
    const first = cards()[0]
    expect(first.dataset.primitiveId).toBe(PRIMITIVES[0].id)
    expect(first.querySelector('.primitive-thumb svg')).toBeTruthy()
    expect(first.querySelector('.primitive-card-desc').textContent).toBe(PRIMITIVES[0].description)
  })

  it('upgrades to the live API catalog with poster thumbnails when the fetch resolves', async () => {
    const api = {
      listPrimitives: async () => [
        { id: 'beam_6hb', name: '6-Helix Bundle', short_name: '6HB', description: 'd',
          lattice: 'HONEYCOMB', helix_count: 6, poster_url: '/api/primitives/beam_6hb/poster.png',
          preview_url: '/api/primitives/beam_6hb/preview.gif' },
      ],
    }
    initPrimitiveLibrary({ api })
    await flush()
    expect(cards().length).toBe(1)
    const img = cards()[0].querySelector('.primitive-thumb-img')
    expect(img).toBeTruthy()
    expect(img.getAttribute('src')).toBe('/api/primitives/beam_6hb/poster.png')
    expect(img.getAttribute('data-anim')).toBe('/api/primitives/beam_6hb/preview.gif')
  })

  it('keeps the fallback when the API returns empty', async () => {
    initPrimitiveLibrary({ api: { listPrimitives: async () => [] } })
    await flush()
    expect(cards().length).toBe(PRIMITIVES.length)
    expect(cards()[0].querySelector('.primitive-thumb svg')).toBeTruthy()
  })

  it('returns a no-op API when the panel DOM is absent', () => {
    clearDom()
    const api = initPrimitiveLibrary({})
    expect(api.isActive()).toBe(false)
    expect(api.getSelected()).toBeNull()
    expect(() => api.activate()).not.toThrow()
  })
})

describe('initPrimitiveLibrary — hover preview swap', () => {
  it('swaps poster → animated preview on hover and back on leave', async () => {
    const api = {
      listPrimitives: async () => [
        { id: 'beam_6hb', name: '6HB', short_name: '6HB', description: 'd', lattice: 'HONEYCOMB',
          helix_count: 6, poster_url: '/poster.png', preview_url: '/anim.gif' },
      ],
    }
    initPrimitiveLibrary({ api })
    await flush()
    const card = cards()[0]
    const img = card.querySelector('.primitive-thumb-img')
    expect(img.src).toContain('/poster.png')
    card.dispatchEvent(new Event('mouseenter'))
    expect(img.src).toContain('/anim.gif')
    card.dispatchEvent(new Event('mouseleave'))
    expect(img.src).toContain('/poster.png')
  })

  it('shows a larger workspace-corner preview on hover and hides it on leave', async () => {
    const api = {
      listPrimitives: async () => [
        { id: 'beam_6hb', name: '6-Helix Bundle', short_name: '6HB', description: 'd', lattice: 'HONEYCOMB',
          helix_count: 6, poster_url: '/poster.png', preview_url: '/anim.gif' },
      ],
    }
    initPrimitiveLibrary({ api })
    await flush()
    const card = cards()[0]

    card.dispatchEvent(new Event('mouseenter'))
    const z = zoom()
    expect(z).toBeTruthy()
    expect(z.style.display).toBe('block')
    expect(z.querySelector('img').src).toContain('/anim.gif')   // prefers the animated preview
    expect(z.querySelector('.ppz-caption').textContent).toBe('6-Helix Bundle')

    card.dispatchEvent(new Event('mouseleave'))
    expect(zoom().style.display).toBe('none')
  })

  it('zoom falls back to the SVG schematic when a primitive has no preview', () => {
    initPrimitiveLibrary({})   // static fallback catalog — no poster/preview URLs
    cards()[0].dispatchEvent(new Event('mouseenter'))
    const z = zoom()
    expect(z.style.display).toBe('block')
    expect(z.querySelector('.ppz-svg svg')).toBeTruthy()
    expect(z.querySelector('img').style.display).toBe('none')
  })

  it('hide() also dismisses the zoom', async () => {
    const api = { listPrimitives: async () => [
      { id: 'beam_6hb', name: '6HB', short_name: '6HB', description: 'd', lattice: 'HONEYCOMB',
        helix_count: 6, poster_url: '/p.png', preview_url: '/a.gif' },
    ] }
    const panel = initPrimitiveLibrary({ api })
    await flush()
    cards()[0].dispatchEvent(new Event('mouseenter'))
    expect(zoom().style.display).toBe('block')
    panel.hide()
    expect(zoom().style.display).toBe('none')
  })

  it('selection survives the fallback → API re-render', async () => {
    const api = {
      listPrimitives: async () => [
        { id: 'beam_6hb', name: '6HB', short_name: '6HB', description: 'd', lattice: 'HONEYCOMB', helix_count: 6 },
      ],
    }
    const panel = initPrimitiveLibrary({ api })
    cards()[0].click()                       // select against the fallback render
    expect(panel.getSelected()).toBe(PRIMITIVES[0].id)
    await flush()                            // API re-render
    // beam_6hb is also the first fallback id, so the highlight should persist.
    expect(cards()[0].classList.contains('is-selected')).toBe(true)
  })
})

describe('initPrimitiveLibrary — visibility', () => {
  it('is hidden until activate(), then hide() tears it down', () => {
    const api = initPrimitiveLibrary({})
    const panel = document.getElementById('primitives-panel')

    api.activate()
    expect(panel.style.display).toBe('block')
    expect(api.isActive()).toBe(true)

    api.hide()
    expect(panel.style.display).toBe('none')
    expect(api.isActive()).toBe(false)
  })
})

describe('initPrimitiveLibrary — selection highlight', () => {
  it('clicking a card selects only it (highlight + aria + getSelected)', () => {
    const api = initPrimitiveLibrary({})
    api.activate()

    cards()[0].click()
    expect(api.getSelected()).toBe(PRIMITIVES[0].id)
    expect(cards()[0].classList.contains('is-selected')).toBe(true)
    expect(cards()[0].getAttribute('aria-selected')).toBe('true')

    cards()[1].click()
    expect(api.getSelected()).toBe(PRIMITIVES[1].id)
    expect(cards()[1].classList.contains('is-selected')).toBe(true)
    expect(cards()[0].classList.contains('is-selected')).toBe(false)
    expect(cards()[0].getAttribute('aria-selected')).toBe('false')
  })
})

describe('initPrimitiveLibrary — placement', () => {
  function setup(over = {}) {
    const calls = { enter: [], setLength: [], cancel: 0 }
    const placement = {
      enter: (spec) => calls.enter.push(spec),
      setLength: (bp) => calls.setLength.push(bp),
      cancel: () => { calls.cancel++ },
    }
    const api = { listPrimitives: async () => [apiCardWithPlacement(over)] }
    const panel = initPrimitiveLibrary({ api, placement })
    return { calls, panel }
  }

  it('selecting a primitive reveals the controls and arms placement with its spec', async () => {
    const { calls } = setup()
    await flush()
    cards()[0].click()
    expect(placeBox().style.display).toBe('block')
    expect(document.getElementById('primitive-plane').value).toBe('XY')
    expect(document.getElementById('primitive-length').value).toBe('42')
    expect(calls.enter.length).toBe(1)
    expect(calls.enter[0]).toMatchObject({
      cells: [[0, 1], [1, 1], [1, 2]], anchorCell: [0, 1], lengthBp: 42, plane: 'XY',
      strandFilter: 'both', ligateAdjacent: true, latticeType: 'HONEYCOMB',
    })
  })

  it('changing the plane dropdown re-arms placement on the new plane', async () => {
    const { calls } = setup()
    await flush()
    cards()[0].click()
    const sel = document.getElementById('primitive-plane')
    sel.value = 'XZ'
    sel.dispatchEvent(new Event('change'))
    expect(calls.enter.at(-1).plane).toBe('XZ')
  })

  it('editing the length input live-updates the footprint length', async () => {
    const { calls } = setup()
    await flush()
    cards()[0].click()
    const len = document.getElementById('primitive-length')
    len.value = '64'
    len.dispatchEvent(new Event('input'))
    expect(calls.setLength.at(-1)).toBe(64)
  })

  it('Cancel exits placement (hides controls, clears selection, calls cancel)', async () => {
    const { calls, panel } = setup()
    await flush()
    cards()[0].click()
    document.getElementById('primitive-place-cancel').click()
    expect(placeBox().style.display).toBe('none')
    expect(panel.getSelected()).toBeNull()
    expect(calls.cancel).toBe(1)
  })

  it('exitPlacement() (called after a commit) hides controls + clears selection', async () => {
    const { panel } = setup()
    await flush()
    cards()[0].click()
    panel.exitPlacement()
    expect(placeBox().style.display).toBe('none')
    expect(panel.getSelected()).toBeNull()
    expect(cards()[0].classList.contains('is-selected')).toBe(false)
  })

  it('blocks placement onto a mismatched-lattice populated design (toast, no arm)', async () => {
    const calls = { enter: [] }
    const store = { getState: () => ({ currentDesign: { lattice_type: 'SQUARE', helices: [{}] } }) }
    const api = { listPrimitives: async () => [apiCardWithPlacement()] }  // HONEYCOMB primitive
    const panel = initPrimitiveLibrary({ store, api, placement: { enter: (s) => calls.enter.push(s) } })
    await flush()
    cards()[0].click()
    expect(calls.enter.length).toBe(0)       // not armed
    expect(placeBox().style.display).toBe('none')
    expect(panel.getSelected()).toBeNull()
  })
})

describe('initPrimitiveLibrary — collapse', () => {
  it('heading click toggles the body + arrow and persists', () => {
    initPrimitiveLibrary({})
    const heading = document.getElementById('primitives-panel-heading')
    const body = document.getElementById('primitives-panel-body')
    const arrow = document.getElementById('primitives-panel-arrow')

    expect(body.style.display).toBe('')
    heading.click()
    expect(body.style.display).toBe('none')
    expect(arrow.classList.contains('is-collapsed')).toBe(true)

    // A fresh init reads the persisted collapsed state back.
    initPrimitiveLibrary({})
    expect(document.getElementById('primitives-panel-body').style.display).toBe('none')
  })
})
