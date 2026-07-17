import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { initOxdnaFloorSetup } from './oxdna_floor_setup.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

const IDS = {
  'oxdna-floor-toggle': 'div', 'oxdna-floor-arrow': 'span', 'oxdna-floor-body': 'div',
  'oxdna-floor-enable': 'input', 'oxdna-floor-controls': 'div',
  'oxdna-floor-axis': 'select', 'oxdna-floor-offset': 'input',
  'oxdna-floor-offset-label': 'span', 'oxdna-floor-stiff': 'input',
  'oxdna-floor-ready': 'div',
}

function mountFloor() {
  const els = mountIds(IDS)
  // Axis options the module reads (default -y).
  for (const [v, label] of [['-y', '−Y (below)'], ['+y', '+Y (above)'], ['-x', '−X']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = label
    els['oxdna-floor-axis'].appendChild(o)
  }
  els['oxdna-floor-stiff'].value = '5'
  els['oxdna-floor-offset'].value = '0'
  return els
}

describe('initOxdnaFloorSetup', () => {
  let els, api
  beforeEach(() => { els = mountFloor(); api = initOxdnaFloorSetup({}) })
  afterEach(() => clearDom())

  it('starts collapsed; the header toggles the body', () => {
    expect(els['oxdna-floor-body'].style.display).toBe('none')
    els['oxdna-floor-toggle'].click()
    expect(els['oxdna-floor-body'].style.display).toBe('')
  })

  it('the enable checkbox reveals the controls and flips spec.enabled', () => {
    els['oxdna-floor-toggle'].click()
    expect(els['oxdna-floor-controls'].style.display).toBe('none')
    expect(api.getSurfaceSpec().enabled).toBe(false)
    els['oxdna-floor-enable'].checked = true
    els['oxdna-floor-enable'].dispatchEvent(new Event('change'))
    expect(els['oxdna-floor-controls'].style.display).toBe('flex')
    expect(api.getSurfaceSpec().enabled).toBe(true)
    expect(api.isEnabled()).toBe(true)
  })

  it('the spec carries the chosen side normal, offset, and stiffness', () => {
    els['oxdna-floor-enable'].checked = true
    els['oxdna-floor-enable'].dispatchEvent(new Event('change'))
    els['oxdna-floor-axis'].value = '+y'
    els['oxdna-floor-axis'].dispatchEvent(new Event('change'))
    els['oxdna-floor-offset'].value = '2.5'
    els['oxdna-floor-offset'].dispatchEvent(new Event('input'))
    els['oxdna-floor-stiff'].value = '8'
    els['oxdna-floor-stiff'].dispatchEvent(new Event('input'))
    const spec = api.getSurfaceSpec()
    expect(spec.dir).toEqual([0, -1, 0])     // +y side → normal points down
    expect(spec.offsetNm).toBe(2.5)
    expect(spec.stiff).toBe(8)
    expect(els['oxdna-floor-offset-label'].textContent).toBe('2.5 nm')
  })

  it('drives the shared surface grid on enable / axis / offset change', () => {
    const setSurfaceGrid = vi.fn()
    const a = initOxdnaFloorSetup({ setSurfaceGrid })
    els['oxdna-floor-enable'].checked = true
    els['oxdna-floor-enable'].dispatchEvent(new Event('change'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: true, axis: '-y', offsetNm: 0 }))
    els['oxdna-floor-offset'].value = '4'
    els['oxdna-floor-offset'].dispatchEvent(new Event('input'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: true, positionNm: 4 }))
    expect(a.isEnabled()).toBe(true)
  })

  it('applyConfig repopulates the card from a stored surface spec', () => {
    api.applyConfig({ dir: [0, -1, 0], offset_nm: 2.5, stiff: 8 })
    expect(els['oxdna-floor-enable'].checked).toBe(true)
    expect(els['oxdna-floor-axis'].value).toBe('+y')   // normal points down → +y side
    expect(els['oxdna-floor-offset'].value).toBe('2.5')
    expect(els['oxdna-floor-offset-label'].textContent).toBe('2.5 nm')
    expect(els['oxdna-floor-stiff'].value).toBe('8')
    const spec = api.getSurfaceSpec()
    expect(spec.enabled).toBe(true)
    expect(spec.dir).toEqual([0, -1, 0])
  })

  it('forwards the persisted physical plane coordinate and edits it absolutely', () => {
    const setSurfaceGrid = vi.fn()
    const a = initOxdnaFloorSetup({ setSurfaceGrid })
    a.applyConfig({ dir: [0, 1, 0], offset_nm: 2, stiff: 5, position_nm: -7.5 })
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(expect.objectContaining({ positionNm: -7.5 }))
    els['oxdna-floor-offset'].value = '3'
    els['oxdna-floor-offset'].dispatchEvent(new Event('input'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(expect.objectContaining({ positionNm: 3 }))
  })

  it('changing side snaps the absolute offset to structure contact', () => {
    const setSurfaceGrid = vi.fn()
    const bounds = { min: [-8, -3, -5], max: [12, 7, 9] }
    const a = initOxdnaFloorSetup({ setSurfaceGrid, getStructureBounds: () => bounds })
    els['oxdna-floor-enable'].checked = true
    els['oxdna-floor-enable'].dispatchEvent(new Event('change'))
    els['oxdna-floor-axis'].value = '+y'
    els['oxdna-floor-axis'].dispatchEvent(new Event('change'))
    expect(els['oxdna-floor-offset'].value).toBe('7')
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(expect.objectContaining({ positionNm: 7 }))
    expect(a.getSurfaceSpec().offsetNm).toBe(0)
  })

  it('accepts an exact manually entered absolute position', () => {
    const setSurfaceGrid = vi.fn()
    const bounds = { min: [-8, -3, -5], max: [12, 7, 9] }
    const a = initOxdnaFloorSetup({ setSurfaceGrid, getStructureBounds: () => bounds })
    els['oxdna-floor-enable'].checked = true
    els['oxdna-floor-enable'].dispatchEvent(new Event('change'))
    els['oxdna-floor-offset'].value = '-4.37'
    els['oxdna-floor-offset'].dispatchEvent(new Event('input'))
    expect(setSurfaceGrid).toHaveBeenLastCalledWith(expect.objectContaining({ positionNm: -4.37 }))
    expect(a.getSurfaceSpec().offsetNm).toBeCloseTo(1.37)
    expect(a.getSurfaceSpec().positionNm).toBe(-4.37)
  })

  it('applyConfig(null) turns the surface off', () => {
    api.applyConfig({ dir: [0, 1, 0], offset_nm: 1, stiff: 5 })
    api.applyConfig(null)
    expect(els['oxdna-floor-enable'].checked).toBe(false)
    expect(api.isEnabled()).toBe(false)
    expect(api.getSurfaceSpec().enabled).toBe(false)
  })
})

// M8: the card mounts on a sibling engine's DOM ids (mrDNA) with identical behaviour.
describe('initOxdnaFloorSetup — custom ids bag (mrDNA mount)', () => {
  const MR_IDS = {
    toggle: 'mrdna-surface-toggle', arrow: 'mrdna-surface-arrow', body: 'mrdna-surface-body',
    enable: 'mrdna-surface-enable', controls: 'mrdna-surface-controls', axis: 'mrdna-surface-axis',
    offset: 'mrdna-surface-offset', offsetLabel: 'mrdna-surface-offset-label',
    stiff: 'mrdna-surface-stiff', ready: 'mrdna-surface-ready',
  }
  afterEach(() => clearDom())

  it('reads/writes the mrDNA ids and emits the same {dir,offsetNm,stiff} spec', () => {
    const els = mountIds({
      'mrdna-surface-toggle': 'div', 'mrdna-surface-arrow': 'span', 'mrdna-surface-body': 'div',
      'mrdna-surface-enable': 'input', 'mrdna-surface-controls': 'div',
      'mrdna-surface-axis': 'select', 'mrdna-surface-offset': 'input',
      'mrdna-surface-offset-label': 'span', 'mrdna-surface-stiff': 'input',
      'mrdna-surface-ready': 'div',
    })
    for (const [v, label] of [['-y', '−Y'], ['+y', '+Y'], ['-x', '−X']]) {
      const o = document.createElement('option'); o.value = v; o.textContent = label
      els['mrdna-surface-axis'].appendChild(o)
    }
    els['mrdna-surface-stiff'].value = '5'; els['mrdna-surface-offset'].value = '0'
    const api = initOxdnaFloorSetup({ ids: MR_IDS })
    els['mrdna-surface-enable'].checked = true
    els['mrdna-surface-enable'].dispatchEvent(new Event('change'))
    els['mrdna-surface-axis'].value = '+y'
    els['mrdna-surface-axis'].dispatchEvent(new Event('change'))
    els['mrdna-surface-offset'].value = '3'
    els['mrdna-surface-offset'].dispatchEvent(new Event('input'))
    const spec = api.getSurfaceSpec()
    expect(spec.enabled).toBe(true)
    expect(spec.dir).toEqual([0, -1, 0])
    expect(spec.offsetNm).toBe(3)
    expect(els['mrdna-surface-offset-label'].textContent).toBe('3.0 nm')
  })

  it('does not touch the oxDNA ids when mounted with a custom bag', () => {
    mountIds({
      'mrdna-surface-toggle': 'div', 'mrdna-surface-body': 'div', 'mrdna-surface-enable': 'input',
      'oxdna-floor-toggle': 'div', 'oxdna-floor-body': 'div', 'oxdna-floor-enable': 'input',
    })
    const api = initOxdnaFloorSetup({ ids: MR_IDS })
    // The oxDNA enable checkbox must be untouched by the mrDNA-mounted card.
    document.getElementById('mrdna-surface-toggle').click()
    expect(document.getElementById('oxdna-floor-body').style.display).toBe('')  // default (never set to none)
    expect(api.isEnabled()).toBe(false)
  })
})
