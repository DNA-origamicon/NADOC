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
      expect.objectContaining({ enabled: true, offsetNm: 4 }))
    expect(a.isEnabled()).toBe(true)
  })
})
