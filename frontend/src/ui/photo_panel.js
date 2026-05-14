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
 */
export function initPhotoPanel(photoRenderer, sceneCtx, { onEnter, onExit }) {
  // ── Element refs ────────────────────────────────────────────────────────────
  const exitBtn      = _el('photo-exit-btn')
  const exportBtn    = _el('photo-export-btn')
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
  const fluoroChk      = _el('photo-fluoro-emissive')
  const fluoroRow      = _el('photo-fluoro-intensity-row')
  const fluoroInt      = _el('photo-fluoro-intensity')
  const fluoroIntLabel = _el('photo-fluoro-intensity-label')
  const envMode        = _el('photo-env-mode')
  const envFile        = _el('photo-env-file')
  const envFileName    = _el('photo-env-file-name')
  const envBg          = _el('photo-env-bg')
  const translucIn     = _el('photo-translucency')
  const translucLbl    = _el('photo-translucency-label')
  const ssaoChk      = _el('photo-ssao')
  const bloomChk     = _el('photo-bloom')
  const bloomRow     = _el('photo-bloom-strength-row')
  const bloomStrIn   = _el('photo-bloom-strength')
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

  if (!exitBtn) return   // panel HTML not loaded yet

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
    exportBtn.textContent = 'Rendering…'
    try {
      const { w, h } = _getTargetSize()
      const blob      = await photoRenderer.renderToBlob(w, h)
      const ts        = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      _download(blob, `nadoc-${ts}.png`)
    } catch (err) {
      console.error('[photo] Export failed:', err)
    } finally {
      exportBtn.disabled = false
      exportBtn.textContent = '↓ Export PNG'
    }
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

  // Translucency (full + cylinders SSS override)
  translucIn?.addEventListener('input', () => {
    const v = parseFloat(translucIn.value)
    if (translucLbl) translucLbl.textContent = `${Math.round(v * 100)}%`
    photoRenderer.setTranslucency(v)
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
    if (translucIn)      translucIn.value      = s.translucency ?? 0
    if (translucLbl)     translucLbl.textContent = `${Math.round((s.translucency ?? 0) * 100)}%`
    if (ssaoChk) ssaoChk.checked  = s.ssao
    if (bloomChk) bloomChk.checked = s.bloom
    if (bloomRow) bloomRow.style.display = s.bloom ? '' : 'none'
    if (bloomStrIn) bloomStrIn.value = s.bloomStrength
    if (fovSlider) {
      fovSlider.value = s.fov ?? sceneCtx.camera.fov
      if (fovLabel) fovLabel.textContent = `${Math.round(s.fov ?? sceneCtx.camera.fov)}°`
    }
    if (ptProgress) ptProgress.style.display = s.pathTracing ? '' : 'none'
    _updateDPILabel()
  }

  return { syncToState }
}
