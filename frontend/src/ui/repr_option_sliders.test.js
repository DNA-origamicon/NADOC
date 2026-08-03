import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  reprSliderRowVisibility,
  hullMarginDefaultTick,
  initReprOptionSliders,
} from './repr_option_sliders.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { createMockStore } from '../test-helpers/mock_store.js'

// ── Pure cores ────────────────────────────────────────────────────────────────
describe('reprSliderRowVisibility', () => {
  it('full → bead-radius + slab-thickness rows', () => {
    expect(reprSliderRowVisibility('full')).toEqual({
      beadRadius: true, slabThickness: true,
      cylRadius: false, hullMargin: false,
      hullCurve: false, atomisticSliders: false, surfacePanel: false,
    })
  })
  it('beads → bead-radius row too, but no slab row (no slabs below full LOD)', () => {
    const v = reprSliderRowVisibility('beads')
    expect(v.beadRadius).toBe(true)
    expect(v.slabThickness).toBe(false)
  })
  it('no slab-opacity row — the control was removed', () => {
    expect(reprSliderRowVisibility('full')).not.toHaveProperty('slabOpacity')
  })
  it('cylinders → cyl-radius row only', () => {
    const v = reprSliderRowVisibility('cylinders')
    expect(v.cylRadius).toBe(true)
    expect(v.beadRadius).toBe(false)
  })
  it('hull-prism → both hull rows', () => {
    const v = reprSliderRowVisibility('hull-prism')
    expect(v.hullMargin).toBe(true)
    expect(v.hullCurve).toBe(true)
  })
  it('vdw / ballstick → atomistic sliders', () => {
    expect(reprSliderRowVisibility('vdw').atomisticSliders).toBe(true)
    expect(reprSliderRowVisibility('ballstick').atomisticSliders).toBe(true)
  })
  it('surface → surface panel', () => {
    expect(reprSliderRowVisibility('surface').surfacePanel).toBe(true)
  })
  it('unknown repr → all hidden', () => {
    expect(Object.values(reprSliderRowVisibility('???')).some(Boolean)).toBe(false)
  })
})

describe('hullMarginDefaultTick', () => {
  it('honeycomb → 8', () => expect(hullMarginDefaultTick('HONEYCOMB')).toBe(8))
  it('square → 7', () => expect(hullMarginDefaultTick('SQUARE')).toBe(7))
  it('undefined → 7 (square default)', () => expect(hullMarginDefaultTick(undefined)).toBe(7))
})

// ── Factory wiring ──────────────────────────────────────────────────────────
const SLIDER_IDS = {
  'sl-bead-radius': 'input', 'sv-bead-radius': 'span',
  'sl-slab-thickness': 'input', 'sv-slab-thickness': 'span',
  'sl-cyl-radius': 'input', 'sv-cyl-radius': 'span',
  'sl-hull-margin': 'input', 'sv-hull-margin': 'span',
  'sl-hull-curve': 'input', 'sv-hull-curve': 'span',
  'repr-bead-radius-row': 'div', 'repr-cyl-radius-row': 'div',
  'repr-slab-thickness-row': 'div',
  'repr-hull-margin-row': 'div', 'repr-hull-curve-row': 'div',
}

function makeDeps(overrides = {}) {
  const designRenderer = {
    setBeadRadius: vi.fn(), setCylinderRadius: vi.fn(),
    setSlabThickness: vi.fn(), setSlabOpacity: vi.fn(),
  }
  const jointRenderer = { setHullScanTick: vi.fn(), setHullCurveDetail: vi.fn() }
  return {
    store: createMockStore({ currentDesign: { lattice_type: 'SQUARE' } }),
    designRenderer,
    getJointRenderer: () => jointRenderer,
    getLodMode: () => 'full',
    setAtomisticSlidersVisible: vi.fn(),
    setSurfacePanelVisible: vi.fn(),
    _jointRenderer: jointRenderer,
    _designRenderer: designRenderer,
    ...overrides,
  }
}

function fireInput(el, value) {
  el.value = String(value)
  el.dispatchEvent(new window.Event('input'))
}

