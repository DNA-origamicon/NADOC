import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initPhotoPanel, formatShadowStatus, shadowResolution, DUPLEX_NM } from './photo_panel.js'

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
  'photo-exit-btn':               'button',
  'photo-status':                 'div',
  'photo-pin-lights':             'input',
  'photo-key-shadow':             'input',
  'photo-key-shadow-controls':    'div',
  'photo-key-shadow-mapsize':     'select',
  'photo-key-shadow-res':         'div',
  'photo-key-shadow-bias':        'input',
  'photo-key-shadow-bias-label':  'span',
  'photo-shadow-strength':        'input',
  'photo-shadow-strength-label':  'span',
  'photo-key-intensity':          'input',
  'photo-key-intensity-label':    'span',
  'photo-fill-intensity':         'input',
  'photo-fill-intensity-label':   'span',
  'photo-ambient-intensity':      'input',
  'photo-ambient-intensity-label':'span',
  'photo-max-contrast':           'button',
  'photo-shadow-depth':           'div',
  'photo-key-azimuth':            'input',
  'photo-key-azimuth-label':      'span',
  'photo-key-elevation':          'input',
  'photo-key-elevation-label':    'span',
  'photo-key-dir':                'div',
  'photo-key-dir-reset':          'button',
  'photo-lighting-heading':       'div',
  'photo-lighting-body':          'div',
  'photo-lighting-arrow':         'span',
  'photo-outline':                'input',
  'photo-outline-controls':       'div',
  'photo-outline-color':          'input',
  'photo-outline-strength':       'input',
  'photo-outline-strength-label': 'span',
  'photo-outline-thickness':      'input',
  'photo-outline-thickness-label':'span',
  'photo-outline-jump':           'input',
  'photo-outline-jump-label':     'span',
  'photo-depthcue':               'input',
  'photo-depthcue-controls':      'div',
  'photo-depthcue-color':         'input',
  'photo-depthcue-strength':      'input',
  'photo-depthcue-strength-label':'span',
  'photo-figure-heading':         'div',
  'photo-figure-body':            'div',
  'photo-figure-arrow':           'span',
  'photo-mat-full':               'select',
  'photo-mat-cylinders':          'select',
  'photo-mat-surface':            'select',
  'photo-mat-atomistic':          'select',
  'photo-materials-heading':      'div',
  'photo-materials-body':         'div',
  'photo-materials-arrow':        'span',
  'photo-bg-heading':             'div',
  'photo-bg-body':                'div',
  'photo-bg-arrow':               'span',
  'photo-fov':                    'input',
  'photo-fov-label':              'span',
  'photo-parallel':               'input',
  'photo-res-preset':             'select',
  'photo-res-w':                  'input',
  'photo-res-h':                  'input',
  'photo-export-note':            'div',
  'photo-export-btn':             'button',
  'photo-camera-heading':         'div',
  'photo-camera-body':            'div',
  'photo-camera-arrow':           'span',
  'photo-export-heading':         'div',
  'photo-export-body':            'div',
  'photo-export-arrow':           'span',
  'photo-bg-type':                'select',
  'photo-bg-color':               'input',
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

