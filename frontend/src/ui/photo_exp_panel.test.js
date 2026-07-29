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
  'photoexp-key-intensity':          'input',
  'photoexp-key-intensity-label':    'span',
  'photoexp-fill-intensity':         'input',
  'photoexp-fill-intensity-label':   'span',
  'photoexp-ambient-intensity':      'input',
  'photoexp-ambient-intensity-label':'span',
  'photoexp-max-contrast':           'button',
  'photoexp-shadow-depth':           'div',
  'photoexp-key-azimuth':            'input',
  'photoexp-key-azimuth-label':      'span',
  'photoexp-key-elevation':          'input',
  'photoexp-key-elevation-label':    'span',
  'photoexp-key-dir':                'div',
  'photoexp-key-dir-reset':          'button',
  'photoexp-lighting-heading':       'div',
  'photoexp-lighting-body':          'div',
  'photoexp-lighting-arrow':         'span',
  'photoexp-outline':                'input',
  'photoexp-outline-controls':       'div',
  'photoexp-outline-color':          'input',
  'photoexp-outline-strength':       'input',
  'photoexp-outline-strength-label': 'span',
  'photoexp-outline-thickness':      'input',
  'photoexp-outline-thickness-label':'span',
  'photoexp-outline-jump':           'input',
  'photoexp-outline-jump-label':     'span',
  'photoexp-depthcue':               'input',
  'photoexp-depthcue-controls':      'div',
  'photoexp-depthcue-color':         'input',
  'photoexp-depthcue-strength':      'input',
  'photoexp-depthcue-strength-label':'span',
  'photoexp-figure-heading':         'div',
  'photoexp-figure-body':            'div',
  'photoexp-figure-arrow':           'span',
  'photoexp-mat-full':               'select',
  'photoexp-mat-cylinders':          'select',
  'photoexp-mat-surface':            'select',
  'photoexp-mat-atomistic':          'select',
  'photoexp-materials-heading':      'div',
  'photoexp-materials-body':         'div',
  'photoexp-materials-arrow':        'span',
  'photoexp-bg-heading':             'div',
  'photoexp-bg-body':                'div',
  'photoexp-bg-arrow':               'span',
  'photoexp-fov':                    'input',
  'photoexp-fov-label':              'span',
  'photoexp-parallel':               'input',
  'photoexp-res-preset':             'select',
  'photoexp-res-w':                  'input',
  'photoexp-res-h':                  'input',
  'photoexp-export-note':            'div',
  'photoexp-export-btn':             'button',
  'photoexp-camera-heading':         'div',
  'photoexp-camera-body':            'div',
  'photoexp-camera-arrow':           'span',
  'photoexp-export-heading':         'div',
  'photoexp-export-body':            'div',
  'photoexp-export-arrow':           'span',
  'photoexp-bg-type':                'select',
  'photoexp-bg-color':               'input',
}

function makeMode(overrides = {}) {
  const settings = {
    bgType: 'color', bgColor: '#0b0d10',
    pinLights: true, keyShadow: true, keyShadowMapSize: 2048,
    keyShadowBias: 1.0, shadowStrength: 1.0,
    keyAzimuth: 135, keyElevation: 35.264,
    keyIntensity: 2.0, fillIntensity: 0, ambientIntensity: 0.15,
    full: 'flat', cylinders: 'flat', surface: 'flat', atomistic: 'cpk-flat',
    outline: false, outlineColor: '#1b1f24', outlineStrength: 1.0,
    outlineThickness: 1.4, outlineDepthSensitivity: 0.35, outlineCreaseSensitivity: 0.85,
    silhouette: 'chimerax', outlineDepthJump: 0.03,
    depthCue: false, depthCueColor: '#ffffff', depthCueStrength: 0.35,
    parallel: false, fov: 55, exportWidth: 4200, exportHeight: 2970,
    ...overrides,
  }
  return {
    getSettings: () => ({ ...settings }),
    getStatus: () => ({ active: true, keyShadow: true, pinned: true, radius: 150, mapSize: 2048 }),
    setPinLights: vi.fn(), setKeyShadow: vi.fn(),
    setKeyAzimuth: vi.fn(), setKeyElevation: vi.fn(), resetKeyDirection: vi.fn(),
    setKeyShadowMapSize: vi.fn(), setKeyShadowBias: vi.fn(), setShadowStrength: vi.fn(),
    setKeyIntensity: vi.fn(), setFillIntensity: vi.fn(), setAmbientIntensity: vi.fn(),
    setBackground: vi.fn(), setMaterialPreset: vi.fn(),
    setOutline: vi.fn(), setOutlineColor: vi.fn(), setOutlineStrength: vi.fn(),
    setOutlineThickness: vi.fn(), setOutlineSensitivity: vi.fn(), setOutlineDepthJump: vi.fn(),
    setDepthCue: vi.fn(), setDepthCueColor: vi.fn(), setDepthCueStrength: vi.fn(),
    setFOV: vi.fn(), setParallel: vi.fn(), setExportSize: vi.fn(),
    renderToBlob: vi.fn(async () => null),
  }
}

