import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initPhotoExpPanel, formatShadowStatus, shadowResolution, DUPLEX_NM } from './photo_exp_panel.js'

// ── Pure helpers ─────────────────────────────────────────────────────────────

describe('shadowResolution', () => {
  it('flags a map too coarse to resolve a duplex', () => {
    // The failure that made cast shadows look absent: once a texel is wider than
    // a helix, a thin arm cannot cast a readable shadow onto anything behind it.
    const r = shadowResolution(150, 128)
    expect(r.nmPerTexel).toBeCloseTo(2.34, 2)
    expect(r.duplexes).toBeLessThan(1)
    expect(r.ok).toBe(false)
  })

  it('passes once the map resolves a duplex at least twice over', () => {
    const r = shadowResolution(150, 2048)
    expect(r.nmPerTexel).toBeCloseTo(0.146, 3)
    expect(r.duplexes).toBeGreaterThan(13)
    expect(r.ok).toBe(true)
  })

  it('gets worse as the structure gets bigger at a fixed map size', () => {
    expect(shadowResolution(300, 2048).nmPerTexel)
      .toBeGreaterThan(shadowResolution(50, 2048).nmPerTexel)
  })

  it('measures against a B-DNA duplex', () => {
    expect(DUPLEX_NM).toBe(2.0)
  })

  it('degrades safely on a degenerate scene', () => {
    expect(shadowResolution(0, 2048).ok).toBe(false)
    expect(shadowResolution(150, 0).nmPerTexel).toBe(0)
  })
})

describe('formatShadowStatus', () => {
  it('reads "inactive" before the mode is entered', () => {
    expect(formatShadowStatus({ active: false })).toBe('inactive')
    expect(formatShadowStatus(null)).toBe('inactive')
  })

  it('reports the shadow, the pin and the fitted radius', () => {
    expect(formatShadowStatus({ active: true, keyShadow: true, pinned: true, radius: 148.2 }))
      .toBe('key shadow on · camera-pinned · scene radius 148 nm')
  })

  it('says so when the shadow is off', () => {
    expect(formatShadowStatus({ active: true, keyShadow: false, pinned: false, radius: 40 }))
      .toBe('key shadow off · scene radius 40.0 nm')
  })

  it('omits the radius when nothing has been fitted yet', () => {
    expect(formatShadowStatus({ active: true, keyShadow: true, pinned: true, radius: 0 }))
      .toBe('key shadow on · camera-pinned')
  })
})

// ── Panel wiring ─────────────────────────────────────────────────────────────

const PANEL_IDS = {
  'photoexp-exit-btn':               'button',
  'photoexp-status':                 'div',
  'photoexp-pin-lights':             'input',
  'photoexp-key-shadow':             'input',
  'photoexp-key-shadow-controls':    'div',
  'photoexp-key-shadow-mapsize':     'select',
  'photoexp-key-shadow-res':         'div',
  'photoexp-key-shadow-bias':        'input',
  'photoexp-key-shadow-bias-label':  'span',
  'photoexp-shadow-strength':        'input',
  'photoexp-shadow-strength-label':  'span',
  'photoexp-bg-type':                'select',
  'photoexp-bg-color':               'input',
}

function makeMode(overrides = {}) {
  const settings = {
    bgType: 'color', bgColor: '#0b0d10',
    pinLights: true, keyShadow: true, keyShadowMapSize: 2048,
    keyShadowBias: 1.0, shadowStrength: 1.0,
    ...overrides,
  }
  return {
    getSettings: () => ({ ...settings }),
    getStatus: () => ({ active: true, keyShadow: true, pinned: true, radius: 150, mapSize: 2048 }),
    setPinLights: vi.fn(), setKeyShadow: vi.fn(),
    setKeyShadowMapSize: vi.fn(), setKeyShadowBias: vi.fn(), setShadowStrength: vi.fn(),
    setBackground: vi.fn(),
  }
}

