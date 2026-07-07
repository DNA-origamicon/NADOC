import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { initCandoEfieldSetup } from './cando_efield_setup.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// Numeric mimic of the oxDNA field card (no gizmo — the CanDo panel shares the Dynamics
// tab with oxDNA, which owns the one in-scene arrow).  Same {field_pN, dir} spec + V/m math.
const IDS = {
  'cando-efield-toggle': 'div', 'cando-efield-arrow': 'span', 'cando-efield-body': 'div',
  'cando-efield-enable': 'input', 'cando-efield-mag': 'input',
  'cando-efield-dir-x': 'input', 'cando-efield-dir-y': 'input', 'cando-efield-dir-z': 'input',
  'cando-efield-vpm-toggle': 'div', 'cando-efield-vpm-arrow': 'span', 'cando-efield-vpm-body': 'div',
  'cando-efield-vpm': 'input', 'cando-efield-qeff': 'input', 'cando-efield-vpm-apply': 'button',
  'cando-efield-ready': 'div',
}

function setInput(el, value) {
  el.value = String(value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('initCandoEfieldSetup', () => {
  let els, api

  beforeEach(() => {
    els = mountIds(IDS)
    api = initCandoEfieldSetup({})
  })
  afterEach(() => clearDom())

  it('missing DOM → inert no-op factory', () => {
    clearDom()
    const inert = initCandoEfieldSetup({})
    expect(inert.getFieldSpec()).toEqual({ field_pN: 0, dir: [0, 1, 0], enabled: false })
    expect(inert.isEnabled()).toBe(false)
  })

  it('starts collapsed; the header toggles the body', () => {
    expect(els['cando-efield-body'].style.display).toBe('none')
    els['cando-efield-toggle'].click()
    expect(els['cando-efield-body'].style.display).toBe('')
    els['cando-efield-toggle'].click()
    expect(els['cando-efield-body'].style.display).toBe('none')
  })

  it('the enable checkbox flips spec.enabled; isEnabled also needs a positive magnitude', () => {
    expect(api.getFieldSpec().enabled).toBe(false)
    els['cando-efield-enable'].checked = true
    els['cando-efield-enable'].dispatchEvent(new Event('change'))
    expect(api.getFieldSpec().enabled).toBe(true)
    expect(api.isEnabled()).toBe(false)          // no magnitude yet
    setInput(els['cando-efield-mag'], 2)
    expect(api.isEnabled()).toBe(true)
  })

  it('magnitude input drives field_pN', () => {
    setInput(els['cando-efield-mag'], 2.5)
    expect(api.getFieldSpec().field_pN).toBe(2.5)
  })

  it('direction inputs feed a normalized dir into the spec', () => {
    setInput(els['cando-efield-dir-x'], 0)
    setInput(els['cando-efield-dir-y'], 0)
    setInput(els['cando-efield-dir-z'], 5)
    const spec = api.getFieldSpec()
    expect(spec.dir[2]).toBeCloseTo(1)
    expect(Math.hypot(...spec.dir)).toBeCloseTo(1)
  })

  it('V/m helper computes force-per-nucleotide into the pN field (same math as oxDNA)', () => {
    els['cando-efield-toggle'].click()
    els['cando-efield-qeff'].value = '0.25'
    els['cando-efield-vpm'].value = '1000000'   // 1e6 V/m
    els['cando-efield-vpm-apply'].click()
    expect(api.getFieldSpec().field_pN).toBeCloseTo(0.0400544, 5)
  })

  it('ready line reflects enable + magnitude + anchor reminder', () => {
    els['cando-efield-toggle'].click()
    expect(els['cando-efield-ready'].textContent).toMatch(/tick "Apply"/i)
    els['cando-efield-enable'].checked = true
    els['cando-efield-enable'].dispatchEvent(new Event('change'))
    expect(els['cando-efield-ready'].textContent).toMatch(/force per nucleotide/i)
    setInput(els['cando-efield-mag'], 2)
    expect(els['cando-efield-ready'].textContent).toMatch(/needs ≥1 anchor/i)
  })

  it('applyConfig repopulates magnitude + direction and enables the field', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] }, { open: true })
    expect(els['cando-efield-enable'].checked).toBe(true)
    expect(parseFloat(els['cando-efield-mag'].value)).toBe(5)
    expect(parseFloat(els['cando-efield-dir-x'].value)).toBeCloseTo(1, 3)
    const spec = api.getFieldSpec()
    expect(spec.enabled).toBe(true)
    expect(spec.field_pN).toBe(5)
    expect(spec.dir[0]).toBeCloseTo(1, 3)
    expect(api.isEnabled()).toBe(true)
  })

  it('applyConfig(null) turns the field off', () => {
    api.applyConfig({ field_pN: 5, dir: [1, 0, 0] }, { open: true })
    api.applyConfig(null)
    expect(els['cando-efield-enable'].checked).toBe(false)
    expect(api.isEnabled()).toBe(false)
    expect(api.getFieldSpec().enabled).toBe(false)
  })
})