describe('initReprOptionSliders', () => {
  beforeEach(() => clearDom())

  it('returns updateForRepr and registers without DOM (all getElementById null)', () => {
    clearDom()
    const ctrl = initReprOptionSliders(makeDeps())
    expect(typeof ctrl.updateForRepr).toBe('function')
    expect(() => ctrl.updateForRepr('full')).not.toThrow()
  })

  it('bead slider writes label + setBeadRadius when LOD is bead-like', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps({ getLodMode: () => 'beads' })
    initReprOptionSliders(deps)
    fireInput(els['sl-bead-radius'], 0.25)
    expect(els['sv-bead-radius'].textContent).toBe('0.25')
    expect(deps._designRenderer.setBeadRadius).toHaveBeenCalledWith(0.25)
  })

  it('bead slider skips setBeadRadius when LOD is cylinders', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps({ getLodMode: () => 'cylinders' })
    initReprOptionSliders(deps)
    fireInput(els['sl-bead-radius'], 0.3)
    expect(els['sv-bead-radius'].textContent).toBe('0.30')   // label still updates
    expect(deps._designRenderer.setBeadRadius).not.toHaveBeenCalled()
  })

  it('slab-thickness slider writes label (nm) + setSlabThickness at full LOD', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps()   // full
    initReprOptionSliders(deps)
    fireInput(els['sl-slab-thickness'], 0.3)
    expect(els['sv-slab-thickness'].textContent).toBe('0.30')
    expect(deps._designRenderer.setSlabThickness).toHaveBeenCalledWith(0.3)
  })

  it('slab-thickness slider skips setSlabThickness below full LOD', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps({ getLodMode: () => 'beads' })
    initReprOptionSliders(deps)
    fireInput(els['sl-slab-thickness'], 0.2)
    expect(els['sv-slab-thickness'].textContent).toBe('0.20')   // label still updates
    expect(deps._designRenderer.setSlabThickness).not.toHaveBeenCalled()
  })

  // The slab-opacity control was removed (it collided with the other opacity
  // controls). Even if a stale element with the old id is present, nothing here
  // may drive designRenderer.setSlabOpacity.
  it('ignores a leftover slab-opacity slider entirely', () => {
    const els = mountIds({ ...SLIDER_IDS, 'sl-slab-opacity': 'input', 'sv-slab-opacity': 'span' })
    const deps = makeDeps()
    initReprOptionSliders(deps)
    fireInput(els['sl-slab-opacity'], 0.35)
    expect(deps._designRenderer.setSlabOpacity).not.toHaveBeenCalled()
    expect(els['sv-slab-opacity'].textContent).toBe('')
  })

  it('cyl slider sets cylinder radius only in cylinders LOD', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps({ getLodMode: () => 'cylinders' })
    initReprOptionSliders(deps)
    fireInput(els['sl-cyl-radius'], 1.5)
    expect(els['sv-cyl-radius'].textContent).toBe('1.50')
    expect(deps._designRenderer.setCylinderRadius).toHaveBeenCalledWith(1.5)
  })

  it('hull-margin slider → setHullScanTick (parsed as int)', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps()
    initReprOptionSliders(deps)
    fireInput(els['sl-hull-margin'], 9)
    expect(els['sv-hull-margin'].textContent).toBe('9')
    expect(deps._jointRenderer.setHullScanTick).toHaveBeenCalledWith(9)
  })

  it('hull-curve slider → setHullCurveDetail (float)', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps()
    initReprOptionSliders(deps)
    fireInput(els['sl-hull-curve'], 0.05)
    expect(els['sv-hull-curve'].textContent).toBe('0.05')
    expect(deps._jointRenderer.setHullCurveDetail).toHaveBeenCalledWith(0.05)
  })

  it('updateForRepr(full) shows bead + slab-thickness rows, hides the rest, calls visibility setters', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps()
    const ctrl = initReprOptionSliders(deps)
    ctrl.updateForRepr('full')
    expect(els['repr-bead-radius-row'].style.display).toBe('')
    expect(els['repr-slab-thickness-row'].style.display).toBe('')
    expect(els['repr-cyl-radius-row'].style.display).toBe('none')
    expect(els['repr-hull-margin-row'].style.display).toBe('none')
    expect(deps.setAtomisticSlidersVisible).toHaveBeenCalledWith(false)
    expect(deps.setSurfacePanelVisible).toHaveBeenCalledWith(false)
  })

  it('updateForRepr(hull-prism) reveals hull rows and seeds the margin from lattice (square→7)', () => {
    const els = mountIds(SLIDER_IDS)
    const deps = makeDeps()   // SQUARE
    const ctrl = initReprOptionSliders(deps)
    ctrl.updateForRepr('hull-prism')
    expect(els['repr-slab-thickness-row'].style.display).toBe('none')
    expect(els['repr-hull-margin-row'].style.display).toBe('')
    expect(els['repr-hull-curve-row'].style.display).toBe('')
    expect(els['sl-hull-margin'].value).toBe('7')
    expect(els['sv-hull-margin'].textContent).toBe('7')
  })

  it('updateForRepr(hull-prism) seeds 8 for honeycomb', () => {
    const els = mountIds(SLIDER_IDS)
    const store = createMockStore({ currentDesign: { lattice_type: 'HONEYCOMB' } })
    const ctrl = initReprOptionSliders(makeDeps({ store }))
    ctrl.updateForRepr('hull-prism')
    expect(els['sl-hull-margin'].value).toBe('8')
  })

  it('updateForRepr(vdw) → atomistic sliders shown, surface hidden', () => {
    mountIds(SLIDER_IDS)
    const deps = makeDeps()
    initReprOptionSliders(deps).updateForRepr('vdw')
    expect(deps.setAtomisticSlidersVisible).toHaveBeenCalledWith(true)
    expect(deps.setSurfacePanelVisible).toHaveBeenCalledWith(false)
  })

  it('updateForRepr(surface) → surface panel shown', () => {
    mountIds(SLIDER_IDS)
    const deps = makeDeps()
    initReprOptionSliders(deps).updateForRepr('surface')
    expect(deps.setSurfacePanelVisible).toHaveBeenCalledWith(true)
    expect(deps.setAtomisticSlidersVisible).toHaveBeenCalledWith(false)
  })
})
