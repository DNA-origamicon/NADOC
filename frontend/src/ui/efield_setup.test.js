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
})