describe('initPhotoPanel', () => {
  let els, mode, panel, onExit

  beforeEach(() => {
    vi.useFakeTimers()
    els = mountIds(PANEL_IDS)
    for (const id of ['photo-pin-lights', 'photo-key-shadow',
                      'photo-outline', 'photo-depthcue']) els[id].type = 'checkbox'
    for (const id of ['photo-outline-color', 'photo-depthcue-color']) els[id].type = 'color'
    for (const id of ['photo-key-shadow-bias', 'photo-shadow-strength',
                      'photo-fov']) els[id].type = 'range'
    for (const id of ['photo-res-w', 'photo-res-h']) els[id].type = 'number'
    els['photo-parallel'].type = 'checkbox'
    els['photo-bg-color'].type = 'color'
    for (const [id, values] of [
      ['photo-key-shadow-mapsize', ['1024', '2048', '4096', '8192']],
      ['photo-res-preset', ['screen', 'x2', 'p300', 'p600', 'custom']],
      ['photo-bg-type', ['color', 'transparent']],
    ]) {
      for (const v of values) {
        const o = document.createElement('option')
        o.value = v; o.textContent = v
        els[id].appendChild(o)
      }
    }
    mode = makeMode()
    onExit = vi.fn()
    panel = initPhotoPanel(mode, { onExit })
  })

  afterEach(() => { panel?.dispose(); vi.useRealTimers(); clearDom() })

  it('syncToState pushes the controller settings into every control', () => {
    panel.syncToState()
    expect(els['photo-pin-lights'].checked).toBe(true)
    expect(els['photo-key-shadow'].checked).toBe(true)
    expect(els['photo-key-shadow-mapsize'].value).toBe('2048')
    expect(els['photo-key-shadow-bias-label'].textContent).toBe('1.0×')
    expect(els['photo-shadow-strength-label'].textContent).toBe('1.00')
  })

  it('shows the live nm/texel resolution for the fitted scene', () => {
    panel.syncToState()
    // radius 150 nm at 2048 texels → 0.146 nm/texel, comfortably sub-duplex.
    expect(els['photo-key-shadow-res'].textContent).toContain('0.146 nm/texel')
    expect(els['photo-key-shadow-res'].textContent).not.toContain('COARSER')
  })

  it('warns in the UI when the map cannot resolve a duplex', () => {
    mode.getStatus = () => ({ active: true, keyShadow: true, pinned: true, radius: 70710 })
    panel.syncToState()
    expect(els['photo-key-shadow-res'].textContent).toContain('COARSER')
  })

  it('wires the shadow map size', () => {
    els['photo-key-shadow-mapsize'].value = '8192'
    els['photo-key-shadow-mapsize'].dispatchEvent(new Event('change'))
    expect(mode.setKeyShadowMapSize).toHaveBeenCalledWith(8192)
  })

  it('drives bias and shadow darkness live, with formatted read-outs', () => {
    els['photo-key-shadow-bias'].value = '2.5'
    els['photo-key-shadow-bias'].dispatchEvent(new Event('input'))
    expect(mode.setKeyShadowBias).toHaveBeenCalledWith(2.5)
    expect(els['photo-key-shadow-bias-label'].textContent).toBe('2.5×')

    els['photo-shadow-strength'].value = '0.4'
    els['photo-shadow-strength'].dispatchEvent(new Event('input'))
    expect(mode.setShadowStrength).toHaveBeenCalledWith(0.4)
    expect(els['photo-shadow-strength-label'].textContent).toBe('0.40')
  })

  it('hides the shadow sub-controls when the key shadow is switched off', () => {
    panel.syncToState()
    els['photo-key-shadow'].checked = false
    els['photo-key-shadow'].dispatchEvent(new Event('change'))
    expect(mode.setKeyShadow).toHaveBeenCalledWith(false)
    expect(els['photo-key-shadow-controls'].style.display).toBe('none')
  })

  it('wires the camera pin and background', () => {
    els['photo-pin-lights'].checked = false
    els['photo-pin-lights'].dispatchEvent(new Event('change'))
    expect(mode.setPinLights).toHaveBeenCalledWith(false)

    els['photo-bg-type'].value = 'transparent'
    els['photo-bg-type'].dispatchEvent(new Event('change'))
    expect(mode.setBackground).toHaveBeenCalledWith('transparent', undefined)
    expect(els['photo-bg-color'].disabled).toBe(true)

    els['photo-bg-color'].value = '#ff0000'
    els['photo-bg-color'].dispatchEvent(new Event('input'))
    expect(mode.setBackground).toHaveBeenLastCalledWith(undefined, '#ff0000')
  })

  it('describes where the light is, and how far off the camera axis', () => {
    panel.syncToState()
    expect(els['photo-key-dir'].textContent).toContain('upper-left')
    expect(els['photo-key-dir'].textContent).toContain('55° off the camera axis')
  })

  it('the Reset direction button defers to the mode, which owns the defaults', () => {
    els['photo-key-dir-reset'].dispatchEvent(new Event('click'))
    expect(mode.resetKeyDirection).toHaveBeenCalledTimes(1)
  })

  it('wires the outline controls and hides them when it is off', () => {
    panel.syncToState()
    expect(els['photo-outline-controls'].style.display).toBe('none')  // off by default

    els['photo-outline'].checked = true
    els['photo-outline'].dispatchEvent(new Event('change'))
    expect(mode.setOutline).toHaveBeenCalledWith(true)
    expect(els['photo-outline-controls'].style.display).toBe('flex')

    els['photo-outline-thickness'].value = '2.5'
    els['photo-outline-thickness'].dispatchEvent(new Event('input'))
    expect(mode.setOutlineThickness).toHaveBeenCalledWith(2.5)
    expect(els['photo-outline-thickness-label'].textContent).toBe('2.5')

    // ChimeraX's depth_jump replaces the old depth/crease pair: the mimic is
    // depth-only, so there is no crease control to wire at all.
    els['photo-outline-jump'].value = '0.075'
    els['photo-outline-jump'].dispatchEvent(new Event('input'))
    expect(mode.setOutlineDepthJump).toHaveBeenCalledWith(0.075)
    expect(els['photo-outline-jump-label'].textContent).toBe('0.075')
  })

  it('wires the depth-cue controls', () => {
    panel.syncToState()
    els['photo-depthcue'].checked = true
    els['photo-depthcue'].dispatchEvent(new Event('change'))
    expect(mode.setDepthCue).toHaveBeenCalledWith(true)
    expect(els['photo-depthcue-controls'].style.display).toBe('flex')

    els['photo-depthcue-strength'].value = '0.6'
    els['photo-depthcue-strength'].dispatchEvent(new Event('input'))
    expect(mode.setDepthCueStrength).toHaveBeenCalledWith(0.6)

    els['photo-depthcue-color'].value = '#00ff00'
    els['photo-depthcue-color'].dispatchEvent(new Event('input'))
    expect(mode.setDepthCueColor).toHaveBeenCalledWith('#00ff00')
  })

  it('builds the material dropdowns from PRESET_LABELS', () => {
    // Driven off the shared preset table, so adding a preset in
    // material_presets.js shows up here with no markup change.
    const opts = id => [...els[id].querySelectorAll('option')].map(o => o.value)
    expect(opts('photo-mat-full')).toEqual(['flat', 'matte', 'glossy', 'metallic'])
    expect(opts('photo-mat-surface')).toContain('gummy')
    expect(opts('photo-mat-atomistic')).toEqual(['cpk-flat', 'cpk-matte', 'cpk-glossy', 'cpk-metallic'])
  })

  it('wires each material dropdown to its own representation', () => {
    els['photo-mat-cylinders'].value = 'metallic'
    els['photo-mat-cylinders'].dispatchEvent(new Event('change'))
    expect(mode.setMaterialPreset).toHaveBeenCalledWith('cylinders', 'metallic')

    els['photo-mat-surface'].value = 'glass'
    els['photo-mat-surface'].dispatchEvent(new Event('change'))
    expect(mode.setMaterialPreset).toHaveBeenLastCalledWith('surface', 'glass')
  })

  it('syncToState selects the active preset in each dropdown', () => {
    panel.syncToState()
    expect(els['photo-mat-full'].value).toBe('flat')
    expect(els['photo-mat-atomistic'].value).toBe('cpk-flat')
  })

  it('renders every section as a collapsible card', () => {
    // Same contract as the Simulations-tab cards: clicking the heading toggles
    // the body and rotates the chevron.
    for (const id of ['lighting', 'figure', 'materials', 'camera', 'export', 'bg']) {
      const head = els[`photo-${id}-heading`]
      const body = els[`photo-${id}-body`]
      const arrow = els[`photo-${id}-arrow`]
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
    els['photo-fov'].value = '20'
    els['photo-fov'].dispatchEvent(new Event('input'))
    expect(mode.setFOV).toHaveBeenCalledWith(20)
    expect(els['photo-fov-label'].textContent).toBe('20°')

    els['photo-parallel'].checked = true
    els['photo-parallel'].dispatchEvent(new Event('change'))
    expect(mode.setParallel).toHaveBeenCalledWith(true)
  })

  it('resolution presets set a real pixel size', () => {
    els['photo-res-preset'].value = 'p600'
    els['photo-res-preset'].dispatchEvent(new Event('change'))
    expect(mode.setExportSize).toHaveBeenCalledWith(8400, 5940)
    expect(els['photo-res-w'].value).toBe('8400')
  })

  it('editing a dimension by hand switches the preset to Custom', () => {
    panel.syncToState()                       // populates both dimension inputs
    els['photo-res-preset'].value = 'p300'
    els['photo-res-w'].value = '1234'
    els['photo-res-w'].dispatchEvent(new Event('change'))
    expect(els['photo-res-preset'].value).toBe('custom')
    expect(mode.setExportSize).toHaveBeenLastCalledWith(1234, 2970)
  })

  it('reports the tile count, since >4096 px must be rendered in tiles', () => {
    panel.syncToState()
    expect(els['photo-export-note'].textContent).toContain('2 tiles')
    expect(els['photo-export-note'].textContent).toContain('4200×2970')
  })

  it('the export button calls renderToBlob and re-enables itself', async () => {
    els['photo-export-btn'].dispatchEvent(new Event('click'))
    await vi.waitFor(() => expect(mode.renderToBlob).toHaveBeenCalledWith(4200, 2970))
    await vi.waitFor(() => expect(els['photo-export-btn'].disabled).toBe(false))
  })

  it('the exit button calls back out to the tab controller', () => {
    els['photo-exit-btn'].dispatchEvent(new Event('click'))
    expect(onExit).toHaveBeenCalledTimes(1)
  })

  it('polls the status line while entered and stops on exit', () => {
    const spy = vi.spyOn(mode, 'getStatus')
    panel.onEnter()
    expect(els['photo-status'].textContent).toContain('key shadow on')
    const afterEnter = spy.mock.calls.length
    vi.advanceTimersByTime(1500)
    expect(spy.mock.calls.length).toBeGreaterThan(afterEnter)

    panel.onExit()
    const afterExit = spy.mock.calls.length
    vi.advanceTimersByTime(1500)
    expect(spy.mock.calls.length).toBe(afterExit)
  })
})