describe('initPhotoExpPanel', () => {
  let els, mode, panel, onExit

  beforeEach(() => {
    vi.useFakeTimers()
    els = mountIds(PANEL_IDS)
    for (const id of ['photoexp-pin-lights', 'photoexp-key-shadow']) els[id].type = 'checkbox'
    for (const id of ['photoexp-key-shadow-bias', 'photoexp-shadow-strength']) els[id].type = 'range'
    els['photoexp-bg-color'].type = 'color'
    for (const [id, values] of [
      ['photoexp-key-shadow-mapsize', ['1024', '2048', '4096', '8192']],
      ['photoexp-bg-type', ['color', 'transparent']],
    ]) {
      for (const v of values) {
        const o = document.createElement('option')
        o.value = v; o.textContent = v
        els[id].appendChild(o)
      }
    }
    mode = makeMode()
    onExit = vi.fn()
    panel = initPhotoExpPanel(mode, { onExit })
  })

  afterEach(() => { panel?.dispose(); vi.useRealTimers(); clearDom() })

  it('syncToState pushes the controller settings into every control', () => {
    panel.syncToState()
    expect(els['photoexp-pin-lights'].checked).toBe(true)
    expect(els['photoexp-key-shadow'].checked).toBe(true)
    expect(els['photoexp-key-shadow-mapsize'].value).toBe('2048')
    expect(els['photoexp-key-shadow-bias-label'].textContent).toBe('1.0×')
    expect(els['photoexp-shadow-strength-label'].textContent).toBe('1.00')
  })

  it('shows the live nm/texel resolution for the fitted scene', () => {
    panel.syncToState()
    // radius 150 nm at 2048 texels → 0.146 nm/texel, comfortably sub-duplex.
    expect(els['photoexp-key-shadow-res'].textContent).toContain('0.146 nm/texel')
    expect(els['photoexp-key-shadow-res'].textContent).not.toContain('COARSER')
  })

  it('warns in the UI when the map cannot resolve a duplex', () => {
    mode.getStatus = () => ({ active: true, keyShadow: true, pinned: true, radius: 70710 })
    panel.syncToState()
    expect(els['photoexp-key-shadow-res'].textContent).toContain('COARSER')
  })

  it('wires the shadow map size', () => {
    els['photoexp-key-shadow-mapsize'].value = '8192'
    els['photoexp-key-shadow-mapsize'].dispatchEvent(new Event('change'))
    expect(mode.setKeyShadowMapSize).toHaveBeenCalledWith(8192)
  })

  it('drives bias and shadow darkness live, with formatted read-outs', () => {
    els['photoexp-key-shadow-bias'].value = '2.5'
    els['photoexp-key-shadow-bias'].dispatchEvent(new Event('input'))
    expect(mode.setKeyShadowBias).toHaveBeenCalledWith(2.5)
    expect(els['photoexp-key-shadow-bias-label'].textContent).toBe('2.5×')

    els['photoexp-shadow-strength'].value = '0.4'
    els['photoexp-shadow-strength'].dispatchEvent(new Event('input'))
    expect(mode.setShadowStrength).toHaveBeenCalledWith(0.4)
    expect(els['photoexp-shadow-strength-label'].textContent).toBe('0.40')
  })

  it('hides the shadow sub-controls when the key shadow is switched off', () => {
    panel.syncToState()
    els['photoexp-key-shadow'].checked = false
    els['photoexp-key-shadow'].dispatchEvent(new Event('change'))
    expect(mode.setKeyShadow).toHaveBeenCalledWith(false)
    expect(els['photoexp-key-shadow-controls'].style.display).toBe('none')
  })

  it('wires the camera pin and background', () => {
    els['photoexp-pin-lights'].checked = false
    els['photoexp-pin-lights'].dispatchEvent(new Event('change'))
    expect(mode.setPinLights).toHaveBeenCalledWith(false)

    els['photoexp-bg-type'].value = 'transparent'
    els['photoexp-bg-type'].dispatchEvent(new Event('change'))
    expect(mode.setBackground).toHaveBeenCalledWith('transparent', undefined)
    expect(els['photoexp-bg-color'].disabled).toBe(true)

    els['photoexp-bg-color'].value = '#ff0000'
    els['photoexp-bg-color'].dispatchEvent(new Event('input'))
    expect(mode.setBackground).toHaveBeenLastCalledWith(undefined, '#ff0000')
  })

  it('the exit button calls back out to the tab controller', () => {
    els['photoexp-exit-btn'].dispatchEvent(new Event('click'))
    expect(onExit).toHaveBeenCalledTimes(1)
  })

  it('polls the status line while entered and stops on exit', () => {
    const spy = vi.spyOn(mode, 'getStatus')
    panel.onEnter()
    expect(els['photoexp-status'].textContent).toContain('key shadow on')
    const afterEnter = spy.mock.calls.length
    vi.advanceTimersByTime(1500)
    expect(spy.mock.calls.length).toBeGreaterThan(afterEnter)

    panel.onExit()
    const afterExit = spy.mock.calls.length
    vi.advanceTimersByTime(1500)
    expect(spy.mock.calls.length).toBe(afterExit)
  })
})
