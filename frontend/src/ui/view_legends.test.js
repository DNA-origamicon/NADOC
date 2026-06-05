/**
 * Unit tests for the View legends controller (Loop/Skip + MD Segmentation).
 *
 *   initViewLegends — factory wiring: builds two fixed-position legend overlays,
 *   wires their View-menu toggle handlers, and exposes reset(). Pure DOM/state, no
 *   pure core. `computeSegments` is mocked so the MD-detail line is deterministic.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// computeSegments is imported directly by the module — mock it so the detail
// readout is deterministic without the real segmentation pipeline.
vi.mock('../scene/md_segmentation_overlay.js', () => ({
  computeSegments: vi.fn(() => ({
    windows: [
      { category: 'periodic' },
      { category: 'periodic' },
      { category: 'minor' },
    ],
    modal: 7,
  })),
}))

import { initViewLegends } from './view_legends.js'

const mountMenu = () => mountIds({
  'menu-view-loop-skip': 'button',
  'menu-view-md-segmentation': 'button',
})

function makeLoopSkip(initialVisible = false) {
  let visible = initialVisible
  return {
    isVisible: vi.fn(() => visible),
    setVisible: vi.fn((v) => { visible = v }),
    rebuild: vi.fn(),
  }
}

function makeMdSeg(toggleResult = true) {
  return {
    toggle: vi.fn(() => toggleResult),
    hide: vi.fn(),
  }
}

function makeDeps(overrides = {}) {
  return {
    store: createMockStore({ currentDesign: { strands: [] }, currentGeometry: [], currentHelixAxes: [] }),
    loopSkipHighlight: makeLoopSkip(),
    mdSegmentation: makeMdSeg(),
    setMenuToggle: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => { clearDom(); vi.clearAllMocks() })

describe('initViewLegends — construction', () => {
  it('appends two hidden legend overlays to the body', () => {
    mountMenu()
    const { loopSkipLegend, mdSegLegend } = initViewLegends(makeDeps())
    expect(loopSkipLegend.parentElement).toBe(document.body)
    expect(mdSegLegend.parentElement).toBe(document.body)
    expect(loopSkipLegend.style.display).toBe('none')
    expect(mdSegLegend.style.display).toBe('none')
    // distinct content so the two legends are not confused
    expect(loopSkipLegend.innerHTML).toContain('LOOP / SKIP')
    expect(mdSegLegend.innerHTML).toContain('MD SEGMENTATION')
    // the MD legend carries the detail slot the handler writes into
    expect(mdSegLegend.querySelector('#md-seg-legend-detail')).toBeTruthy()
  })

  it('does not throw when the menu items are absent (welcome screen)', () => {
    // no mountMenu() — getElementById returns null, optional-chained
    expect(() => initViewLegends(makeDeps())).not.toThrow()
  })
})

describe('Loop/Skip toggle', () => {
  it('on: shows legend, flips highlight visible, sets pill, rebuilds with store geometry', () => {
    mountMenu()
    const deps = makeDeps()
    const { loopSkipLegend } = initViewLegends(deps)
    document.getElementById('menu-view-loop-skip').click()
    expect(deps.loopSkipHighlight.setVisible).toHaveBeenCalledWith(true)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-loop-skip', true)
    expect(loopSkipLegend.style.display).toBe('block')
    expect(deps.loopSkipHighlight.rebuild).toHaveBeenCalledWith(
      deps.store.getState().currentDesign,
      deps.store.getState().currentGeometry,
      deps.store.getState().currentHelixAxes,
    )
  })

  it('off: hides legend, flips highlight off, sets pill, does NOT rebuild', () => {
    mountMenu()
    const deps = makeDeps({ loopSkipHighlight: makeLoopSkip(true) })
    const { loopSkipLegend } = initViewLegends(deps)
    document.getElementById('menu-view-loop-skip').click()
    expect(deps.loopSkipHighlight.setVisible).toHaveBeenCalledWith(false)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-loop-skip', false)
    expect(loopSkipLegend.style.display).toBe('none')
    expect(deps.loopSkipHighlight.rebuild).not.toHaveBeenCalled()
  })
})

describe('MD Segmentation toggle', () => {
  it('on: shows legend, sets pill, writes the periodic-windows detail line', () => {
    mountMenu()
    const deps = makeDeps({ mdSegmentation: makeMdSeg(true) })
    const { mdSegLegend } = initViewLegends(deps)
    document.getElementById('menu-view-md-segmentation').click()
    expect(deps.mdSegmentation.toggle).toHaveBeenCalledWith(deps.store.getState().currentDesign)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-md-segmentation', true)
    expect(mdSegLegend.style.display).toBe('block')
    // mocked computeSegments → 2 periodic / 3 windows, modal 7
    expect(mdSegLegend.querySelector('#md-seg-legend-detail').textContent)
      .toBe('2 / 3 windows periodic  ·  modal = 7 xovers')
  })

  it('off: hides legend, sets pill, leaves the detail line untouched', () => {
    mountMenu()
    const deps = makeDeps({ mdSegmentation: makeMdSeg(false) })
    const { mdSegLegend } = initViewLegends(deps)
    document.getElementById('menu-view-md-segmentation').click()
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-md-segmentation', false)
    expect(mdSegLegend.style.display).toBe('none')
    expect(mdSegLegend.querySelector('#md-seg-legend-detail').textContent).toBe('')
  })

  it('on with no current design: shows legend but skips the detail computation', () => {
    mountMenu()
    const deps = makeDeps({
      store: createMockStore({ currentDesign: null }),
      mdSegmentation: makeMdSeg(true),
    })
    const { mdSegLegend } = initViewLegends(deps)
    document.getElementById('menu-view-md-segmentation').click()
    expect(mdSegLegend.style.display).toBe('block')
    expect(mdSegLegend.querySelector('#md-seg-legend-detail').textContent).toBe('')
  })
})

describe('reset()', () => {
  it('hides both legends, clears both pills, and hides the MD overlay', () => {
    mountMenu()
    const deps = makeDeps({ loopSkipHighlight: makeLoopSkip(false), mdSegmentation: makeMdSeg(true) })
    const api = initViewLegends(deps)
    // open both first (loop-skip starts hidden → first click shows it)
    document.getElementById('menu-view-loop-skip').click()
    document.getElementById('menu-view-md-segmentation').click()
    expect(api.loopSkipLegend.style.display).toBe('block')
    expect(api.mdSegLegend.style.display).toBe('block')

    deps.setMenuToggle.mockClear()
    api.reset()

    expect(api.loopSkipLegend.style.display).toBe('none')
    expect(api.mdSegLegend.style.display).toBe('none')
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-loop-skip', false)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-md-segmentation', false)
    expect(deps.mdSegmentation.hide).toHaveBeenCalled()
  })
})