describe('initPhotoExpPanel', () => {
  let els, mode, panel, onExit

  beforeEach(() => {
    vi.useFakeTimers()
    els = mountIds(PANEL_IDS)
    for (const id of ['photoexp-pin-lights', 'photoexp-key-shadow',
                      'photoexp-outline', 'photoexp-depthcue']) els[id].type = 'checkbox'
    for (const id of ['photoexp-outline-color', 'photoexp-depthcue-color']) els[id].type = 'color'
    for (const id of ['photoexp-key-shadow-bias', 'photoexp-shadow-strength',
                      'photoexp-fov']) els[id].type = 'range'
    for (const id of ['photoexp-res-w', 'photoexp-res-h']) els[id].type = 'number'
    els['photoexp-parallel'].type = 'checkbox'
    els['photoexp-bg-color'].type = 'color'
    for (const [id, values] of [
      ['photoexp-key-shadow-mapsize', ['1024', '2048', '4096', '8192']],
      ['photoexp-res-preset', ['screen', 'x2', 'p300', 'p600', 'custom']],
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

  it('describes where the light is, and how far off the camera axis', () => {
    panel.syncToState()
    expect(els['photoexp-key-dir'].textContent).toContain('upper-left')
    expect(els['photoexp-key-dir'].textContent).toContain('55° off the camera axis')
  })

  it('the Reset direction button defers to the mode, which owns the defaults', () => {
    els['photoexp-key-dir-reset'].dispatchEvent(new Event('click'))
    expect(mode.resetKeyDirection).toHaveBeenCalledTimes(1)
  })

  it('wires the outline controls and hides them when it is off', () => {
    panel.syncToState()
    expect(els['photoexp-outline-controls'].style.display).toBe('none')  // off by default

    els['photoexp-outline'].checked = true
    els['photoexp-outline'].dispatchEvent(new Event('change'))
    expect(mode.setOutline).toHaveBeenCalledWith(true)
    expect(els['photoexp-outline-controls'].style.display).toBe('flex')

    els['photoexp-outline-thickness'].value = '2.5'
    els['photoexp-outline-thickness'].dispatchEvent(new Event('input'))
    expect(mode.setOutlineThickness).toHaveBeenCalledWith(2.5)
    expect(els['photoexp-outline-thickness-label'].textContent).toBe('2.5')

    // ChimeraX's depth_jump replaces the old depth/crease pair: the mimic is
    // depth-only, so there is no crease control to wire at all.
    els['photoexp-outline-jump'].value = '0.075'
    els['photoexp-outline-jump'].dispatchEvent(new Event('input'))
    expect(mode.setOutlineDepthJump).toHaveBeenCalledWith(0.075)
    expect(els['photoexp-outline-jump-label'].textContent).toBe('0.075')
  })

  it('wires the depth-cue controls', () => {
    panel.syncToState()
    els['photoexp-depthcue'].checked = true
    els['photoexp-depthcue'].dispatchEvent(new Event('change'))
    expect(mode.setDepthCue).toHaveBeenCalledWith(true)
    expect(els['photoexp-depthcue-controls'].style.display).toBe('flex')

    els['photoexp-depthcue-strength'].value = '0.6'
    els['photoexp-depthcue-strength'].dispatchEvent(new Event('input'))
    expect(mode.setDepthCueStrength).toHaveBeenCalledWith(0.6)

    els['photoexp-depthcue-color'].value = '#00ff00'
    els['photoexp-depthcue-color'].dispatchEvent(new Event('input'))
    expect(mode.setDepthCueColor).toHaveBeenCalledWith('#00ff00')
  })

  it('builds the material dropdowns from PRESET_LABELS', () => {
    // Driven off the shared preset table, so adding a preset in
    // material_presets.js shows up here with no markup change.
    const opts = id => [...els[id].querySelectorAll('option')].map(o => o.value)
    expect(opts('photoexp-mat-full')).toEqual(['flat', 'matte', 'glossy', 'metallic'])
    expect(opts('photoexp-mat-surface')).toContain('gummy')
    expect(opts('photoexp-mat-atomistic')).toEqual(['cpk-flat', 'cpk-matte', 'cpk-glossy', 'cpk-metallic'])
  })

  it('wires each material dropdown to its own representation', () => {
    els['photoexp-mat-cylinders'].value = 'metallic'
    els['photoexp-mat-cylinders'].dispatchEvent(new Event('change'))
    expect(mode.setMaterialPreset).toHaveBeenCalledWith('cylinders', 'metallic')

    els['photoexp-mat-surface'].value = 'glass'
    els['photoexp-mat-surface'].dispatchEvent(new Event('change'))
    expect(mode.setMaterialPreset).toHaveBeenLastCalledWith('surface', 'glass')
  })

  it('syncToState selects the active preset in each dropdown', () => {
    panel.syncToState()
    expect(els['photoexp-mat-full'].value).toBe('flat')
    expect(els['photoexp-mat-atomistic'].value).toBe('cpk-flat')
  })

  it('renders every section as a collapsible card', () => {
    // Same contract as the Simulations-tab cards: clicking the heading toggles
    // the body and rotates the chevron.
    for (const id of ['lighting', 'figure', 'materials', 'camera', 'export', 'bg']) {
      const head = els[`photoexp-${id}-heading`]
      const body = els[`photoexp-${id}-body`]
      const arrow = els[`photoexp-${id}-arrow`]
      expect(body.style.display).toBe('')
      head.dispatchEvent(new Event('click'))
      expect(body.style.display).toBe('none')
      expect(arrow.classList.contains('is-collapsed')).toBe(true)
      head.dispatchEvent(new Event('click'))
      expect(body.style.display).toBe('')
      expect(arrow.classList.contains('is-collapsed')).toBe(false)
    }
  })

  it('wires FOV and the parallel-projection toggle', () => {
    panel.syncToState()
    els['photoexp-fov'].value = '20'
    els['photoexp-fov'].dispatchEvent(new Event('input'))
    expect(mode.setFOV).toHaveBeenCalledWith(20)
    expect(els['photoexp-fov-label'].textContent).toBe('20°')

    els['photoexp-parallel'].checked = true
    els['photoexp-parallel'].dispatchEvent(new Event('change'))
    expect(mode.setParallel).toHaveBeenCalledWith(true)
  })

  it('resolution presets set a real pixel size', () => {
    els['photoexp-res-preset'].value = 'p600'
    els['photoexp-res-preset'].dispatchEvent(new Event('change'))
    expect(mode.setExportSize).toHaveBeenCalledWith(8400, 5940)
    expect(els['photoexp-res-w'].value).toBe('8400')
  })

  it('editing a dimension by hand switches the preset to Custom', () => {
    panel.syncToState()                       // populates both dimension inputs
    els['photoexp-res-preset'].value = 'p300'
    els['photoexp-res-w'].value = '1234'
    els['photoexp-res-w'].dispatchEvent(new Event('change'))
    expect(els['photoexp-res-preset'].value).toBe('custom')
    expect(mode.setExportSize).toHaveBeenLastCalledWith(1234, 2970)
  })

  it('reports the tile count, since >4096 px must be rendered in tiles', () => {
    panel.syncToState()
    expect(els['photoexp-export-note'].textContent).toContain('2 tiles')
    expect(els['photoexp-export-note'].textContent).toContain('4200×2970')
  })

  it('the export button calls renderToBlob and re-enables itself', async () => {
    els['photoexp-export-btn'].dispatchEvent(new Event('click'))
    await vi.waitFor(() => expect(mode.renderToBlob).toHaveBeenCalledWith(4200, 2970))
    await vi.waitFor(() => expect(els['photoexp-export-btn'].disabled).toBe(false))
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
