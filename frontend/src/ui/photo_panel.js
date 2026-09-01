/**
 * Photo-mode panel — the controls for scene/photo_mode.js.
 *
 * Thin by design: it reads DOM elements, pushes values into the mode controller,
 * and renders a status line. All rendering decisions live in the mode; this file
 * only translates clicks into calls, so the experiment can be re-skinned or
 * thrown away without touching the renderer.
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { showConfirm } from './primitives/confirm.js'
import { PRESET_LABELS } from '../scene/photo_renderer/material_presets.js'
import { trajectoryJobs } from '../scene/trajectory_keyframes.js'
import { trajectorySamplingPlan } from '../scene/trajectory_range.js'
import { planExportPhases, beginExportSession, endExportSession }
  from '../scene/export_progress.js'

const PROFILES_KEY = 'nadoc.photoProfiles.v1'
const ACTIVE_PROFILE_KEY = 'nadoc.photoActiveProfile.v1'

export function loadPhotoProfiles() {
  try {
    const value = JSON.parse(localStorage.getItem(PROFILES_KEY) || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  } catch { return {} }
}

function _savePhotoProfiles(profiles) {
  try { localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles)) } catch {}
}

function _activeProfileName() {
  try { return localStorage.getItem(ACTIVE_PROFILE_KEY) || '' } catch { return '' }
}

function _setActiveProfileName(name) {
  try { localStorage.setItem(ACTIVE_PROFILE_KEY, name) } catch {}
}

/** B-DNA duplex diameter — the feature a shadow map has to resolve to be useful. */
export const DUPLEX_NM = 2.0

/**
 * World size of one shadow-map texel, and how that compares with a duplex.
 *
 * This is the number that decides whether an object casts a readable shadow onto
 * something behind it: once a texel is wider than a helix, the shadow of a thin
 * feature cannot be represented at all and long-range shadowing degenerates into
 * a wash. It turned out to be THE parameter here — ChimeraX's map-size defaults
 * are sized for a ~5 nm protein, not a 150 nm origami.
 *
 * @param {number} radiusNm — scene bounding radius the frustum is fitted to
 * @param {number} texels   — pixels across the map
 * @returns {{nmPerTexel:number, duplexes:number, ok:boolean}}
 */
export function shadowResolution(radiusNm, texels) {
  if (!(radiusNm > 0) || !(texels > 0)) return { nmPerTexel: 0, duplexes: 0, ok: false }
  const nmPerTexel = (2 * radiusNm) / texels
  return {
    nmPerTexel,
    duplexes: DUPLEX_NM / nmPerTexel,     // texels across one duplex
    ok: nmPerTexel <= DUPLEX_NM / 2,      // need ≥2 texels per duplex to resolve it
  }
}

/**
 * Fraction of the light a cast shadow can remove. A shadow only subtracts the
 * KEY light, so fill + ambient are the floor it cannot go below — which is why
 * ChimeraX's own 0.7/0.3/0.8 gives a shadow only 39% dark.
 */
export function shadowDepthFraction({ keyIntensity, fillIntensity, ambientIntensity }) {
  const total = keyIntensity + fillIntensity + ambientIntensity
  if (!(total > 0)) return 0
  return keyIntensity / total
}

/**
 * Video output sizes. Deliberately SEPARATE from the still presets below: those
 * are print sizes (300 DPI = 4200×2970, 600 DPI = 8400×5940) which tile 4–12×
 * per frame. Fine for one still, absurd for a 300-frame clip.
 */
export const VIDEO_RES_PRESETS = {
  '720p':  [1280, 720],
  '1080p': [1920, 1080],
  '1440p': [2560, 1440],
  '2160p': [3840, 2160],
}

/**
 * Total playing time of an animation, in seconds.
 *
 * Mirrors the player's `_buildSchedule`, which walks keyframes accumulating
 * `transition_duration_s + hold_duration_s` — an animation has no absolute-time
 * field, so duration is only ever implied by the list. Re-derived here so the
 * panel can price an export WITHOUT calling `play()` (which bakes geometry and
 * would make merely opening the dropdown expensive).
 *
 * @param {{keyframes?: Array}} animation
 * @returns {number} seconds
 */
export function animationDuration(animation) {
  const kfs = animation?.keyframes
  if (!Array.isArray(kfs)) return 0
  let total = 0
  for (const kf of kfs) {
    total += (kf?.transition_duration_s ?? 0) + (kf?.hold_duration_s ?? 0)
  }
  return total
}

/**
 * What an export will cost, as the note line under the button.
 * Pure, so the arithmetic is testable without a GL context.
 *
 * @param {{durationS:number, fps:number, width:number, height:number}} p
 * @returns {{frames:number, tiles:number, text:string}}
 */
export function videoPlan({ durationS, fps, width, height }) {
  if (!(durationS > 0) || !(fps > 0)) return { frames: 0, tiles: 0, text: '' }
  // +1 because the loop renders both endpoints (t=0 and t=duration).
  const frames = Math.ceil(durationS * fps) + 1
  const tiles  = Math.max(1, Math.ceil(width / 4096)) * Math.max(1, Math.ceil(height / 4096))
  return {
    frames, tiles,
    text: `${durationS.toFixed(1)} s · ${frames} frames · ${width}×${height}`
        + ` · ${tiles} tile${tiles === 1 ? '' : 's'}/frame`,
  }
}

/**
 * Format the status line. Pure — the string is the whole contract, so the test
 * can assert it without a DOM.
 *
 * @param {{active:boolean, keyShadow:boolean, pinned:boolean,
 *          radius:number, mapSize:number}} status
 * @returns {string}
 */
