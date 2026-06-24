import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initEfieldSetup } from './efield_setup.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// Spec-only contract: magnitude + direction + V/m + enable checkbox + gizmo.
// Anchors + run live elsewhere now (Anchors card + the panel's single Run button).
const IDS = {
  'efield-toggle': 'div', 'efield-arrow': 'span', 'efield-body': 'div',
  'efield-enable': 'input', 'efield-mag': 'input',
  'efield-dir-x': 'input', 'efield-dir-y': 'input', 'efield-dir-z': 'input',
  'efield-vpm-toggle': 'div', 'efield-vpm-arrow': 'span', 'efield-vpm-body': 'div',
  'efield-vpm': 'input', 'efield-qeff': 'input', 'efield-vpm-apply': 'button',
  'efield-ready': 'div',
}

function makeGizmo() {
  let vec = [0, 1, 0], active = false, onChange = null
  return {
    attach: vi.fn(() => { active = true }),
    detach: vi.fn(() => { active = false }),
    setVector: vi.fn((v) => { vec = v.slice() }),
    getVector: () => vec.slice(),
    setOnChange: (cb) => { onChange = cb },
    setColor: vi.fn(),
    isActive: () => active,
    _fireDrag: (v) => onChange?.(v),   // test hook: simulate a tip drag
  }
}

function setInput(el, value) {
  el.value = String(value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('initEfieldSetup', () => {
  let els, gizmo, api

  beforeEach(() => {
    els = mountIds(IDS)
    gizmo = makeGizmo()
    api = initEfieldSetup({ gizmo })
  })
  afterEach(() => clearDom())

  it('starts collapsed; opening attaches the gizmo', () => {
    expect(els['efield-body'].style.display).toBe('none')
    expect(gizmo.attach).not.toHaveBeenCalled()
    els['efield-toggle'].click()
    expect(els['efield-body'].style.display).toBe('')
    expect(gizmo.attach).toHaveBeenCalled()
    els['efield-toggle'].click()
    expect(els['efield-body'].style.display).toBe('none')
    expect(gizmo.detach).toHaveBeenCalled()
  })

  it('the enable checkbox flips the spec.enabled flag', () => {
    expect(api.getFieldSpec().enabled).toBe(false)
    expect(api.isEnabled()).toBe(false)
    els['efield-enable'].checked = true
    els['efield-enable'].dispatchEvent(new Event('change'))
    expect(api.getFieldSpec().enabled).toBe(true)
    // isEnabled additionally requires a positive magnitude.
    expect(api.isEnabled()).toBe(false)
    setInput(els['efield-mag'], 2)
    expect(api.isEnabled()).toBe(true)
  })

  it('magnitude input drives the gizmo and the field spec', () => {
    els['efield-toggle'].click()
    setInput(els['efield-mag'], 2.5)
    expect(api.getFieldSpec().field_pN).toBe(2.5)
    expect(gizmo.setVector).toHaveBeenCalled()
  })

  it('direction inputs feed a normalized dir into the spec', () => {
    setInput(els['efield-dir-x'], 0)
    setInput(els['efield-dir-y'], 0)
    setInput(els['efield-dir-z'], 5)
    const spec = api.getFieldSpec()
    expect(spec.dir[2]).toBeCloseTo(1)
  })

  it('V/m helper computes force-per-nucleotide into the pN field', () => {
    els['efield-toggle'].click()
    els['efield-qeff'].value = '0.25'
    els['efield-vpm'].value = '1000000'   // 1e6 V/m
    els['efield-vpm-apply'].click()
    expect(api.getFieldSpec().field_pN).toBeCloseTo(0.0400544, 5)
  })

  it('a gizmo drag updates the magnitude (length → pN)', () => {
    els['efield-toggle'].click()
    gizmo._fireDrag([0, 10, 0])   // 10 nm arrow → (10-2)/4 = 2 pN
    expect(api.getFieldSpec().field_pN).toBeCloseTo(2, 6)
    expect(els['efield-mag'].value).toBe('2')
  })

  it('ready line reflects enable + magnitude + anchor reminder', () => {
    els['efield-toggle'].click()
    expect(els['efield-ready'].textContent).toMatch(/tick "Apply"/i)
    els['efield-enable'].checked = true
    els['efield-enable'].dispatchEvent(new Event('change'))
    expect(els['efield-ready'].textContent).toMatch(/force per nucleotide/i)
    setInput(els['efield-mag'], 2)
    expect(els['efield-ready'].textContent).toMatch(/needs ≥1 anchor/i)
  })

  it('a strong magnitude warns it can disrupt the DNA', () => {
    els['efield-toggle'].click()
    els['efield-enable'].checked = true
    els['efield-enable'].dispatchEvent(new Event('change'))
    setInput(els['efield-mag'], 100)            // ≥ disrupt threshold
    expect(els['efield-ready'].textContent).toMatch(/disrupt/i)
    expect(gizmo.setColor).toHaveBeenCalled()
  })

  it('applyConfig repopulates magnitude + direction and enables the field', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] }, { open: true })
    expect(els['efield-enable'].checked).toBe(true)
    expect(parseFloat(els['efield-mag'].value)).toBe(5)
    expect(parseFloat(els['efield-dir-x'].value)).toBeCloseTo(1, 3)
    expect(parseFloat(els['efield-dir-y'].value)).toBeCloseTo(0, 3)
    const spec = api.getFieldSpec()
    expect(spec.enabled).toBe(true)
    expect(spec.field_pN).toBe(5)
    expect(spec.dir[0]).toBeCloseTo(1, 3)
    expect(api.isEnabled()).toBe(true)
    expect(gizmo.attach).toHaveBeenCalled()       // open:true reveals the arrow
  })

  it('applyConfig shows the arrow for a field job even with the card collapsed', () => {
    expect(els['efield-body'].style.display).toBe('none')   // card starts collapsed
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] })          // no { open: true }
    expect(els['efield-body'].style.display).toBe('none')     // card stays collapsed
    expect(gizmo.attach).toHaveBeenCalled()                   // …but the arrow shows
    expect(gizmo.isActive()).toBe(true)
  })

  it('applyConfig(null) hides the arrow when the card is collapsed', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] })   // arrow on, card collapsed
    expect(gizmo.isActive()).toBe(true)
    api.applyConfig(null)                               // a non-field job selected
    expect(gizmo.detach).toHaveBeenCalled()
    expect(gizmo.isActive()).toBe(false)
  })

  it('leaving the Dynamics tab drops the job-selected arrow', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] })   // arrow on via a field job
    expect(gizmo.isActive()).toBe(true)
    window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', { detail: { activeTab: 'design' } }))
    expect(gizmo.isActive()).toBe(false)
  })

  it('applyConfig(null) turns the field off', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] }, { open: true })
    api.applyConfig(null)
    expect(els['efield-enable'].checked).toBe(false)
    expect(api.isEnabled()).toBe(false)
    expect(api.getFieldSpec().enabled).toBe(false)
  })
})

