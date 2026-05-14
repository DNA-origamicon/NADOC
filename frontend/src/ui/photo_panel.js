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

  // Material presets
  matFull?.addEventListener('change', () => photoRenderer.setMaterialPreset('full', matFull.value))
  matSurface?.addEventListener('change', () => photoRenderer.setMaterialPreset('surface', matSurface.value))
  matCylinders?.addEventListener('change', () => photoRenderer.setMaterialPreset('cylinders', matCylinders.value))
  matAtomistic?.addEventListener('change', () => photoRenderer.setMaterialPreset('atomistic', matAtomistic.value))

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