export function formatShadowStatus(status) {
  if (!status?.active) return 'inactive'
  const bits = [status.keyShadow ? 'key shadow on' : 'key shadow off']
  if (status.pinned) bits.push('camera-pinned')
  if (status.radius > 0) {
    const r = status.radius >= 100 ? `${Math.round(status.radius)} nm` : `${status.radius.toFixed(1)} nm`
    bits.push(`scene radius ${r}`)
  }
  return bits.join(' · ')
}

/**
 * @param {object} photoMode — controller from createPhotoMode()
 * @param {object} deps
 * @param {() => void}   deps.onExit
 * @param {object}       [deps.store]            — for the saved-animation list
 * @param {object}       [deps.player]           — initAnimationPlayer, driven frame-by-frame
 * @param {function}     [deps.exportPhotoVideo] — from scene/export_video.js
 */
export function initPhotoPanel(photoMode, { onExit, store, player, exportPhotoVideo, trajectoryKeyframes = null } = {}) {
  const $ = (id) => document.getElementById(id)

  const els = {
    exit:      $('photo-exit-btn'),
    status:    $('photo-status'),
    pinLights: $('photo-pin-lights'),
    studioEnvironment:         $('photo-studio-environment'),
    studioEnvironmentControls: $('photo-studio-environment-controls'),
    studioEnvironmentIntensity:      $('photo-studio-environment-intensity'),
    studioEnvironmentIntensityLabel: $('photo-studio-environment-intensity-label'),
    studioEnvironmentRotation:       $('photo-studio-environment-rotation'),
    studioEnvironmentRotationLabel:  $('photo-studio-environment-rotation-label'),
    keyShadow: $('photo-key-shadow'),
    keyShadowControls:  $('photo-key-shadow-controls'),
    keyShadowMapSize:   $('photo-key-shadow-mapsize'),
    keyShadowRes:       $('photo-key-shadow-res'),
    keyShadowBias:      $('photo-key-shadow-bias'),
    keyShadowBiasLabel: $('photo-key-shadow-bias-label'),
    keyAzimuth:        $('photo-key-azimuth'),
    keyAzimuthLabel:   $('photo-key-azimuth-label'),
    keyElevation:      $('photo-key-elevation'),
    keyElevationLabel: $('photo-key-elevation-label'),
    keyDir:            $('photo-key-dir'),
    keyDirReset:       $('photo-key-dir-reset'),
    shadowStrength:      $('photo-shadow-strength'),
    shadowStrengthLabel: $('photo-shadow-strength-label'),
    floor:             $('photo-floor'),
    floorControls:     $('photo-floor-controls'),
    floorAxis:         $('photo-floor-axis'),
    floorOpacity:      $('photo-floor-opacity'),
    floorOpacityLabel: $('photo-floor-opacity-label'),
    floorOffset:       $('photo-floor-offset'),
    floorOffsetLabel:  $('photo-floor-offset-label'),
    keyIntensity:        $('photo-key-intensity'),
    keyIntensityLabel:   $('photo-key-intensity-label'),
    fillIntensity:       $('photo-fill-intensity'),
    fillIntensityLabel:  $('photo-fill-intensity-label'),
    ambientIntensity:      $('photo-ambient-intensity'),
    ambientIntensityLabel: $('photo-ambient-intensity-label'),
    maxContrast: $('photo-max-contrast'),
    shadowDepth: $('photo-shadow-depth'),
    outline:            $('photo-outline'),
    outlineControls:    $('photo-outline-controls'),
    outlineColor:       $('photo-outline-color'),
    outlineStrength:    $('photo-outline-strength'),
    outlineStrengthLab: $('photo-outline-strength-label'),
    outlineThickness:   $('photo-outline-thickness'),
    outlineThicknessLab:$('photo-outline-thickness-label'),
    outlineJump:        $('photo-outline-jump'),
    outlineJumpLab:     $('photo-outline-jump-label'),
    depthCue:           $('photo-depthcue'),
    depthCueControls:   $('photo-depthcue-controls'),
    depthCueColor:      $('photo-depthcue-color'),
    depthCueStrength:   $('photo-depthcue-strength'),
    depthCueStrengthLab:$('photo-depthcue-strength-label'),
    matFull:      $('photo-mat-full'),
    matCylinders: $('photo-mat-cylinders'),
    matSurface:   $('photo-mat-surface'),
    matAtomistic: $('photo-mat-atomistic'),
    fov:        $('photo-fov'),
    fovLabel:   $('photo-fov-label'),
    fovReset:   $('photo-fov-reset'),
    parallel:   $('photo-parallel'),
    resPreset:  $('photo-res-preset'),
    resW:       $('photo-res-w'),
    resH:       $('photo-res-h'),
    exportNote: $('photo-export-note'),
    exportBtn:  $('photo-export-btn'),
    animSelect:  $('photo-anim-select'),
    videoRes:    $('photo-video-res'),
    videoFormat: $('photo-video-format'),
    videoFps:    $('photo-video-fps'),
    videoNote:   $('photo-video-note'),
    videoBtn:    $('photo-video-btn'),
    bgType:  $('photo-bg-type'),
    bgColor: $('photo-bg-color'),
    profileSelect: $('photo-profile-select'),
    profileNew:    $('photo-profile-new'),
    profileRename: $('photo-profile-rename'),
    profileDelete: $('photo-profile-delete'),
    profileReset:  $('photo-profile-reset'),
    profileStatus: $('photo-profile-status'),
  }

  let _statusTimer = null
  let _persistTimer = null
  const factorySettings = photoMode.getSettings()

  function _applyProfile(settings) {
    if (!settings) return
    const call = (key, method, ...args) => {
      if (settings[key] !== undefined) photoMode[method]?.(settings[key], ...args)
    }
    for (const repr of ['full', 'cylinders', 'surface', 'atomistic']) {
      if (settings[repr] !== undefined) photoMode.setMaterialPreset(repr, settings[repr])
    }
    if (settings.bgType !== undefined || settings.bgColor !== undefined) {
      photoMode.setBackground(settings.bgType, settings.bgColor)
    }
    call('pinLights', 'setPinLights')
    call('studioEnvironment', 'setStudioEnvironment')
    call('studioEnvironmentIntensity', 'setStudioEnvironmentIntensity')
    call('studioEnvironmentRotation', 'setStudioEnvironmentRotation')
    call('keyShadowMapSize', 'setKeyShadowMapSize')
    call('keyShadowBias', 'setKeyShadowBias')
    call('shadowStrength', 'setShadowStrength')
    call('keyAzimuth', 'setKeyAzimuth')
    call('keyElevation', 'setKeyElevation')
    call('keyIntensity', 'setKeyIntensity')
    call('fillIntensity', 'setFillIntensity')
    call('ambientIntensity', 'setAmbientIntensity')
    call('keyShadow', 'setKeyShadow')
    call('floorAxis', 'setFloorAxis')
    call('floorOpacity', 'setFloorOpacity')
    call('floorOffset', 'setFloorOffset')
    call('floor', 'setFloor')
    call('outlineColor', 'setOutlineColor')
    call('outlineStrength', 'setOutlineStrength')
    call('outlineThickness', 'setOutlineThickness')
    call('outlineDepthJump', 'setOutlineDepthJump')
    call('outline', 'setOutline')
    call('depthCueColor', 'setDepthCueColor')
    call('depthCueStrength', 'setDepthCueStrength')
    call('depthCue', 'setDepthCue')
    if (settings.fov != null) photoMode.setFOV(settings.fov)
    else if (settings.parallel !== undefined) photoMode.setParallel(settings.parallel)
    if (settings.exportWidth !== undefined || settings.exportHeight !== undefined) {
      photoMode.setExportSize(settings.exportWidth, settings.exportHeight)
    }
    syncToState()
  }

  function _populateProfiles() {
    if (!els.profileSelect) return
    const profiles = loadPhotoProfiles()
    const active = _activeProfileName()
    els.profileSelect.innerHTML = ''
    for (const name of Object.keys(profiles).sort((a, b) => a.localeCompare(b))) {
      const option = document.createElement('option')
      option.value = name
      option.textContent = name
      option.selected = name === active
      els.profileSelect.appendChild(option)
    }
    if (els.profileStatus) els.profileStatus.textContent = active ? `Active: ${active} · changes save automatically` : ''
  }

  function _ensureProfile() {
    const profiles = loadPhotoProfiles()
    const names = Object.keys(profiles)
    if (!names.length) {
      profiles.Default = { ...factorySettings }
      _savePhotoProfiles(profiles)
      _setActiveProfileName('Default')
    } else if (!profiles[_activeProfileName()]) {
      _setActiveProfileName(names.sort()[0])
    }
    _populateProfiles()
  }

  function _persistActiveProfile() {
    const name = _activeProfileName()
    if (!name) return
    const profiles = loadPhotoProfiles()
    profiles[name] = photoMode.getSettings()
    _savePhotoProfiles(profiles)
    if (els.profileStatus) els.profileStatus.textContent = `Active: ${name} · saved`
  }

  function _schedulePersist() {
    clearTimeout(_persistTimer)
    _persistTimer = setTimeout(() => { _persistTimer = null; _persistActiveProfile() }, 250)
  }

  _ensureProfile()

  els.profileSelect?.addEventListener('change', () => {
    const name = els.profileSelect.value
    if (!name) return
    _setActiveProfileName(name)
    _applyProfile(loadPhotoProfiles()[name])
    _populateProfiles()
  })

  els.profileNew?.addEventListener('click', async () => {
    const profiles = loadPhotoProfiles()
    const name = prompt('New profile name:', `Profile ${Object.keys(profiles).length + 1}`)?.trim()
    if (!name) return
    if (profiles[name] && !await showConfirm({ title: 'Overwrite profile', message: `Profile "${name}" already exists. Overwrite?`, confirmLabel: 'Overwrite' })) return
    profiles[name] = photoMode.getSettings()
    _savePhotoProfiles(profiles)
    _setActiveProfileName(name)
    _populateProfiles()
  })

  els.profileRename?.addEventListener('click', async () => {
    const oldName = _activeProfileName()
    const name = prompt(`Rename "${oldName}" to:`, oldName)?.trim()
    if (!oldName || !name || name === oldName) return
    const profiles = loadPhotoProfiles()
    if (profiles[name] && !await showConfirm({ title: 'Overwrite profile', message: `Profile "${name}" already exists. Overwrite?`, confirmLabel: 'Overwrite' })) return
    profiles[name] = profiles[oldName]
    delete profiles[oldName]
    _savePhotoProfiles(profiles)
    _setActiveProfileName(name)
    _populateProfiles()
  })

  els.profileDelete?.addEventListener('click', async () => {
    const name = _activeProfileName()
    if (!name || !await showConfirm({ title: 'Delete profile', message: `Delete profile "${name}"?`, confirmLabel: 'Delete', danger: true })) return
    const profiles = loadPhotoProfiles()
    delete profiles[name]
    const next = Object.keys(profiles).sort()[0]
    if (next) {
      _setActiveProfileName(next)
      _applyProfile(profiles[next])
    } else {
      profiles.Default = { ...factorySettings }
      _setActiveProfileName('Default')
      _applyProfile(profiles.Default)
    }
    _savePhotoProfiles(profiles)
    _populateProfiles()
  })

  els.profileReset?.addEventListener('click', async () => {
    if (!await showConfirm({ title: 'Reset Photomode profile', message: 'Reset the active profile to Photomode defaults?', confirmLabel: 'Reset' })) return
    _applyProfile(factorySettings)
    _persistActiveProfile()
  })

  // All ordinary controls bubble input/change after their renderer setter runs.
  // This keeps the active profile current without duplicating persistence in
  // every individual control handler.
  const _persistFromControl = event => {
    if (!event.target?.id?.startsWith('photo-') || event.target.id.startsWith('photo-profile-')) return
    _schedulePersist()
  }
  for (const eventName of ['input', 'change']) {
    document.addEventListener(eventName, _persistFromControl)
  }

  function _refreshStatus() {
    if (els.status) els.status.textContent = formatShadowStatus(photoMode.getStatus())
  }

  function _refreshResolution() {
    if (!els.keyShadowRes) return
    const s = photoMode.getSettings()
    const r = shadowResolution(photoMode.getStatus()?.radius ?? 0, s.keyShadowMapSize)
    els.keyShadowRes.textContent = (!r.ok && r.nmPerTexel > 0)
      ? `${r.nmPerTexel.toFixed(2)} nm/texel — COARSER than a ${DUPLEX_NM} nm duplex `
        + `(${r.duplexes.toFixed(1)} texels across one). Raise the map size or the shadow `
        + `will be a wash, not a cast shadow.`
      : `${r.nmPerTexel.toFixed(3)} nm/texel (${r.duplexes.toFixed(1)} texels across a ${DUPLEX_NM} nm duplex).`
  }

  /** Poll while active — the rig refits inside the render loop, so there is no
   *  event to hang this off. */
  function _startStatusPolling() {
    _stopStatusPolling()
    _statusTimer = setInterval(() => { _refreshStatus(); _refreshResolution() }, 500)
    _refreshStatus()
    _refreshResolution()
  }

  function _stopStatusPolling() {
    if (_statusTimer) { clearInterval(_statusTimer); _statusTimer = null }
    _refreshStatus()
  }

  /** Push every control's current value into the UI from the controller. */
  function syncToState() {
    const s = photoMode.getSettings()
    if (els.pinLights) els.pinLights.checked = s.pinLights
    if (els.studioEnvironment) els.studioEnvironment.checked = s.studioEnvironment
    if (els.studioEnvironmentControls) {
      els.studioEnvironmentControls.style.display = s.studioEnvironment ? 'flex' : 'none'
    }
    if (els.studioEnvironmentIntensity) {
      els.studioEnvironmentIntensity.value = String(s.studioEnvironmentIntensity)
    }
    if (els.studioEnvironmentIntensityLabel) {
      els.studioEnvironmentIntensityLabel.textContent = s.studioEnvironmentIntensity.toFixed(2)
    }
    if (els.studioEnvironmentRotation) {
      els.studioEnvironmentRotation.value = String(s.studioEnvironmentRotation)
    }
    if (els.studioEnvironmentRotationLabel) {
      els.studioEnvironmentRotationLabel.textContent = `${s.studioEnvironmentRotation.toFixed(0)}°`
    }
    if (els.keyShadow) els.keyShadow.checked = s.keyShadow
    if (els.keyShadowMapSize)   els.keyShadowMapSize.value = String(s.keyShadowMapSize)
    if (els.keyShadowBias)      els.keyShadowBias.value = String(s.keyShadowBias)
    if (els.keyShadowBiasLabel) els.keyShadowBiasLabel.textContent = `${s.keyShadowBias.toFixed(1)}×`
    if (els.shadowStrength)      els.shadowStrength.value = String(s.shadowStrength)
    if (els.shadowStrengthLabel) els.shadowStrengthLabel.textContent = s.shadowStrength.toFixed(2)
    if (els.keyShadowControls)  els.keyShadowControls.style.display = s.keyShadow ? 'flex' : 'none'
    if (els.floor) els.floor.checked = s.floor
    if (els.floorControls) els.floorControls.style.display = s.floor ? 'flex' : 'none'
    if (els.floorAxis)         els.floorAxis.value = s.floorAxis
    if (els.floorOpacity)      els.floorOpacity.value = String(s.floorOpacity)
    if (els.floorOpacityLabel) els.floorOpacityLabel.textContent = s.floorOpacity.toFixed(2)
    if (els.floorOffset)       els.floorOffset.value = String(s.floorOffset)
    if (els.floorOffsetLabel)  els.floorOffsetLabel.textContent = `${s.floorOffset.toFixed(1)} nm`
    for (const [k, el, lab] of [
      ['shadowStrength',   els.shadowStrength,   els.shadowStrengthLabel],
      ['keyIntensity',     els.keyIntensity,     els.keyIntensityLabel],
      ['fillIntensity',    els.fillIntensity,    els.fillIntensityLabel],
      ['ambientIntensity', els.ambientIntensity, els.ambientIntensityLabel],
    ]) {
      if (el)  el.value = String(s[k])
      if (lab) lab.textContent = s[k].toFixed(2)
    }
    if (els.keyAzimuth)        els.keyAzimuth.value = String(s.keyAzimuth)
    if (els.keyAzimuthLabel)   els.keyAzimuthLabel.textContent = `${s.keyAzimuth.toFixed(0)}°`
    if (els.keyElevation)      els.keyElevation.value = String(s.keyElevation)
    if (els.keyElevationLabel) els.keyElevationLabel.textContent = `${s.keyElevation.toFixed(0)}°`
    _refreshKeyDir()
    _refreshShadowDepth()
    if (els.outline)  els.outline.checked = s.outline
    if (els.depthCue) els.depthCue.checked = s.depthCue
    if (els.outlineControls)  els.outlineControls.style.display  = s.outline  ? 'flex' : 'none'
    if (els.depthCueControls) els.depthCueControls.style.display = s.depthCue ? 'flex' : 'none'
    if (els.outlineColor)  els.outlineColor.value  = s.outlineColor
    if (els.depthCueColor) els.depthCueColor.value = s.depthCueColor
    for (const [k, el, lab, dp] of [
      ['outlineStrength',          els.outlineStrength,  els.outlineStrengthLab,  2],
      ['outlineThickness',         els.outlineThickness, els.outlineThicknessLab, 1],
      ['outlineDepthJump',         els.outlineJump,      els.outlineJumpLab,      3],
      ['depthCueStrength',         els.depthCueStrength, els.depthCueStrengthLab, 2],
    ]) {
      if (!Number.isFinite(s[k])) continue   // a settings blob predating this control
      if (el)  el.value = String(s[k])
      if (lab) lab.textContent = s[k].toFixed(dp)
    }
    for (const [repr, sel] of MAT_ROWS) if (sel) sel.value = s[repr]
    if (els.fov && s.fov != null) {
      els.fov.value = String(Math.round(s.fov))
      if (els.fovLabel) els.fovLabel.textContent = `${Math.round(s.fov)}°`
    }
    if (els.parallel) els.parallel.checked = s.parallel
    if (els.resW) els.resW.value = String(s.exportWidth)
    if (els.resH) els.resH.value = String(s.exportHeight)
    _refreshExportNote()
    if (els.bgType)  els.bgType.value = s.bgType
    if (els.bgColor) els.bgColor.value = s.bgColor
    _refreshResolution()
    _refreshStatus()
  }

  /** Where the light is, in words, plus the angle off the camera axis — which
   *  is what decides whether the shadow reads as offset or hides behind the
   *  object. It is exactly `90 - elevation`. */
  function _refreshKeyDir() {
    if (!els.keyDir) return
    const s = photoMode.getSettings()
    const az = ((s.keyAzimuth % 360) + 360) % 360
    const side =
      az < 22.5 || az >= 337.5 ? 'right' :
      az < 67.5   ? 'upper-right' :
      az < 112.5  ? 'above' :
      az < 157.5  ? 'upper-left' :
      az < 202.5  ? 'left' :
      az < 247.5  ? 'lower-left' :
      az < 292.5  ? 'below' : 'lower-right'
    const off = 90 - s.keyElevation
    els.keyDir.textContent = s.keyElevation >= 0
      ? `Lit from the ${side}, ${off.toFixed(0)}° off the camera axis.`
      : `Lit from behind (${side}), ${off.toFixed(0)}° off the camera axis — rim light.`
  }

  function _refreshShadowDepth() {
    if (!els.shadowDepth) return
    const s = photoMode.getSettings()
    const pct = Math.round(shadowDepthFraction(s) * 100)
    els.shadowDepth.textContent =
      `A cast shadow removes ${pct}% of the light here (key ${s.keyIntensity.toFixed(2)} of `
      + `${(s.keyIntensity + s.fillIntensity + s.ambientIntensity).toFixed(2)} total). `
      + `Lower Fill and Diffuse ambient to deepen it.`
      + (s.studioEnvironment
        ? ' Studio reflections add non-shadowing PBR fill, especially on metal.'
        : '')
  }

  /** Bind an intensity slider → setter → label → readout. */
  function _bindIntensity(el, label, setter) {
    el?.addEventListener('input', () => {
      const v = Number(el.value)
      setter(v)
      if (label) label.textContent = v.toFixed(2)
      _refreshShadowDepth()
    })
  }

  // ── Wiring ─────────────────────────────────────────────────────────────────

  els.exit?.addEventListener('click', () => onExit?.())


  els.pinLights?.addEventListener('change', () => photoMode.setPinLights(els.pinLights.checked))

  els.studioEnvironment?.addEventListener('change', () => {
    photoMode.setStudioEnvironment(els.studioEnvironment.checked)
    if (els.studioEnvironmentControls) {
      els.studioEnvironmentControls.style.display = els.studioEnvironment.checked ? 'flex' : 'none'
    }
    _refreshShadowDepth()
  })

  els.studioEnvironmentIntensity?.addEventListener('input', () => {
    const v = Number(els.studioEnvironmentIntensity.value)
    photoMode.setStudioEnvironmentIntensity(v)
    if (els.studioEnvironmentIntensityLabel) {
      els.studioEnvironmentIntensityLabel.textContent = v.toFixed(2)
    }
  })

  els.studioEnvironmentRotation?.addEventListener('input', () => {
    const v = Number(els.studioEnvironmentRotation.value)
    photoMode.setStudioEnvironmentRotation(v)
    if (els.studioEnvironmentRotationLabel) {
      els.studioEnvironmentRotationLabel.textContent = `${v.toFixed(0)}°`
    }
  })

  els.keyShadow?.addEventListener('change', () => {
    photoMode.setKeyShadow(els.keyShadow.checked)
    if (els.keyShadowControls) {
      els.keyShadowControls.style.display = els.keyShadow.checked ? 'flex' : 'none'
    }
    _refreshStatus()
  })

  els.keyShadowMapSize?.addEventListener('change', () => {
    photoMode.setKeyShadowMapSize(Number(els.keyShadowMapSize.value))
    _refreshResolution()
  })

  els.keyShadowBias?.addEventListener('input', () => {
    const v = Number(els.keyShadowBias.value)
    photoMode.setKeyShadowBias(v)
    if (els.keyShadowBiasLabel) els.keyShadowBiasLabel.textContent = `${v.toFixed(1)}×`
  })

  els.shadowStrength?.addEventListener('input', () => {
    const v = Number(els.shadowStrength.value)
    photoMode.setShadowStrength(v)
    if (els.shadowStrengthLabel) els.shadowStrengthLabel.textContent = v.toFixed(2)
  })

  els.floor?.addEventListener('change', () => {
    photoMode.setFloor(els.floor.checked)
    if (els.floorControls) els.floorControls.style.display = els.floor.checked ? 'flex' : 'none'
  })

  els.floorAxis?.addEventListener('change', () => photoMode.setFloorAxis(els.floorAxis.value))

  els.floorOpacity?.addEventListener('input', () => {
    const v = Number(els.floorOpacity.value)
    photoMode.setFloorOpacity(v)
    if (els.floorOpacityLabel) els.floorOpacityLabel.textContent = v.toFixed(2)
  })

  els.floorOffset?.addEventListener('input', () => {
    const v = Number(els.floorOffset.value)
    photoMode.setFloorOffset(v)
    if (els.floorOffsetLabel) els.floorOffsetLabel.textContent = `${v.toFixed(1)} nm`
  })

  for (const [el, lab, setter, unit] of [
    [els.keyAzimuth,   els.keyAzimuthLabel,   v => photoMode.setKeyAzimuth(v),   '°'],
    [els.keyElevation, els.keyElevationLabel, v => photoMode.setKeyElevation(v), '°'],
  ]) {
    el?.addEventListener('input', () => {
      const v = Number(el.value)
      setter(v)
      if (lab) lab.textContent = `${v.toFixed(0)}${unit}`
      _refreshKeyDir()
    })
  }

  _bindIntensity(els.keyIntensity,     els.keyIntensityLabel,     v => photoMode.setKeyIntensity(v))
  _bindIntensity(els.fillIntensity,    els.fillIntensityLabel,    v => photoMode.setFillIntensity(v))
  _bindIntensity(els.ambientIntensity, els.ambientIntensityLabel, v => photoMode.setAmbientIntensity(v))
  _bindIntensity(els.shadowStrength,   els.shadowStrengthLabel,   v => photoMode.setShadowStrength(v))

  els.maxContrast?.addEventListener('click', () => {
    photoMode.setKeyIntensity(2.0)
    photoMode.setFillIntensity(0)
    photoMode.setAmbientIntensity(0.15)
    syncToState()
    _schedulePersist()
  })

  els.bgType?.addEventListener('change', () => {
    photoMode.setBackground(els.bgType.value, undefined)
    if (els.bgColor) els.bgColor.disabled = els.bgType.value === 'transparent'
  })

  els.bgColor?.addEventListener('input', () => photoMode.setBackground(undefined, els.bgColor.value))

  // ── Collapsible cards ──────────────────────────────────────────────────────
  // Same markup, classes and persistence as the Simulations-tab cards: a clickable
  // <h2> with a rotating chevron and a sibling body div, with per-tab collapse state
  // in localStorage.
  function _initCard(id) {
    const heading = $(`photo-${id}-heading`)
    const body    = $(`photo-${id}-body`)
    const arrow   = $(`photo-${id}-arrow`)
    if (!heading || !body) return
    let collapsed = getSectionCollapsed('photo', `photo-${id}-panel`, false)
    body.style.display = collapsed ? 'none' : ''
    arrow?.classList.toggle('is-collapsed', collapsed)
    heading.addEventListener('click', () => {
      collapsed = !collapsed
      body.style.display = collapsed ? 'none' : ''
      arrow?.classList.toggle('is-collapsed', collapsed)
      setSectionCollapsed('photo', `photo-${id}-panel`, collapsed)
    })
  }
  // Material dropdowns are built from PRESET_LABELS so adding a preset to
  // material_presets.js shows up here with no markup change.
  const MAT_ROWS = [
    ['full',      els.matFull],
    ['cylinders', els.matCylinders],
    ['surface',   els.matSurface],
    ['atomistic', els.matAtomistic],
  ]
  for (const [repr, sel] of MAT_ROWS) {
    if (!sel) continue
    sel.innerHTML = ''
    for (const [value, label] of Object.entries(PRESET_LABELS[repr] ?? {})) {
      const o = document.createElement('option')
      o.value = value
      o.textContent = label
      sel.appendChild(o)
    }
    sel.addEventListener('change', () => photoMode.setMaterialPreset(repr, sel.value))
  }

  els.outline?.addEventListener('change', () => {
    photoMode.setOutline(els.outline.checked)
    if (els.outlineControls) els.outlineControls.style.display = els.outline.checked ? 'flex' : 'none'
  })
  els.depthCue?.addEventListener('change', () => {
    photoMode.setDepthCue(els.depthCue.checked)
    if (els.depthCueControls) els.depthCueControls.style.display = els.depthCue.checked ? 'flex' : 'none'
  })
  els.outlineColor?.addEventListener('input', () => photoMode.setOutlineColor(els.outlineColor.value))
  els.depthCueColor?.addEventListener('input', () => photoMode.setDepthCueColor(els.depthCueColor.value))

  /** slider → setter → label, with a fixed number of decimals. */
  function _bindRange(el, lab, setter, dp = 2) {
    el?.addEventListener('input', () => {
      const v = Number(el.value)
      setter(v)
      if (lab) lab.textContent = v.toFixed(dp)
    })
  }
  _bindRange(els.outlineStrength,  els.outlineStrengthLab,  v => photoMode.setOutlineStrength(v))
  _bindRange(els.outlineThickness, els.outlineThicknessLab, v => photoMode.setOutlineThickness(v), 1)
  _bindRange(els.outlineJump,      els.outlineJumpLab,      v => photoMode.setOutlineDepthJump(v), 3)
  _bindRange(els.depthCueStrength, els.depthCueStrengthLab, v => photoMode.setDepthCueStrength(v))

  // ── Camera ─────────────────────────────────────────────────────────────────
  els.fov?.addEventListener('input', () => {
    const v = Number(els.fov.value)
    photoMode.setFOV(v)
    if (els.fovLabel) els.fovLabel.textContent = `${v}°`
    if (els.parallel) els.parallel.checked = photoMode.getSettings().parallel
  })
  els.fovReset?.addEventListener('click', () => {
    photoMode.resetFOV()
    syncToState()          // slider, label and the Parallel checkbox all follow
  })
  els.parallel?.addEventListener('change', () => {
    photoMode.setParallel(els.parallel.checked)
    syncToState()
  })

  // ── Export ─────────────────────────────────────────────────────────────────
  // A 14×9.9 in figure at the named DPI. 300 DPI already exceeds the 4096
  // MAX_TEXTURE_SIZE common on WSL/integrated GPUs, which is why the export is
  // tiled rather than one oversized render target.
  const RES_PRESETS = {
    screen: () => [window.innerWidth, window.innerHeight],
    x2:     () => [window.innerWidth * 2, window.innerHeight * 2],
    p300:   () => [4200, 2970],
    p600:   () => [8400, 5940],
  }

  function _refreshExportNote() {
    if (!els.exportNote) return
    const w = Number(els.resW?.value ?? 0)
    const h = Number(els.resH?.value ?? 0)
    if (!(w > 0 && h > 0)) { els.exportNote.textContent = ''; return }
    const tiles = Math.max(1, Math.ceil(w / 4096)) * Math.max(1, Math.ceil(h / 4096))
    const inches = (w / 300).toFixed(1)
    els.exportNote.textContent =
      `${w}×${h} px — ${inches} in wide at 300 DPI, rendered in ${tiles} tile${tiles === 1 ? '' : 's'}.`
  }

  function _applyResPreset(key) {
    const fn = RES_PRESETS[key]
    if (!fn) { _refreshExportNote(); return }
    const [w, h] = fn().map(Math.round)
    if (els.resW) els.resW.value = String(w)
    if (els.resH) els.resH.value = String(h)
    photoMode.setExportSize(w, h)
    _refreshExportNote()
  }

  els.resPreset?.addEventListener('change', () => _applyResPreset(els.resPreset.value))
  for (const el of [els.resW, els.resH]) {
    el?.addEventListener('change', () => {
      if (els.resPreset) els.resPreset.value = 'custom'
      photoMode.setExportSize(Number(els.resW.value), Number(els.resH.value))
      _refreshExportNote()
    })
  }

  els.exportBtn?.addEventListener('click', async () => {
    if (!els.exportBtn) return
    const label = els.exportBtn.textContent
    els.exportBtn.disabled = true
    els.exportBtn.textContent = 'Rendering…'
    try {
      const s = photoMode.getSettings()
      const blob = await photoMode.renderToBlob(s.exportWidth, s.exportHeight)
      if (blob) {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `nadoc-figure-${s.exportWidth}x${s.exportHeight}.png`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      console.error('[photo] export failed:', err)
      if (els.exportNote) els.exportNote.textContent = `Export failed: ${err.message}`
    } finally {
      els.exportBtn.disabled = false
      els.exportBtn.textContent = label
    }
  })

  // ── Video export ────────────────────────────────────────────────────────────
  // Renders a saved animation frame-by-frame through the SAME photo pipeline as
  // the PNG button, via one long-lived offscreen session. It lives on this tab
  // rather than the Animations tab because photo mode has to be ACTIVE to render
  // and the sidebar exits it on any switch to a non-photo tab.

  /** Animations live on the design/assembly itself — same source the animation panel reads. */
  function _animations() {
    const s = store?.getState?.()
    return s?.currentAssembly?.animations ?? s?.currentDesign?.animations ?? []
  }

  function _selectedAnim() {
    const id = els.animSelect?.value
    return _animations().find(a => a.id === id) ?? null
  }

  function _videoSize() {
    return VIDEO_RES_PRESETS[els.videoRes?.value] ?? VIDEO_RES_PRESETS['1080p']
  }

  function _refreshVideoNote() {
    if (!els.videoNote) return
    const anim = _selectedAnim()
    if (!anim) {
      els.videoNote.textContent = _animations().length
        ? 'Pick an animation.'
        : 'No saved animations — author one in the Animations tab.'
      if (els.videoBtn) els.videoBtn.disabled = true
      return
    }
    const [w, h] = _videoSize()
    const fpsVal = parseInt(els.videoFps?.value)
    const fps = Number.isFinite(fpsVal) && fpsVal > 0 ? fpsVal : (anim.fps ?? 30)
    const plan = videoPlan({ durationS: animationDuration(anim), fps, width: w, height: h })
    // A trajectory keyframe is RESAMPLED onto the capture grid, so fps decides how much
    // of the simulation reaches the file. Say so here rather than let the user discover
    // it as "the motion looks coarser than the run was" after an hours-long render.
    const warn = _samplingWarning(anim, fps)
    els.videoNote.textContent = !plan.frames
      ? 'Animation has no duration — check keyframe timings.'
      : warn ? `${plan.text}  ·  ${warn}` : plan.text
    els.videoNote.style.color = plan.frames && warn ? '#e3b341' : ''
    if (els.videoBtn) els.videoBtn.disabled = !plan.frames
  }

  /** One-line warning when `fps` cannot show every simulated frame of a trajectory
   *  keyframe, or '' when it can. Silent until the trajectory has been loaded at least
   *  once — guessing a frame count would be worse than saying nothing. */
  function _samplingWarning(anim, fps) {
    if (!anim || !trajectoryKeyframes) return ''
    const plan = trajectorySamplingPlan(
      anim, (jobId) => trajectoryKeyframes.frameCount?.(jobId) ?? 0, fps)
    if (plan.ok || !plan.worst) return ''
    const w = plan.worst
    return `⚠ shows ${w.shown} of ${w.frames} simulated frames — use ${plan.minFps} fps`
  }

  /** Rebuild the picker, preserving the selection when the list is unchanged. */
  function _refreshAnimList() {
    if (!els.animSelect) return
    const anims = _animations()
    const prev  = els.animSelect.value
    els.animSelect.innerHTML = ''
    for (const a of anims) {
      const opt = document.createElement('option')
      opt.value = a.id
      opt.textContent = a.name || 'Animation'
      els.animSelect.appendChild(opt)
    }
    if (anims.some(a => a.id === prev)) els.animSelect.value = prev
    // A fresh pick adopts that animation's own fps, the way the Animations tab does.
    const anim = _selectedAnim()
    if (anim && els.videoFps && anim.id !== prev) els.videoFps.value = String(anim.fps ?? 30)
    _refreshVideoNote()
  }

  els.animSelect?.addEventListener('change', () => {
    const anim = _selectedAnim()
    if (anim && els.videoFps) els.videoFps.value = String(anim.fps ?? 30)
    _refreshVideoNote()
  })
  for (const el of [els.videoRes, els.videoFormat, els.videoFps]) {
    el?.addEventListener('change', _refreshVideoNote)
  }
  els.videoFps?.addEventListener('input', _refreshVideoNote)

  els.videoBtn?.addEventListener('click', async () => {
    const anim = _selectedAnim()
    if (!anim || !player || !exportPhotoVideo) return
    const [width, height] = _videoSize()
    const fpsVal = parseInt(els.videoFps?.value)
    const format = els.videoFormat?.value ?? 'webm'

    const label = els.videoBtn.textContent
    els.videoBtn.disabled = true
    els.videoBtn.textContent = 'Rendering…'

    // One session owns the popup for the whole run — the bake that happens inside
    // exportPhotoVideo's `player.play()` (geometry, trajectory download, surface
    // frame prebuild) reports into these same phases via the animation panel's
    // player-event handler. Before this it opened a SECOND op-progress on top,
    // which retitled this popup and replaced its Cancel with the bake's.
    const cancelCtl = new AbortController()
    const session = beginExportSession({
      header: 'Exporting Video',
      phases: planExportPhases({
        hasTrajectory:  trajectoryJobs(anim).size > 0,
        hasHeavyFrames: player.hasHeavyRep?.() ?? false,
        format,
      }),
      onCancel: () => { cancelCtl.abort(); player.cancelBake?.() },
      onStatus: (u) => { if (els.videoNote) els.videoNote.textContent = u.text },
    })
    try {
      await exportPhotoVideo({
        animation: anim,
        player,
        photoRenderer: photoMode,
        width, height,
        options: { format, fps: Number.isFinite(fpsVal) && fpsVal > 0 ? fpsVal : undefined },
        signal: cancelCtl.signal,
        onPhase: (key, info = null) => {
          if (info?.total != null) session.tick(key, info.done, info.total)
          else session.begin(key)
        },
      })
      session.finish()
      if (els.videoNote) els.videoNote.textContent = 'Done.'
    } catch (err) {
      if (err?.name === 'AbortError') {
        if (els.videoNote) els.videoNote.textContent = 'Cancelled.'
      } else {
        console.error('[photo] video export failed:', err)
        if (els.videoNote) els.videoNote.textContent = `Export failed: ${err.message}`
      }
    } finally {
      endExportSession()
      els.videoBtn.disabled = false
      els.videoBtn.textContent = label
    }
  })

  _initCard('lighting')
  _initCard('camera')
  _initCard('export')
  _initCard('figure')
  // No 'bg' card — the background controls moved INTO the Figure card, where
  // they belong: the depth cue fades toward that colour and the silhouette
  // deliberately paints onto background pixels.
  _initCard('materials')

  els.keyDirReset?.addEventListener('click', () => {
    photoMode.resetKeyDirection()
    syncToState()
    _schedulePersist()
  })

  return {
    syncToState,
    applyActiveProfile: () => _applyProfile(loadPhotoProfiles()[_activeProfileName()]),
    onEnter: () => { _applyProfile(loadPhotoProfiles()[_activeProfileName()]); _refreshAnimList(); _startStatusPolling() },
    onExit:  () => { _stopStatusPolling() },
    dispose: () => {
      _stopStatusPolling()
      clearTimeout(_persistTimer)
      for (const eventName of ['input', 'change']) document.removeEventListener(eventName, _persistFromControl)
    },
  }
}