// Sibling describe (its own setup — no flat `api` bound to the same DOM) so the
// base-count scaling is the only handler on the gizmo/inputs.
describe('initEfieldSetup — base-count-aware gizmo scaling', () => {
  let els, gizmo
  beforeEach(() => { els = mountIds(IDS); gizmo = makeGizmo() })
  afterEach(() => clearDom())

  it('arrow encodes total force: on a 10× design, 1 pN/nt is a 10× longer arrow', () => {
    initEfieldSetup({ gizmo, getBaseCount: () => 10000 })   // 10× the 1000-nt reference
    setInput(els['efield-mag'], '1')                        // 1 pN/nt
    const v = gizmo.setVector.mock.calls.at(-1)[0]
    // nm/pN = 4 × 10000/1000 = 40 → arrow = MIN(2) + 40·1 = 42 nm
    expect(Math.hypot(...v)).toBeCloseTo(42, 6)
  })

  it('a fixed drag length yields a small per-nt force on a big design', () => {
    const api = initEfieldSetup({ gizmo, getBaseCount: () => 10000 })
    els['efield-toggle'].click()                            // open → gizmo active
    gizmo._fireDrag([0, 40, 0])                             // 40 nm arrow drag
    // pN = (40 − 2) / 40 ≈ 0.95 (vs 9.5 under the flat structure-blind mapping)
    expect(api.getFieldSpec().field_pN).toBeCloseTo(0.95, 6)
  })

  it('no base count → flat behaviour unchanged (1 pN/nt = 6 nm arrow)', () => {
    initEfieldSetup({ gizmo })                              // getBaseCount omitted
    setInput(els['efield-mag'], '1')
    const v = gizmo.setVector.mock.calls.at(-1)[0]
    expect(Math.hypot(...v)).toBeCloseTo(6, 6)              // 2 + 4·1
  })
})
