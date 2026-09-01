import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initPhotoPanel, formatShadowStatus, shadowResolution, DUPLEX_NM,
         animationDuration, videoPlan, VIDEO_RES_PRESETS } from './photo_panel.js'

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

// ── Video export helpers ─────────────────────────────────────────────────────

describe('animationDuration', () => {
  it('sums transition + hold across keyframes, like the player schedule does', () => {
    // An animation has no absolute-time field — duration is only ever implied
    // by the list, so this has to mirror _buildSchedule exactly.
    expect(animationDuration({ keyframes: [
      { transition_duration_s: 0.5, hold_duration_s: 1.0 },
      { transition_duration_s: 0.5, hold_duration_s: 2.0 },
    ] })).toBeCloseTo(4.0, 9)
  })

  it('treats missing durations as zero rather than NaN', () => {
    expect(animationDuration({ keyframes: [{}, { hold_duration_s: 1 }] })).toBe(1)
  })

  it('is 0 for nothing to play', () => {
    expect(animationDuration(null)).toBe(0)
    expect(animationDuration({ keyframes: [] })).toBe(0)
  })
})

describe('videoPlan', () => {
  it('counts both endpoints — the loop renders t=0 and t=duration', () => {
    const p = videoPlan({ durationS: 2, fps: 10, width: 1920, height: 1080 })
    expect(p.frames).toBe(21)
    expect(p.tiles).toBe(1)
    expect(p.text).toContain('2.0 s')
    expect(p.text).toContain('21 frames')
  })

  it('reports the per-frame tile cost, which is what makes long exports slow', () => {
    // 4K is still one tile; a 300-DPI still preset would be four.
    expect(videoPlan({ durationS: 1, fps: 30, width: 3840, height: 2160 }).tiles).toBe(1)
    expect(videoPlan({ durationS: 1, fps: 30, width: 8400, height: 5940 }).tiles).toBe(6)
  })

  it('is empty when there is nothing to render', () => {
    expect(videoPlan({ durationS: 0, fps: 30, width: 1920, height: 1080 }).frames).toBe(0)
    expect(videoPlan({ durationS: 5, fps: 0, width: 1920, height: 1080 }).text).toBe('')
  })
})

describe('VIDEO_RES_PRESETS', () => {
  it('are video sizes, not the print sizes — every one is a single tile', () => {
    for (const [w, h] of Object.values(VIDEO_RES_PRESETS)) {
      expect(w).toBeLessThanOrEqual(4096)
      expect(h).toBeLessThanOrEqual(4096)
    }
    expect(VIDEO_RES_PRESETS['1080p']).toEqual([1920, 1080])
  })
})

const PANEL_IDS = {
  'photo-exit-btn':               'button',
  'photo-status':                 'div',
  'photo-profile-select':         'select',
  'photo-profile-new':            'button',
  'photo-profile-rename':         'button',
  'photo-profile-delete':         'button',
  'photo-profile-reset':          'button',
  'photo-profile-status':         'div',
  'photo-pin-lights':             'input',
  'photo-studio-environment':     'input',
  'photo-studio-environment-controls': 'div',
  'photo-studio-environment-intensity': 'input',
  'photo-studio-environment-intensity-label': 'span',
  'photo-studio-environment-rotation': 'input',
  'photo-studio-environment-rotation-label': 'span',
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
  'photo-fov':                    'input',
  'photo-fov-label':              'span',
  'photo-fov-reset':              'button',
  'photo-parallel':               'input',
  'photo-res-preset':             'select',
  'photo-res-w':                  'input',
  'photo-res-h':                  'input',
  'photo-export-note':            'div',
  'photo-export-btn':             'button',
  'photo-anim-select':            'select',
  'photo-video-res':              'select',
  'photo-video-format':           'select',
  'photo-video-fps':              'input',
  'photo-video-note':             'div',
  'photo-video-btn':              'button',
  'photo-camera-heading':         'div',
  'photo-camera-body':            'div',
  'photo-camera-arrow':           'span',
  'photo-export-heading':         'div',
  'photo-export-body':            'div',
  'photo-export-arrow':           'span',
  'photo-bg-type':                'select',
  'photo-bg-color':               'input',
  'photo-floor':                  'input',
  'photo-floor-controls':         'div',
  'photo-floor-axis':             'select',
  'photo-floor-opacity':          'input',
  'photo-floor-opacity-label':    'span',
  'photo-floor-offset':           'input',
  'photo-floor-offset-label':     'span',
}

