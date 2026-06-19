/**
 * Photo mode panel — left-panel "Photo" tab.
 *
 * Wires DOM controls defined in #tab-content-photo (index.html) to the
 * photoRenderer instance.  No HTML is created here; all elements are
 * declared in the template and looked up by ID.
 *
 * Usage:
 *   import { initPhotoPanel } from './ui/photo_panel.js'
 *   initPhotoPanel(photoRenderer, sceneCtx, { onEnter, onExit })
 */

// ── Resolution presets ────────────────────────────────────────────────────────

// Width × height at 1× pixel ratio.  DPI assumes 88 mm (3.46") single-column width.
const RESOLUTION_PRESETS = {
  screen: { label: 'Screen (1×)', w: null, h: null, dpi: null },   // null = use canvas size
  x2:     { label: '2× (slides)',  w: null, h: null, scale: 2, dpi: 130 },
  p300:   { label: 'Print 300 DPI', w: 4200, h: 2970, dpi: 300 },
  p600:   { label: 'Print 600 DPI', w: 8400, h: 5940, dpi: 600 },
  custom: { label: 'Custom',        w: null, h: null, dpi: null },
}

// ── Profiles (persisted across reloads) ───────────────────────────────────────

const PROFILES_KEY        = 'nadoc.photoProfiles.v1'
const ACTIVE_PROFILE_KEY  = 'nadoc.photoActiveProfile.v1'
// One-time flag: the photo-mode default environment changed 'off' → 'room'.
const ENV_ROOM_MIGRATION_KEY = 'nadoc.photoEnvRoomDefault.v1'

function _loadProfiles() {
  try { return JSON.parse(localStorage.getItem(PROFILES_KEY) || '{}') }
  catch { return {} }
}
function _saveProfiles(p) {
  try { localStorage.setItem(PROFILES_KEY, JSON.stringify(p)) } catch {}
}