function makeMode(overrides = {}) {
  const settings = {
    bgType: 'color', bgColor: '#0b0d10',
    pinLights: true, keyShadow: true, keyShadowMapSize: 2048,
    studioEnvironment: true, studioEnvironmentIntensity: 1, studioEnvironmentRotation: 0,
    keyShadowBias: 1.0, shadowStrength: 1.0,
    keyAzimuth: 135, keyElevation: 35.264,
    floor: true, floorAxis: '-y', floorOpacity: 0.35, floorOffset: 0,
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
    setStudioEnvironment: vi.fn(), setStudioEnvironmentIntensity: vi.fn(),
    setStudioEnvironmentRotation: vi.fn(),
    setKeyAzimuth: vi.fn(), setKeyElevation: vi.fn(), resetKeyDirection: vi.fn(),
    setKeyShadowMapSize: vi.fn(), setKeyShadowBias: vi.fn(), setShadowStrength: vi.fn(),
    setKeyIntensity: vi.fn(), setFillIntensity: vi.fn(), setAmbientIntensity: vi.fn(),
    setBackground: vi.fn(), setMaterialPreset: vi.fn(),
    setOutline: vi.fn(), setOutlineColor: vi.fn(), setOutlineStrength: vi.fn(),
    setOutlineThickness: vi.fn(), setOutlineSensitivity: vi.fn(), setOutlineDepthJump: vi.fn(),
    setDepthCue: vi.fn(), setDepthCueColor: vi.fn(), setDepthCueStrength: vi.fn(),
    setFloor: vi.fn(), setFloorOpacity: vi.fn(), setFloorOffset: vi.fn(),
    setFloorAxis: vi.fn(),
    setFOV: vi.fn(), resetFOV: vi.fn(), setParallel: vi.fn(), setExportSize: vi.fn(),
    renderToBlob: vi.fn(async () => null),
  }
}

describe('initPhotoPanel', () => {
  let els, mode, panel, onExit

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.removeItem('nadoc.photoProfiles.v1')
    localStorage.removeItem('nadoc.photoActiveProfile.v1')
    els = mountIds(PANEL_IDS)
    for (const id of ['photo-pin-lights', 'photo-studio-environment', 'photo-key-shadow',
                      'photo-outline', 'photo-depthcue',
                      'photo-floor']) els[id].type = 'checkbox'
    for (const id of ['photo-outline-color', 'photo-depthcue-color']) els[id].type = 'color'
    for (const id of ['photo-key-shadow-bias', 'photo-shadow-strength',
                      'photo-studio-environment-intensity', 'photo-studio-environment-rotation',
                      'photo-floor-opacity', 'photo-floor-offset',
                      'photo-fov']) els[id].type = 'range'
    for (const id of ['photo-res-w', 'photo-res-h']) els[id].type = 'number'
    els['photo-parallel'].type = 'checkbox'
    els['photo-bg-color'].type = 'color'
    for (const [id, values] of [
      ['photo-key-shadow-mapsize', ['1024', '2048', '4096', '8192']],
      ['photo-res-preset', ['screen', 'x2', 'p300', 'p600', 'custom']],
      ['photo-bg-type', ['color', 'transparent']],
      ['photo-floor-axis', ['-y', '+y', '-x', '+x', '-z', '+z']],
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
    expect(els['photo-studio-environment'].checked).toBe(true)
    expect(els['photo-studio-environment-intensity-label'].textContent).toBe('1.00')
    expect(els['photo-studio-environment-rotation-label'].textContent).toBe('0°')
  })

  it('creates a durable default profile on first use', () => {
    const profiles = JSON.parse(localStorage.getItem('nadoc.photoProfiles.v1'))
    expect(profiles.Default.keyIntensity).toBe(2)
    expect(localStorage.getItem('nadoc.photoActiveProfile.v1')).toBe('Default')
    expect(els['photo-profile-select'].value).toBe('Default')
  })

  it('restores the active profile through the current Photomode setters', () => {
    localStorage.setItem('nadoc.photoProfiles.v1', JSON.stringify({ Saved: {
      keyIntensity: 3.25, keyAzimuth: -45, full: 'metallic',
      outline: true, fov: 24, bgType: 'transparent', bgColor: '#123456',
    } }))
    localStorage.setItem('nadoc.photoActiveProfile.v1', 'Saved')

    panel.applyActiveProfile()

    expect(mode.setKeyIntensity).toHaveBeenLastCalledWith(3.25)
    expect(mode.setKeyAzimuth).toHaveBeenLastCalledWith(-45)
    expect(mode.setMaterialPreset).toHaveBeenLastCalledWith('full', 'metallic')
    expect(mode.setOutline).toHaveBeenLastCalledWith(true)
    expect(mode.setFOV).toHaveBeenLastCalledWith(24)
    expect(mode.setBackground).toHaveBeenLastCalledWith('transparent', '#123456')
  })

  it('auto-saves changed settings into the active profile', () => {
    mode.getSettings = () => ({ ...makeMode().getSettings(), keyIntensity: 3.5 })
    els['photo-key-intensity'].dispatchEvent(new Event('input', { bubbles: true }))
    vi.advanceTimersByTime(250)

    const profiles = JSON.parse(localStorage.getItem('nadoc.photoProfiles.v1'))
    expect(profiles.Default.keyIntensity).toBe(3.5)
    expect(els['photo-profile-status'].textContent).toContain('saved')
  })

  it('wires studio ambient reflections, strength, and rotation', () => {
    panel.syncToState()
    els['photo-studio-environment'].checked = false
    els['photo-studio-environment'].dispatchEvent(new Event('change'))
    expect(mode.setStudioEnvironment).toHaveBeenCalledWith(false)
    expect(els['photo-studio-environment-controls'].style.display).toBe('none')

    els['photo-studio-environment-intensity'].value = '1.75'
    els['photo-studio-environment-intensity'].dispatchEvent(new Event('input'))
    expect(mode.setStudioEnvironmentIntensity).toHaveBeenCalledWith(1.75)
    expect(els['photo-studio-environment-intensity-label'].textContent).toBe('1.75')

    els['photo-studio-environment-rotation'].value = '45'
    els['photo-studio-environment-rotation'].dispatchEvent(new Event('input'))
    expect(mode.setStudioEnvironmentRotation).toHaveBeenCalledWith(45)
    expect(els['photo-studio-environment-rotation-label'].textContent).toBe('45°')
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

  it('syncToState and the Side dropdown drive the shadow catcher', () => {
    panel.syncToState()
    expect(els['photo-floor'].checked).toBe(true)
    expect(els['photo-floor-axis'].value).toBe('-y')
    expect(els['photo-floor-opacity-label'].textContent).toBe('0.35')
    expect(els['photo-floor-offset-label'].textContent).toBe('0.0 nm')

    els['photo-floor-axis'].value = '+y'
    els['photo-floor-axis'].dispatchEvent(new Event('change'))
    expect(mode.setFloorAxis).toHaveBeenCalledWith('+y')

    els['photo-floor-offset'].value = '12'
    els['photo-floor-offset'].dispatchEvent(new Event('input'))
    expect(mode.setFloorOffset).toHaveBeenCalledWith(12)
    expect(els['photo-floor-offset-label'].textContent).toBe('12.0 nm')

    // Unchecking hides the sub-controls, same pattern as the key-shadow group.
    els['photo-floor'].checked = false
    els['photo-floor'].dispatchEvent(new Event('change'))
    expect(mode.setFloor).toHaveBeenCalledWith(false)
    expect(els['photo-floor-controls'].style.display).toBe('none')
  })

  it('renders every section as a collapsible card', () => {
    // Same contract as the Simulations-tab cards: clicking the heading toggles
    // the body and rotates the chevron.
    // No 'bg' — the background controls moved INTO the Figure card, so that
    // card and its heading/body/chevron no longer exist.
    for (const id of ['lighting', 'figure', 'materials', 'camera', 'export']) {
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

  it('the FOV reset button defers to the mode and re-syncs the slider', () => {
    els['photo-fov'].value = '20'
    els['photo-fov'].dispatchEvent(new Event('input'))
    expect(els['photo-fov-label'].textContent).toBe('20°')

    // The mock's settings still report 55 — syncToState must pull the slider
    // and label back from the mode rather than leaving the hand-set value.
    els['photo-fov-reset'].dispatchEvent(new Event('click'))
    expect(mode.resetFOV).toHaveBeenCalledTimes(1)
    expect(els['photo-fov'].value).toBe('55')
    expect(els['photo-fov-label'].textContent).toBe('55°')
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

// ── Video export section ─────────────────────────────────────────────────────

describe('initPhotoPanel — video export', () => {
  let els, mode, panel, player, exportPhotoVideo, store

  const ANIMS = [
    { id: 'a1', name: 'Unfold', fps: 24, keyframes: [{ transition_duration_s: 0.5, hold_duration_s: 1.5 }] },
    { id: 'a2', name: 'Spin',   fps: 30, keyframes: [{ transition_duration_s: 1, hold_duration_s: 1 }] },
  ]

  function mount(state) {
    store = { getState: () => state }
    panel = initPhotoPanel(mode, { onExit: vi.fn(), store, player, exportPhotoVideo })
    panel.onEnter()
  }

  beforeEach(() => {
    els = mountIds(PANEL_IDS)
    for (const id of ['photo-pin-lights', 'photo-key-shadow', 'photo-outline',
                      'photo-depthcue', 'photo-floor', 'photo-parallel']) els[id].type = 'checkbox'
    for (const id of ['photo-outline-color', 'photo-depthcue-color']) els[id].type = 'color'
    for (const id of ['photo-res-w', 'photo-res-h', 'photo-video-fps']) els[id].type = 'number'
    // A <select> silently rejects a value that isn't one of its options, so the
    // static markup's options have to exist here too.
    const addOpts = (id, vals) => vals.forEach(v => {
      const o = document.createElement('option'); o.value = v; els[id].appendChild(o)
    })
    addOpts('photo-video-res', Object.keys(VIDEO_RES_PRESETS))
    addOpts('photo-video-format', ['webm', 'gif'])
    els['photo-video-res'].value = '1080p'
    mode = makeMode()
    player = { id: 'player' }
    exportPhotoVideo = vi.fn(async () => {})
  })

  afterEach(() => { panel?.dispose(); clearDom() })

  it('lists the design\'s saved animations and adopts the first one\'s fps', () => {
    mount({ currentDesign: { animations: ANIMS } })
    expect([...els['photo-anim-select'].options].map(o => o.textContent)).toEqual(['Unfold', 'Spin'])
    expect(els['photo-video-fps'].value).toBe('24')
  })

  it('prefers the assembly\'s animations when one is open', () => {
    mount({ currentDesign: { animations: ANIMS }, currentAssembly: { animations: [ANIMS[1]] } })
    expect([...els['photo-anim-select'].options].map(o => o.textContent)).toEqual(['Spin'])
  })

  it('says so, and disables the button, when there is nothing to export', () => {
    mount({ currentDesign: { animations: [] } })
    expect(els['photo-video-note'].textContent).toMatch(/No saved animations/)
    expect(els['photo-video-btn'].disabled).toBe(true)
  })

  it('prices the export from the keyframes without ever calling play()', () => {
    mount({ currentDesign: { animations: ANIMS } })
    // 2.0 s at 24 fps = 49 frames. play() bakes geometry — merely opening the
    // dropdown must not pay that.
    expect(els['photo-video-note'].textContent).toContain('2.0 s')
    expect(els['photo-video-note'].textContent).toContain('49 frames')
    expect(els['photo-video-note'].textContent).toContain('1920×1080')
  })

  it('re-prices when the size or fps changes', () => {
    mount({ currentDesign: { animations: ANIMS } })
    els['photo-video-res'].value = '2160p'
    els['photo-video-res'].dispatchEvent(new Event('change'))
    expect(els['photo-video-note'].textContent).toContain('3840×2160')

    els['photo-video-fps'].value = '10'
    els['photo-video-fps'].dispatchEvent(new Event('change'))
    expect(els['photo-video-note'].textContent).toContain('21 frames')
  })

  it('exports the SELECTED animation at the chosen size and format', async () => {
    mount({ currentDesign: { animations: ANIMS } })
    els['photo-anim-select'].value = 'a2'
    els['photo-anim-select'].dispatchEvent(new Event('change'))
    expect(els['photo-video-fps'].value).toBe('30')     // adopts that animation's fps

    els['photo-video-format'].value = 'gif'
    els['photo-video-res'].value = '720p'
    els['photo-video-btn'].dispatchEvent(new Event('click'))

    await vi.waitFor(() => expect(exportPhotoVideo).toHaveBeenCalled())
    const arg = exportPhotoVideo.mock.calls[0][0]
    expect(arg.animation.id).toBe('a2')
    expect(arg.width).toBe(1280)
    expect(arg.height).toBe(720)
    expect(arg.options.format).toBe('gif')
    expect(arg.options.fps).toBe(30)
    // The frame session is opened on the photo mode itself, so every frame gets
    // the live photo settings rather than a snapshot.
    expect(arg.photoRenderer).toBe(mode)
    expect(arg.player).toBe(player)
    await vi.waitFor(() => expect(els['photo-video-btn'].disabled).toBe(false))
  })

  it('re-enables the button and reports a failure rather than dying silently', async () => {
    exportPhotoVideo = vi.fn(async () => { throw new Error('GL died') })
    mount({ currentDesign: { animations: ANIMS } })
    els['photo-video-btn'].dispatchEvent(new Event('click'))
    await vi.waitFor(() => expect(els['photo-video-note'].textContent).toContain('GL died'))
    expect(els['photo-video-btn'].disabled).toBe(false)
  })

  it('reports a cancel as a cancel, not an error', async () => {
    exportPhotoVideo = vi.fn(async () => {
      const e = new Error('Aborted'); e.name = 'AbortError'; throw e
    })
    mount({ currentDesign: { animations: ANIMS } })
    els['photo-video-btn'].dispatchEvent(new Event('click'))
    await vi.waitFor(() => expect(els['photo-video-note'].textContent).toBe('Cancelled.'))
  })

  it('does nothing when the panel was built without the video deps', () => {
    store = { getState: () => ({ currentDesign: { animations: ANIMS } }) }
    panel = initPhotoPanel(mode, { onExit: vi.fn(), store })   // no player/exporter
    panel.onEnter()
    expect(() => els['photo-video-btn'].dispatchEvent(new Event('click'))).not.toThrow()
  })
})