// The default photo environment is now a neutral 'room' studio so metallic/glossy
// materials reflect and look correct.  Existing saved profiles pinned to the OLD
// 'off' default would otherwise override that and keep metals flat — bump them to
// 'room' exactly once.  Runs before any deliberate 'off' choice can be made, so a
// user who later picks 'off' on purpose keeps it (the flag stops re-migration).
function _migrateEnvDefaultToRoom() {
  if (localStorage.getItem(ENV_ROOM_MIGRATION_KEY)) return
  const profiles = _loadProfiles()
  let changed = false
  for (const s of Object.values(profiles)) {
    if (s && s.environment === 'off') { s.environment = 'room'; changed = true }
  }
  if (changed) _saveProfiles(profiles)
  try { localStorage.setItem(ENV_ROOM_MIGRATION_KEY, '1') } catch {}
}
function _getActiveProfileName() {
  return localStorage.getItem(ACTIVE_PROFILE_KEY) || ''
}
function _setActiveProfileName(name) {
  try { localStorage.setItem(ACTIVE_PROFILE_KEY, name) } catch {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _el(id) { return document.getElementById(id) }

function _download(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a   = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function _fmt(n) { return n ? n.toLocaleString() : '—' }

// ── Main initialiser ──────────────────────────────────────────────────────────

/**
 * @param {object} photoRenderer   — returned by createPhotoRenderer()
 * @param {object} sceneCtx        — { camera, renderer }
 * @param {object} callbacks
 * @param {function} callbacks.onEnter  — called when user enters photo mode
 * @param {function} callbacks.onExit   — called when user exits photo mode
 * @param {object}   [callbacks.store]            — global store (for animation list)
 * @param {object}   [callbacks.player]           — initAnimationPlayer instance
 * @param {function} [callbacks.exportPhotoVideo] — high-res video exporter
 */

import { showConfirm } from './primitives/confirm.js'

export function initPhotoPanel(photoRenderer, sceneCtx, { onEnter, onExit, store, player, exportPhotoVideo, withExportRepresentation, setExportRepresentation }) {
  // Run the export render `fn` with the assembly's chosen export representation
  // temporarily applied (no-op wrapper if main.js didn't inject one).
  const _withExportRep = withExportRepresentation ?? (async (fn) => fn())
  // ── Element refs ────────────────────────────────────────────────────────────
  const exitBtn      = _el('photo-exit-btn')
  const exportBtn    = _el('photo-export-btn')
  const exportRepSel = _el('photo-export-rep')
  const profileSel    = _el('photo-profile-select')
  const profileNew    = _el('photo-profile-new')
  const profileRename = _el('photo-profile-rename')
  const profileDelete = _el('photo-profile-delete')
  const profileStatus = _el('photo-profile-status')
  const lightingSel  = _el('photo-lighting-select')
  const bgRadios     = document.querySelectorAll('input[name="photo-bg"]')
  const bgColorIn    = _el('photo-bg-color')
  const bgColorRow   = _el('photo-bg-color-row')
  const matFull      = _el('photo-material-full')
  const matSurface   = _el('photo-material-surface')
  const matCylinders = _el('photo-material-cylinders')
  const matAtomistic = _el('photo-material-atomistic')
  const lightYaw       = _el('photo-light-yaw')
  const lightYawLabel  = _el('photo-light-yaw-label')
  const lightPitch     = _el('photo-light-pitch')
  const lightPitchLabel= _el('photo-light-pitch-label')
  const sunEnable      = _el('photo-sun-enable')
  const sunCtrlsRow    = _el('photo-sun-controls')
  const sunAzimuth     = _el('photo-sun-azimuth')
  const sunAzimuthLbl  = _el('photo-sun-azimuth-label')
  const sunElevation   = _el('photo-sun-elevation')
  const sunElevationLbl= _el('photo-sun-elevation-label')
  const sunStrength    = _el('photo-sun-strength')
  const sunStrengthLbl = _el('photo-sun-strength-label')
  const sunColor       = _el('photo-sun-color')
  const fluoroChk      = _el('photo-fluoro-emissive')
  const fluoroRow      = _el('photo-fluoro-intensity-row')
  const fluoroInt      = _el('photo-fluoro-intensity')
  const fluoroIntLabel = _el('photo-fluoro-intensity-label')
  const envMode        = _el('photo-env-mode')
  const envFile        = _el('photo-env-file')
  const envFileName    = _el('photo-env-file-name')
  const envBg          = _el('photo-env-bg')
  const envEffect      = _el('photo-env-effect')
  const envEffectMistRow = _el('photo-env-effect-mist-row')
  const mistDensity    = _el('photo-mist-density')
  const mistDensityLbl = _el('photo-mist-density-label')
  const mistColor      = _el('photo-mist-color')
  const mistHalo       = _el('photo-mist-halo')
  const mistHaloLbl    = _el('photo-mist-halo-label')
  const mistWispC      = _el('photo-mist-wisp-contrast')
  const mistWispCLbl   = _el('photo-mist-wisp-contrast-label')
  const mistWispS      = _el('photo-mist-wisp-scale')
  const mistWispSLbl   = _el('photo-mist-wisp-scale-label')
  const mistWispSpd    = _el('photo-mist-wisp-speed')
  const mistWispSpdLbl = _el('photo-mist-wisp-speed-label')
  const translucIn     = _el('photo-translucency')
  const translucLbl    = _el('photo-translucency-label')
  const floorAxis      = _el('photo-floor-axis')
  const floorCtrlsRow  = _el('photo-floor-controls')
  const floorMatSel    = _el('photo-floor-material')
  const floorColorIn   = _el('photo-floor-color')
  const floorOpacityIn = _el('photo-floor-opacity')
  const floorOpacityLbl= _el('photo-floor-opacity-label')
  const floorDensityIn = _el('photo-floor-grid-density')
  const floorDensityLbl= _el('photo-floor-grid-density-label')
  const floorOffsetIn  = _el('photo-floor-offset')
  const floorOffsetLbl = _el('photo-floor-offset-label')
  const floorShadowsIn = _el('photo-floor-shadows')
  const floorGridIn       = _el('photo-floor-grid')
  const floorGridStyleRow = _el('photo-floor-grid-style-row')
  const floorGridNeonChk  = _el('photo-floor-grid-neon')
  const floorGridNeonRow  = _el('photo-floor-grid-neon-row')
  const floorGridNeonHint = _el('photo-floor-grid-neon-hint')
  const floorGridColor    = _el('photo-floor-grid-color')
  const floorGridGlow     = _el('photo-floor-grid-glow')
  const floorGridGlowLbl  = _el('photo-floor-grid-glow-label')
  const floorGridFade     = _el('photo-floor-grid-fade')
  const floorGridFadeLbl  = _el('photo-floor-grid-fade-label')
  const ssaoChk      = _el('photo-ssao')
  const bloomChk     = _el('photo-bloom')
  const bloomRow     = _el('photo-bloom-strength-row')
  const bloomStrIn   = _el('photo-bloom-strength')
  const exposureIn   = _el('photo-exposure')
  const resSel       = _el('photo-res-preset')
  const resWIn       = _el('photo-res-w')
  const resHIn       = _el('photo-res-h')
  const dpiLabel     = _el('photo-dpi-label')
  const fovSlider    = _el('photo-fov')
  const fovLabel     = _el('photo-fov-label')
  const orthoChk     = _el('photo-ortho')
  const qualFast     = _el('photo-quality-fast')
  const qualPT       = _el('photo-quality-pt')
  const ptProgress   = _el('photo-pt-progress')
  const ptSamplesEl  = _el('photo-pt-samples')
  // Animation Video section refs.
  const animSelect   = _el('photo-anim-select')
  const animFpsIn    = _el('photo-anim-fps')
  const animFormatIn = _el('photo-anim-format')
  const animPreview  = _el('photo-anim-preview-btn')
  const animExport   = _el('photo-anim-export-btn')
  const animProgRow  = _el('photo-anim-progress-row')
  const animProgLbl  = _el('photo-anim-progress-label')
  const animProgBar  = _el('photo-anim-progress-bar')
  const animCancel   = _el('photo-anim-cancel-btn')

  if (!exitBtn) return   // panel HTML not loaded yet


  // ── Profile machinery ─────────────────────────────────────────────────────
  // Settings to skip when applying a profile (HDR file blob can't be persisted;
  // 'file' environment is downgraded to 'off' on apply so the user can re-upload).
  function _applyProfile(s) {
    if (!s) return
    if (s.lighting)  photoRenderer.setLighting(s.lighting)
    if (s.lightingYaw != null || s.lightingPitch != null) {
      photoRenderer.setLightingDirection(s.lightingYaw ?? 0, s.lightingPitch ?? 0)
    }
    if (s.full)      photoRenderer.setMaterialPreset('full',      s.full)
    if (s.cylinders) photoRenderer.setMaterialPreset('cylinders', s.cylinders)
    if (s.surface)   photoRenderer.setMaterialPreset('surface',   s.surface)
    if (s.atomistic) photoRenderer.setMaterialPreset('atomistic', s.atomistic)
    if (s.bgType)    photoRenderer.setBackground(s.bgType, s.bgColor ?? '#ffffff')
    if (s.ssao  !== undefined) photoRenderer.setSSAO(s.ssao)
    if (s.bloom !== undefined) photoRenderer.setBloom(s.bloom, s.bloomStrength, s.bloomRadius, s.bloomThreshold)
    if (s.exposure !== undefined) photoRenderer.setExposure(s.exposure)
    if (s.fov   != null)       photoRenderer.setFOV(s.fov)
    if (s.fluorophoreEmissive !== undefined) {
      photoRenderer.setFluorophoreEmissive(s.fluorophoreEmissive, s.fluorophoreIntensity ?? 5)
    }
    if (s.translucency !== undefined) photoRenderer.setTranslucency(s.translucency)
    // Sun — apply scalars before toggle so the on-build has the right pose.
    if (s.sunAzimuth   !== undefined) photoRenderer.setSunAzimuth(s.sunAzimuth)
    if (s.sunElevation !== undefined) photoRenderer.setSunElevation(s.sunElevation)
    if (s.sunStrength  !== undefined) photoRenderer.setSunStrength(s.sunStrength)
    if (s.sunColor     !== undefined) photoRenderer.setSunColor(s.sunColor)
    if (s.sun          !== undefined) photoRenderer.setSun(s.sun)
    // Floor — apply in stable order so setFloor() (which triggers a rebuild)
    // sees the rest of the settings already in place.
    if (s.floorMaterial !== undefined) photoRenderer.setFloorMaterial(s.floorMaterial)
    if (s.floorColor    !== undefined) photoRenderer.setFloorColor(s.floorColor)
    if (s.floorOpacity  !== undefined) photoRenderer.setFloorOpacity(s.floorOpacity)
    if (s.floorGridDensity !== undefined) photoRenderer.setFloorGridDensity(s.floorGridDensity)
    if (s.floorOffset   !== undefined) photoRenderer.setFloorOffset(s.floorOffset)
    if (s.floorShadows  !== undefined) photoRenderer.setFloorShadows(s.floorShadows)
    if (s.floorGridColor !== undefined) photoRenderer.setFloorGridColor(s.floorGridColor)
    if (s.floorGridGlow  !== undefined) photoRenderer.setFloorGridGlow(s.floorGridGlow)
    if (s.floorGridFade  !== undefined) photoRenderer.setFloorGridFade(s.floorGridFade)
    if (s.floorGridNeon  !== undefined) photoRenderer.setFloorGridNeon(s.floorGridNeon)
    if (s.floorGrid     !== undefined) photoRenderer.setFloorGrid(s.floorGrid)
    if (s.floor         !== undefined) photoRenderer.setFloor(s.floor)
    // Environment: 'file' can't be restored without the blob — downgrade to 'off'.
    if (s.environment === 'off' || s.environment === 'room') {
      photoRenderer.setEnvironment(s.environment)
    } else if (s.environment === 'file') {
      photoRenderer.setEnvironment('off')
    }
    if (s.environmentBackground !== undefined) photoRenderer.setEnvironmentBackground(s.environmentBackground)
    if (s.envEffect          !== undefined) photoRenderer.setEnvironmentalEffect(s.envEffect)
    if (s.mistDensity        !== undefined) photoRenderer.setMistDensity(s.mistDensity)
    if (s.mistColor          !== undefined) photoRenderer.setMistColor(s.mistColor)
    if (s.mistHaloIntensity  !== undefined) photoRenderer.setMistHaloIntensity(s.mistHaloIntensity)
    photoRenderer.setMistNoise({
      contrast: s.mistNoiseContrast,
      scale:    s.mistNoiseScale,
      speed:    s.mistNoiseSpeed,
    })
    syncToState()
  }

  function _populateProfileDropdown() {
    if (!profileSel) return
    const profiles = _loadProfiles()
    const active   = _getActiveProfileName()
    profileSel.innerHTML = ''
    const names = Object.keys(profiles).sort((a, b) => a.localeCompare(b))
    for (const name of names) {
      const opt = document.createElement('option')
      opt.value = name
      opt.textContent = name
      if (name === active) opt.selected = true
      profileSel.appendChild(opt)
    }
    if (profileStatus) {
      profileStatus.textContent = active ? `Active: ${active}` : ''
    }
  }

  function _ensureDefaultProfile() {
    const profiles = _loadProfiles()
    if (Object.keys(profiles).length === 0) {
      profiles.Default = photoRenderer.getSettings()
      _saveProfiles(profiles)
      _setActiveProfileName('Default')
    } else if (!profiles[_getActiveProfileName()]) {
      // Active name points at a profile that no longer exists — pick first.
      _setActiveProfileName(Object.keys(profiles).sort()[0])
    }
  }

  let _persistTimer = null
  function _schedulePersist() {
    clearTimeout(_persistTimer)
    _persistTimer = setTimeout(() => {
      _persistTimer = null
      const name = _getActiveProfileName()
      if (!name) return
      const profiles = _loadProfiles()
      profiles[name] = photoRenderer.getSettings()
      _saveProfiles(profiles)
    }, 250)
  }

  // Initial profile setup (runs once when the panel is first instantiated).
  // The actual application of the active profile is deferred to applyActiveProfile()
  // which the caller (main.js _photoModeEnter) invokes AFTER photoRenderer.activate(),
  // so material setters take effect properly instead of queueing with toast warnings.
  _migrateEnvDefaultToRoom()
  _ensureDefaultProfile()
  _populateProfileDropdown()

  function applyActiveProfile() {
    const name = _getActiveProfileName()
    if (!name) return
    const profiles = _loadProfiles()
    if (profiles[name]) _applyProfile(profiles[name])
  }

  // Profile dropdown — load on selection.
  profileSel?.addEventListener('change', () => {
    const name = profileSel.value
    if (!name) return
    _setActiveProfileName(name)
    const profiles = _loadProfiles()
    if (profiles[name]) _applyProfile(profiles[name])
    if (profileStatus) profileStatus.textContent = `Active: ${name}`
  })

  // New profile — snapshot of current settings under a chosen name.
  profileNew?.addEventListener('click', async () => {
    const profiles = _loadProfiles()
    const suggested = `Profile ${Object.keys(profiles).length + 1}`
    const name = prompt('New profile name:', suggested)?.trim()
    if (!name) return
    if (profiles[name]) {
      const ok = await showConfirm({
        title: 'Overwrite profile',
        message: `Profile "${name}" already exists. Overwrite?`,
        confirmLabel: 'Overwrite',
      })
      if (!ok) return
    }
    profiles[name] = photoRenderer.getSettings()
    _saveProfiles(profiles)
    _setActiveProfileName(name)
    _populateProfileDropdown()
  })

  // Rename — change the active profile's key.
  profileRename?.addEventListener('click', async () => {
    const oldName = _getActiveProfileName()
    if (!oldName) return
    const newName = prompt(`Rename "${oldName}" to:`, oldName)?.trim()
    if (!newName || newName === oldName) return
    const profiles = _loadProfiles()
    if (profiles[newName]) {
      const ok = await showConfirm({
        title: 'Overwrite profile',
        message: `Profile "${newName}" already exists. Overwrite?`,
        confirmLabel: 'Overwrite',
      })
      if (!ok) return
    }
    profiles[newName] = profiles[oldName]
    delete profiles[oldName]
    _saveProfiles(profiles)
    _setActiveProfileName(newName)
    _populateProfileDropdown()
  })

  // Delete — remove the active profile, fall back to first remaining (or recreate Default).
  profileDelete?.addEventListener('click', async () => {
    const name = _getActiveProfileName()
    if (!name) return
    const ok = await showConfirm({
      title: 'Delete profile',
      message: `Delete profile "${name}"?`,
      danger: true,
      confirmLabel: 'Delete',
    })
    if (!ok) return
    const profiles = _loadProfiles()
    delete profiles[name]
    const remaining = Object.keys(profiles).sort()
    if (remaining.length === 0) {
      profiles.Default = photoRenderer.getSettings()
      _saveProfiles(profiles)
      _setActiveProfileName('Default')
    } else {
      _saveProfiles(profiles)
      _setActiveProfileName(remaining[0])
      _applyProfile(profiles[remaining[0]])
    }
    _populateProfileDropdown()
  })

  // Auto-save on any user interaction inside the photo panel (event delegation).
  // Programmatic .value writes from syncToState/_applyProfile do NOT fire input/change,
  // so loading a profile doesn't trigger a recursive save loop.
  const _photoTab = document.getElementById('tab-content-photo')
  _photoTab?.addEventListener('input',  _schedulePersist, true)
  _photoTab?.addEventListener('change', _schedulePersist, true)

  // ── Resolution helpers ───────────────────────────────────────────────────────

  function _getTargetSize() {
    const pkey = resSel?.value ?? 'p300'
    const preset = RESOLUTION_PRESETS[pkey]
    if (!preset) return { w: 2100, h: 1485 }
    if (pkey === 'screen') {
      return { w: sceneCtx.renderer.domElement.width, h: sceneCtx.renderer.domElement.height }
    }
    if (pkey === 'x2') {
      return {
        w: sceneCtx.renderer.domElement.width  * 2,
        h: sceneCtx.renderer.domElement.height * 2,
      }
    }
    if (pkey === 'custom') {
      return { w: parseInt(resWIn?.value) || 2100, h: parseInt(resHIn?.value) || 1485 }
    }
    return { w: preset.w, h: preset.h }
  }

  function _updateDPILabel() {
    const pkey = resSel?.value ?? 'p300'
    const preset = RESOLUTION_PRESETS[pkey]
    if (!dpiLabel) return
    if (pkey === 'custom') {
      const w   = parseInt(resWIn?.value) || 2100
      const dpi = Math.round(w / 3.46)   // assume 88 mm column width
      dpiLabel.textContent = `≈ ${dpi} DPI`
    } else if (preset?.dpi) {
      dpiLabel.textContent = `${preset.dpi} DPI`
    } else {
      dpiLabel.textContent = 'screen res'
    }
    const { w, h } = _getTargetSize()
    if (resWIn) resWIn.value = w
    if (resHIn) resHIn.value = h
  }

  // ── Wire controls ────────────────────────────────────────────────────────────

  // Exit
  exitBtn.addEventListener('click', () => onExit?.())

  // Export
  exportBtn.addEventListener('click', async () => {
    exportBtn.disabled = true
    try {
      const { w, h } = _getTargetSize()
      // Temporarily upgrade to the chosen export rep (rebuild before/after);
      // the working preview is unchanged except a flicker during the render.
      await _withExportRep(async () => {
        exportBtn.textContent = 'Rendering…'
        const blob = await photoRenderer.renderToBlob(w, h)
        const ts   = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
        _download(blob, `nadoc-${ts}.png`)
      })
    } catch (err) {
      console.error('[photo] Export failed:', err)
    } finally {
      exportBtn.disabled = false
      exportBtn.textContent = '↓ Export PNG'
    }
  })

  // Export representation: persist on change (per-assembly, saved to .nass).
  exportRepSel?.addEventListener('change', () => {
    setExportRepresentation?.(exportRepSel.value)
  })

  // Lighting
  lightingSel?.addEventListener('change', () => {
    photoRenderer.setLighting(lightingSel.value)
  })
  lightYaw?.addEventListener('input', () => {
    if (lightYawLabel) lightYawLabel.textContent = `${lightYaw.value}°`
    photoRenderer.setLightingDirection(parseFloat(lightYaw.value), null)
  })
  lightPitch?.addEventListener('input', () => {
    if (lightPitchLabel) lightPitchLabel.textContent = `${lightPitch.value}°`
    photoRenderer.setLightingDirection(null, parseFloat(lightPitch.value))
  })

  // Sun controls
  function _syncSunRowVisibility() {
    if (sunCtrlsRow) sunCtrlsRow.style.display = sunEnable?.checked ? 'flex' : 'none'
  }
  sunEnable?.addEventListener('change', () => {
    _syncSunRowVisibility()
    photoRenderer.setSun(sunEnable.checked)
  })
  sunAzimuth?.addEventListener('input', () => {
    const v = parseFloat(sunAzimuth.value)
    if (sunAzimuthLbl) sunAzimuthLbl.textContent = `${Math.round(v)}°`
    photoRenderer.setSunAzimuth(v)
  })
  sunElevation?.addEventListener('input', () => {
    const v = parseFloat(sunElevation.value)
    if (sunElevationLbl) sunElevationLbl.textContent = `${Math.round(v)}°`
    photoRenderer.setSunElevation(v)
  })
  sunStrength?.addEventListener('input', () => {
    const v = parseFloat(sunStrength.value)
    if (sunStrengthLbl) sunStrengthLbl.textContent = `${v.toFixed(1)}×`
    photoRenderer.setSunStrength(v)
  })
  sunColor?.addEventListener('input', () => {
    photoRenderer.setSunColor(sunColor.value)
  })

  // Fluorophore emissive override
  fluoroChk?.addEventListener('change', () => {
    if (fluoroRow) fluoroRow.style.display = fluoroChk.checked ? '' : 'none'
    const intensity = parseFloat(fluoroInt?.value ?? 5)
    photoRenderer.setFluorophoreEmissive(fluoroChk.checked, intensity)
  })
  fluoroInt?.addEventListener('input', () => {
    const v = parseFloat(fluoroInt.value)
    if (fluoroIntLabel) fluoroIntLabel.textContent = v.toFixed(1)
    photoRenderer.setFluorophoreIntensity(v)
  })

  // Environment (HDRI)
  envMode?.addEventListener('change', () => {
    const mode = envMode.value
    if (mode === 'file') {
      // Trigger the hidden file input; env applied once the user picks a file
      envFile?.click()
      return
    }
    if (envFileName) envFileName.textContent = ''
    photoRenderer.setEnvironment(mode)
  })
  envFile?.addEventListener('change', async () => {
    const f = envFile.files?.[0]
    if (!f) {
      // User cancelled; revert dropdown to current setting
      if (envMode) envMode.value = photoRenderer.getSettings().environment || 'off'
      return
    }
    if (envFileName) envFileName.textContent = `Loading ${f.name}…`
    await photoRenderer.setEnvironment('file', f)
    if (envFileName) envFileName.textContent = f.name
  })
  envBg?.addEventListener('change', () => {
    photoRenderer.setEnvironmentBackground(envBg.checked)
  })

  // Environmental Effects (mist)
  function _syncMistRowVisibility() {
    if (envEffectMistRow) envEffectMistRow.style.display = (envEffect?.value === 'mist') ? 'flex' : 'none'
  }
  envEffect?.addEventListener('change', () => {
    _syncMistRowVisibility()
    photoRenderer.setEnvironmentalEffect(envEffect.value)
  })
  mistDensity?.addEventListener('input', () => {
    const v = parseFloat(mistDensity.value)
    if (mistDensityLbl) mistDensityLbl.textContent = v.toFixed(3)
    photoRenderer.setMistDensity(v)
  })
  mistColor?.addEventListener('input', () => {
    photoRenderer.setMistColor(mistColor.value)
  })
  mistHalo?.addEventListener('input', () => {
    const v = parseFloat(mistHalo.value)
    if (mistHaloLbl) mistHaloLbl.textContent = `${v.toFixed(2)}×`
    photoRenderer.setMistHaloIntensity(v)
  })
  mistWispC?.addEventListener('input', () => {
    const v = parseFloat(mistWispC.value)
    if (mistWispCLbl) mistWispCLbl.textContent = v.toFixed(2)
    photoRenderer.setMistNoise({ contrast: v })
  })
  mistWispS?.addEventListener('input', () => {
    const v = parseFloat(mistWispS.value)
    if (mistWispSLbl) mistWispSLbl.textContent = v.toFixed(3)
    photoRenderer.setMistNoise({ scale: v })
  })
  mistWispSpd?.addEventListener('input', () => {
    const v = parseFloat(mistWispSpd.value)
    if (mistWispSpdLbl) mistWispSpdLbl.textContent = v.toFixed(2)
    photoRenderer.setMistNoise({ speed: v })
  })

  // Translucency (full + cylinders SSS override)
  translucIn?.addEventListener('input', () => {
    const v = parseFloat(translucIn.value)
    if (translucLbl) translucLbl.textContent = `${Math.round(v * 100)}%`
    photoRenderer.setTranslucency(v)
  })

  // Floor (resting surface)
  function _syncFloorRowVisibility() {
    if (floorCtrlsRow) floorCtrlsRow.style.display = (floorAxis?.value && floorAxis.value !== 'off') ? 'flex' : 'none'
  }
  floorAxis?.addEventListener('change', () => {
    _syncFloorRowVisibility()
    photoRenderer.setFloor(floorAxis.value)
  })
  floorMatSel?.addEventListener('change', () => {
    photoRenderer.setFloorMaterial(floorMatSel.value)
  })
  floorColorIn?.addEventListener('input', () => {
    photoRenderer.setFloorColor(floorColorIn.value)
  })
  floorOpacityIn?.addEventListener('input', () => {
    const v = parseFloat(floorOpacityIn.value)
    if (floorOpacityLbl) floorOpacityLbl.textContent = `${Math.round(v * 100)}%`
    photoRenderer.setFloorOpacity(v)
  })
  floorDensityIn?.addEventListener('input', () => {
    const v = parseFloat(floorDensityIn.value)
    if (floorDensityLbl) floorDensityLbl.textContent = `${v.toFixed(0)}`
    photoRenderer.setFloorGridDensity(v)
  })
  floorOffsetIn?.addEventListener('input', () => {
    const v = parseFloat(floorOffsetIn.value)
    if (floorOffsetLbl) floorOffsetLbl.textContent = `${v.toFixed(1)} nm`
    photoRenderer.setFloorOffset(v)
  })
  floorShadowsIn?.addEventListener('change', () => {
    photoRenderer.setFloorShadows(floorShadowsIn.checked)
  })
  function _syncFloorGridSubRows() {
    if (floorGridStyleRow) floorGridStyleRow.style.display = floorGridIn?.checked ? 'flex' : 'none'
    if (floorGridNeonRow)  floorGridNeonRow.style.display  = floorGridNeonChk?.checked ? 'flex' : 'none'
    if (floorGridNeonHint) floorGridNeonHint.style.display = floorGridNeonChk?.checked ? 'block' : 'none'
  }
  floorGridIn?.addEventListener('change', () => {
    _syncFloorGridSubRows()
    photoRenderer.setFloorGrid(floorGridIn.checked)
  })
  floorGridNeonChk?.addEventListener('change', () => {
    _syncFloorGridSubRows()
    photoRenderer.setFloorGridNeon(floorGridNeonChk.checked)
  })
  floorGridColor?.addEventListener('input', () => {
    photoRenderer.setFloorGridColor(floorGridColor.value)
  })
  floorGridGlow?.addEventListener('input', () => {
    const v = parseFloat(floorGridGlow.value)
    if (floorGridGlowLbl) floorGridGlowLbl.textContent = `${v.toFixed(1)}×`
    photoRenderer.setFloorGridGlow(v)
  })
  floorGridFade?.addEventListener('input', () => {
    const v = parseFloat(floorGridFade.value)
    if (floorGridFadeLbl) floorGridFadeLbl.textContent = `${v.toFixed(1)}×`
    photoRenderer.setFloorGridFade(v)
  })

  // Background
  bgRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      const type = radio.value
      const color = bgColorIn?.value ?? '#ffffff'
      if (bgColorRow) bgColorRow.style.display = type === 'custom' ? '' : 'none'
      photoRenderer.setBackground(type, color)
    })
  })
  bgColorIn?.addEventListener('input', () => {
    photoRenderer.setBackground('custom', bgColorIn.value)
  })

  // Material presets — log attachment so we can confirm wiring at init time
  console.log('[photo-panel] material dropdown refs:', {
    full:      !!matFull,
    surface:   !!matSurface,
    cylinders: !!matCylinders,
    atomistic: !!matAtomistic,
  })
  matFull?.addEventListener('change', () => {
    console.log('[photo-panel] change → full:', matFull.value)
    photoRenderer.setMaterialPreset('full', matFull.value)
  })
  matSurface?.addEventListener('change', () => {
    console.log('[photo-panel] change → surface:', matSurface.value)
    photoRenderer.setMaterialPreset('surface', matSurface.value)
  })
  matCylinders?.addEventListener('change', () => {
    console.log('[photo-panel] change → cylinders:', matCylinders.value)
    photoRenderer.setMaterialPreset('cylinders', matCylinders.value)
  })
  matAtomistic?.addEventListener('change', () => {
    console.log('[photo-panel] change → atomistic:', matAtomistic.value)
    photoRenderer.setMaterialPreset('atomistic', matAtomistic.value)
  })
  // Expose for console debugging
  window.__photoRenderer = photoRenderer
  window.__photoPanelEls = { matFull, matSurface, matCylinders, matAtomistic }

  // SSAO
  ssaoChk?.addEventListener('change', () => photoRenderer.setSSAO(ssaoChk.checked))

  // Bloom
  bloomChk?.addEventListener('change', () => {
    if (bloomRow) bloomRow.style.display = bloomChk.checked ? '' : 'none'
    photoRenderer.setBloom(
      bloomChk.checked,
      parseFloat(bloomStrIn?.value) || 0.5,
    )
  })
  bloomStrIn?.addEventListener('input', () => {
    photoRenderer.setBloom(bloomChk?.checked ?? false, parseFloat(bloomStrIn.value) || 0.5)
  })
  exposureIn?.addEventListener('input', () => {
    photoRenderer.setExposure(parseFloat(exposureIn.value) || 1.0)
  })

  // Resolution
  resSel?.addEventListener('change', () => {
    const isCustom = resSel.value === 'custom'
    if (resWIn) resWIn.readOnly = !isCustom
    if (resHIn) resHIn.readOnly = !isCustom
    _updateDPILabel()
  })
  resWIn?.addEventListener('input', _updateDPILabel)
  resHIn?.addEventListener('input', _updateDPILabel)
  _updateDPILabel()

  // FOV
  fovSlider?.addEventListener('input', () => {
    const v = parseInt(fovSlider.value)
    if (fovLabel) fovLabel.textContent = `${v}°`
    photoRenderer.setFOV(v)
  })

  // Ortho
  orthoChk?.addEventListener('change', () => {
    // Ortho toggle is communicated back to main.js via onEnter/onExit callbacks
    // which manage camera switching; here we just record the intent.
    photoRenderer.getSettings().ortho = orthoChk.checked
  })

  // Quality (path tracing toggle)
  qualPT?.addEventListener('change', () => {
    const enabled = qualPT.checked
    if (ptProgress) ptProgress.style.display = enabled ? '' : 'none'
    photoRenderer.enablePathTracing(enabled)
  })
  qualFast?.addEventListener('change', () => {
    if (ptProgress) ptProgress.style.display = 'none'
    photoRenderer.enablePathTracing(false)
  })

  // Sample counter update from path tracer
  photoRenderer.onSamplesUpdate(count => {
    if (ptSamplesEl) ptSamplesEl.textContent = count
    // Simple fill bar
    const fill = _el('photo-pt-bar-fill')
    if (fill) fill.style.width = Math.min(100, count / 5) + '%'
  })

  // ── Sync UI to current renderer state on open ────────────────────────────────

  function syncToState() {
    const s = photoRenderer.getSettings()
    if (lightingSel) lightingSel.value = s.lighting
    bgRadios.forEach(r => { r.checked = r.value === s.bgType })
    if (bgColorIn) bgColorIn.value = s.bgColor
    if (bgColorRow) bgColorRow.style.display = s.bgType === 'custom' ? '' : 'none'
    if (matFull)      matFull.value      = s.full
    if (matSurface)   matSurface.value   = s.surface
    if (matCylinders) matCylinders.value = s.cylinders
    if (matAtomistic) matAtomistic.value = s.atomistic
    // Export rep is a per-assembly setting (not a photo profile setting).
    if (exportRepSel) exportRepSel.value = store?.getState?.()?.currentAssembly?.export_representation ?? 'full'
    if (lightYaw)        lightYaw.value        = s.lightingYaw
    if (lightPitch)      lightPitch.value      = s.lightingPitch
    if (lightYawLabel)   lightYawLabel.textContent   = `${s.lightingYaw}°`
    if (lightPitchLabel) lightPitchLabel.textContent = `${s.lightingPitch}°`
    if (fluoroChk)       fluoroChk.checked     = s.fluorophoreEmissive
    if (fluoroRow)       fluoroRow.style.display = s.fluorophoreEmissive ? '' : 'none'
    if (fluoroInt)       fluoroInt.value       = s.fluorophoreIntensity
    if (fluoroIntLabel)  fluoroIntLabel.textContent = s.fluorophoreIntensity.toFixed(1)
    if (envMode)         envMode.value         = s.environment ?? 'off'
    if (envFileName)     envFileName.textContent = s.environmentName ?? ''
    if (envBg)           envBg.checked         = !!s.environmentBackground
    if (envEffect)       envEffect.value       = s.envEffect ?? 'none'
    _syncMistRowVisibility()
    if (mistDensity)     mistDensity.value     = s.mistDensity ?? 0.04
    if (mistDensityLbl)  mistDensityLbl.textContent = (s.mistDensity ?? 0.04).toFixed(3)
    if (mistColor)       mistColor.value       = s.mistColor ?? '#9aa6b8'
    if (mistHalo)        mistHalo.value        = s.mistHaloIntensity ?? 1.0
    if (mistHaloLbl)     mistHaloLbl.textContent = `${(s.mistHaloIntensity ?? 1.0).toFixed(2)}×`
    if (mistWispC)       mistWispC.value       = s.mistNoiseContrast ?? 0
    if (mistWispCLbl)    mistWispCLbl.textContent = (s.mistNoiseContrast ?? 0).toFixed(2)
    if (mistWispS)       mistWispS.value       = s.mistNoiseScale ?? 0.05
    if (mistWispSLbl)    mistWispSLbl.textContent = (s.mistNoiseScale ?? 0.05).toFixed(3)
    if (mistWispSpd)     mistWispSpd.value     = s.mistNoiseSpeed ?? 0
    if (mistWispSpdLbl)  mistWispSpdLbl.textContent = (s.mistNoiseSpeed ?? 0).toFixed(2)
    if (translucIn)      translucIn.value      = s.translucency ?? 0
    if (translucLbl)     translucLbl.textContent = `${Math.round((s.translucency ?? 0) * 100)}%`
    // Sun
    if (sunEnable)       sunEnable.checked      = !!s.sun
    if (sunAzimuth)      sunAzimuth.value       = s.sunAzimuth ?? 135
    if (sunAzimuthLbl)   sunAzimuthLbl.textContent  = `${Math.round(s.sunAzimuth ?? 135)}°`
    if (sunElevation)    sunElevation.value     = s.sunElevation ?? 35
    if (sunElevationLbl) sunElevationLbl.textContent = `${Math.round(s.sunElevation ?? 35)}°`
    if (sunStrength)     sunStrength.value      = s.sunStrength ?? 1.5
    if (sunStrengthLbl)  sunStrengthLbl.textContent = `${(s.sunStrength ?? 1.5).toFixed(1)}×`
    if (sunColor)        sunColor.value         = s.sunColor ?? '#ffffff'
    _syncSunRowVisibility()
    // Floor
    if (floorAxis)       floorAxis.value       = s.floor ?? 'off'
    if (floorMatSel)     floorMatSel.value     = s.floorMaterial ?? 'matte'
    if (floorColorIn)    floorColorIn.value    = s.floorColor ?? '#888888'
    if (floorOpacityIn)  floorOpacityIn.value  = s.floorOpacity ?? 1
    if (floorOpacityLbl) floorOpacityLbl.textContent = `${Math.round((s.floorOpacity ?? 1) * 100)}%`
    if (floorDensityIn)  floorDensityIn.value  = s.floorGridDensity ?? 10
    if (floorDensityLbl) floorDensityLbl.textContent = `${(s.floorGridDensity ?? 10).toFixed(0)}`
    if (floorOffsetIn)   floorOffsetIn.value   = s.floorOffset ?? 0
    if (floorOffsetLbl)  floorOffsetLbl.textContent = `${(s.floorOffset ?? 0).toFixed(1)} nm`
    if (floorShadowsIn)  floorShadowsIn.checked = s.floorShadows ?? true
    if (floorGridIn)     floorGridIn.checked   = !!s.floorGrid
    if (floorGridNeonChk) floorGridNeonChk.checked = !!s.floorGridNeon
    if (floorGridColor)  floorGridColor.value  = s.floorGridColor ?? '#ff00ff'
    if (floorGridGlow)   floorGridGlow.value   = s.floorGridGlow ?? 3.0
    if (floorGridGlowLbl) floorGridGlowLbl.textContent = `${(s.floorGridGlow ?? 3.0).toFixed(1)}×`
    if (floorGridFade)   floorGridFade.value   = s.floorGridFade ?? 1.5
    if (floorGridFadeLbl) floorGridFadeLbl.textContent = `${(s.floorGridFade ?? 1.5).toFixed(1)}×`
    _syncFloorGridSubRows()
    _syncFloorRowVisibility()
    if (ssaoChk) ssaoChk.checked  = s.ssao
    if (bloomChk) bloomChk.checked = s.bloom
    if (bloomRow) bloomRow.style.display = s.bloom ? '' : 'none'
    if (bloomStrIn) bloomStrIn.value = s.bloomStrength
    if (exposureIn && s.exposure !== undefined) exposureIn.value = s.exposure
    if (fovSlider) {
      fovSlider.value = s.fov ?? sceneCtx.camera.fov
      if (fovLabel) fovLabel.textContent = `${Math.round(s.fov ?? sceneCtx.camera.fov)}°`
    }
    if (ptProgress) ptProgress.style.display = s.pathTracing ? '' : 'none'
    _updateDPILabel()
  }

  // ── Animation Video section ────────────────────────────────────────────────
  //
  // Lets the user select a previously-created animation and either preview it
  // through the live scene (which is already using the photo renderer's
  // materials/lights/environment) or export it as a high-resolution video by
  // running each frame through `photoRenderer.renderToBlob` — same path the
  // "Export PNG" button uses for stills.
  //
  // Animations are sourced from the active design or (in assembly mode) the
  // active assembly. The dropdown auto-refreshes when the relevant slice
  // changes so the list stays current with the Animation panel.

  function _currentAnimations() {
    const s = store?.getState?.()
    if (!s) return []
    if (s.assemblyActive && s.currentAssembly) return s.currentAssembly.animations ?? []
    return s.currentDesign?.animations ?? []
  }

  function _refreshAnimationDropdown() {
    if (!animSelect) return
    const prev = animSelect.value
    const anims = _currentAnimations()
    animSelect.innerHTML = ''
    if (anims.length === 0) {
      const opt = document.createElement('option')
      opt.value = ''
      opt.textContent = '— no animations available —'
      animSelect.appendChild(opt)
    } else {
      for (const a of anims) {
        const opt = document.createElement('option')
        opt.value = a.id
        opt.textContent = a.name || a.id
        animSelect.appendChild(opt)
      }
      if (anims.some(a => a.id === prev)) animSelect.value = prev
    }
    _refreshAnimationButtons()
  }

  function _activeAnimation() {
    const id = animSelect?.value
    if (!id) return null
    return _currentAnimations().find(a => a.id === id) ?? null
  }

  function _refreshAnimationButtons() {
    const has = !!_activeAnimation()
    const ready = has && !!player
    const exportable = ready && !!exportPhotoVideo
    if (animPreview) {
      animPreview.disabled = !ready
      animPreview.style.opacity = ready ? '1' : '0.45'
      animPreview.style.cursor  = ready ? 'pointer' : 'default'
    }
    if (animExport) {
      animExport.disabled = !exportable
      animExport.style.opacity = exportable ? '1' : '0.45'
      animExport.style.cursor  = exportable ? 'pointer' : 'default'
    }
    // When an animation is picked, default FPS from the animation itself
    // (only if the user hasn't manually changed the field).
    const a = _activeAnimation()
    if (a && animFpsIn && animFpsIn.dataset.userEdited !== 'true') {
      animFpsIn.value = String(Math.max(1, Math.min(60, a.fps ?? 30)))
    }
  }

  animFpsIn?.addEventListener('input', () => { animFpsIn.dataset.userEdited = 'true' })
  animSelect?.addEventListener('change', _refreshAnimationButtons)

  // Subscribe to store updates so newly-created animations show up live.
  if (store?.subscribe) {
    store.subscribe((n, p) => {
      const designChanged   = n.currentDesign   !== p.currentDesign
      const assemblyChanged = n.currentAssembly !== p.currentAssembly
      const modeChanged     = n.assemblyActive  !== p.assemblyActive
      if (designChanged || assemblyChanged || modeChanged) _refreshAnimationDropdown()
    })
  }
  _refreshAnimationDropdown()

  // Preview: play the animation in the live scene. Photo mode is active when
  // this panel is visible, so playback uses the photo materials/lights/HDRI
  // automatically — no special render path needed.
  animPreview?.addEventListener('click', async () => {
    const anim = _activeAnimation()
    if (!anim || !player) return
    animPreview.disabled = true
    animPreview.textContent = 'Playing…'
    try {
      await player.play(anim)
    } catch (err) {
      console.error('[photo] Preview failed:', err)
    } finally {
      animPreview.disabled = false
      animPreview.textContent = '▶ Preview'
      _refreshAnimationButtons()
    }
  })

  // Export: drive the animation player frame-by-frame and render each frame
  // at the chosen photo-mode resolution via photoRenderer.renderToBlob.
  let _exportAbort = null
  animCancel?.addEventListener('click', () => { _exportAbort?.abort?.() })

  animExport?.addEventListener('click', async () => {
    const anim = _activeAnimation()
    if (!anim || !player || !exportPhotoVideo) return
    const { w, h } = _getTargetSize()
    const fps = Math.max(1, Math.min(60, parseInt(animFpsIn?.value, 10) || 30))
    const format = (animFormatIn?.value === 'gif') ? 'gif' : 'webm'

    animExport.disabled = true
    animExport.textContent = 'Rendering…'
    if (animProgRow) animProgRow.style.display = 'flex'
    if (animProgBar) animProgBar.style.width = '0%'
    if (animProgLbl) animProgLbl.textContent = 'Preparing…'
    _exportAbort = new AbortController()

    try {
      // One upgrade to the export rep before the frame session, one restore
      // after (the session renders the live scene per frame). Working view unchanged.
      await _withExportRep(async () => {
        if (animProgLbl) animProgLbl.textContent = 'Building high-detail…'
        await exportPhotoVideo({
          animation: anim,
          player,
          photoRenderer,
          width: w, height: h,
          options: { format, fps },
          signal: _exportAbort.signal,
          onProgress: (frac, info) => {
            if (animProgBar) animProgBar.style.width = `${Math.round(frac * 100)}%`
            if (animProgLbl) animProgLbl.textContent =
              `Frame ${info?.frame ?? 0} / ${info?.frames ?? '?'}  (${Math.round(frac * 100)}%)`
          },
        })
      })
      if (animProgLbl) animProgLbl.textContent = 'Done.'
    } catch (err) {
      if (err?.name === 'AbortError') {
        if (animProgLbl) animProgLbl.textContent = 'Cancelled.'
      } else {
        console.error('[photo] Animation export failed:', err)
        if (animProgLbl) animProgLbl.textContent = `Error: ${err?.message ?? err}`
      }
    } finally {
      _exportAbort = null
      animExport.disabled = false
      animExport.textContent = '↓ Export Video'
      // Hide progress row after a short delay so the user can read the result.
      setTimeout(() => { if (animProgRow) animProgRow.style.display = 'none' }, 2000)
      _refreshAnimationButtons()
    }
  })

  return { syncToState, applyActiveProfile, refreshAnimationDropdown: _refreshAnimationDropdown }
}
