/**
 * Photo mode — "Figure (publication)" controls.
 *
 * The outline / depth-cue / occlusion-shading / parallel-projection section of
 * the Photo tab. Split out of photo_panel.js because it is a cohesive block
 * with its own element refs, its own row-visibility rules, and its own slice of
 * the settings object — photo_panel just constructs it and delegates.
 *
 * Contract with photo_panel:
 *   - `applySettings(s)` — push this section's settings into the renderer.
 *     Called from photo_panel's `_applyProfile` so a saved profile (and a style
 *     preset, which is applied through the same path) restores these controls.
 *   - `syncToState()`    — refresh the controls from `photoRenderer.getSettings()`.
 *
 * The controls are all INDEPENDENT: the Publication style preset is just a
 * bundle that switches the right ones on (see photo_renderer/style_presets.js).
 * Auto-save is free — photo_panel delegates `input`/`change` on the whole tab.
 */

function _el(id) { return document.getElementById(id) }

/**
 * @param {object} photoRenderer — createPhotoRenderer() instance
 * @returns {{ applySettings: (s: object) => void, syncToState: () => void }}
 */
export function initPhotoFigurePanel(photoRenderer) {
  // Outline
  const outlineChk       = _el('photo-outline')
  const outlineCtrls     = _el('photo-outline-controls')
  const outlineThick     = _el('photo-outline-thickness')
  const outlineThickLbl  = _el('photo-outline-thickness-label')
  const outlineStr       = _el('photo-outline-strength')
  const outlineStrLbl    = _el('photo-outline-strength-label')
  const outlineDepth     = _el('photo-outline-depth-sens')
  const outlineDepthLbl  = _el('photo-outline-depth-sens-label')
  const outlineCrease    = _el('photo-outline-crease-sens')
  const outlineCreaseLbl = _el('photo-outline-crease-sens-label')
  const outlineColor     = _el('photo-outline-color')

  // Depth cue
  const cueChk      = _el('photo-depthcue')
  const cueCtrls    = _el('photo-depthcue-controls')
  const cueStr      = _el('photo-depthcue-strength')
  const cueStrLbl   = _el('photo-depthcue-strength-label')
  const cueColor    = _el('photo-depthcue-color')

  // Occlusion shading (GTAO)
  const aoChk       = _el('photo-ao')
  const aoCtrls     = _el('photo-ao-controls')
  const aoRadius    = _el('photo-ao-radius')
  const aoRadiusLbl = _el('photo-ao-radius-label')
  const aoInt       = _el('photo-ao-intensity')
  const aoIntLbl    = _el('photo-ao-intensity-label')

  // Full-quality-while-orbiting toggle (keeps occlusion shading live during orbit)
  const orbitFullChk = _el('photo-orbit-fullquality')

  // Camera
  const parallelChk = _el('photo-parallel')

  // ── Row visibility ─────────────────────────────────────────────────────────

  function _syncRows() {
    if (outlineCtrls) outlineCtrls.style.display = outlineChk?.checked ? 'flex' : 'none'
    if (cueCtrls)     cueCtrls.style.display     = cueChk?.checked     ? 'flex' : 'none'
    if (aoCtrls)      aoCtrls.style.display      = aoChk?.checked      ? 'flex' : 'none'
  }

  // ── Wire controls ──────────────────────────────────────────────────────────

  outlineChk?.addEventListener('change', () => {
    _syncRows()
    photoRenderer.setOutline(outlineChk.checked)
  })
  outlineThick?.addEventListener('input', () => {
    const v = parseFloat(outlineThick.value)
    if (outlineThickLbl) outlineThickLbl.textContent = `${v.toFixed(1)} px`
    photoRenderer.setOutlineThickness(v)
  })
  outlineStr?.addEventListener('input', () => {
    const v = parseFloat(outlineStr.value)
    if (outlineStrLbl) outlineStrLbl.textContent = `${Math.round(v * 100)}%`
    photoRenderer.setOutlineStrength(v)
  })
  outlineDepth?.addEventListener('input', () => {
    const v = parseFloat(outlineDepth.value)
    if (outlineDepthLbl) outlineDepthLbl.textContent = v.toFixed(2)
    photoRenderer.setOutlineSensitivity({ depth: v })
  })
  outlineCrease?.addEventListener('input', () => {
    const v = parseFloat(outlineCrease.value)
    if (outlineCreaseLbl) outlineCreaseLbl.textContent = v.toFixed(2)
    photoRenderer.setOutlineSensitivity({ crease: v })
  })
  outlineColor?.addEventListener('input', () => {
    photoRenderer.setOutlineColor(outlineColor.value)
  })

  cueChk?.addEventListener('change', () => {
    _syncRows()
    photoRenderer.setDepthCue(cueChk.checked)
  })
  cueStr?.addEventListener('input', () => {
    const v = parseFloat(cueStr.value)
    if (cueStrLbl) cueStrLbl.textContent = `${Math.round(v * 100)}%`
    photoRenderer.setDepthCueStrength(v)
  })
  cueColor?.addEventListener('input', () => {
    photoRenderer.setDepthCueColor(cueColor.value)
  })

  aoChk?.addEventListener('change', () => {
    _syncRows()
    photoRenderer.setAO(aoChk.checked)
  })
  aoRadius?.addEventListener('input', () => {
    const v = parseFloat(aoRadius.value)
    if (aoRadiusLbl) aoRadiusLbl.textContent = `${v.toFixed(1)} nm`
    photoRenderer.setAORadius(v)
  })
  aoInt?.addEventListener('input', () => {
    const v = parseFloat(aoInt.value)
    if (aoIntLbl) aoIntLbl.textContent = `${v.toFixed(2)}×`
    photoRenderer.setAOIntensity(v)
  })

  orbitFullChk?.addEventListener('change', () => {
    photoRenderer.setOrbitFullQuality(orbitFullChk.checked)
  })

  parallelChk?.addEventListener('change', () => {
    photoRenderer.setParallel(parallelChk.checked)
  })

  // ── Profile / style application ────────────────────────────────────────────

  /** Push this section's settings into the renderer. Scalars before toggles so
   *  the effect is built with the right parameters the first time. */
  function applySettings(s) {
    if (!s) return
    if (s.outlineColor             !== undefined) photoRenderer.setOutlineColor(s.outlineColor)
    if (s.outlineStrength          !== undefined) photoRenderer.setOutlineStrength(s.outlineStrength)
    if (s.outlineThickness         !== undefined) photoRenderer.setOutlineThickness(s.outlineThickness)
    if (s.outlineDepthSensitivity  !== undefined || s.outlineCreaseSensitivity !== undefined) {
      photoRenderer.setOutlineSensitivity({
        depth:  s.outlineDepthSensitivity,
        crease: s.outlineCreaseSensitivity,
      })
    }
    if (s.outline          !== undefined) photoRenderer.setOutline(s.outline)

    if (s.depthCueColor    !== undefined) photoRenderer.setDepthCueColor(s.depthCueColor)
    if (s.depthCueStrength !== undefined) photoRenderer.setDepthCueStrength(s.depthCueStrength)
    if (s.depthCue         !== undefined) photoRenderer.setDepthCue(s.depthCue)

    if (s.aoRadius    !== undefined) photoRenderer.setAORadius(s.aoRadius)
    if (s.aoIntensity !== undefined) photoRenderer.setAOIntensity(s.aoIntensity)
    if (s.ao          !== undefined) photoRenderer.setAO(s.ao)

    if (s.orbitFullQuality !== undefined) photoRenderer.setOrbitFullQuality(s.orbitFullQuality)

    // `parallel` drives FOV (and dollies the camera), so it must win over any
    // stale `fov` in the same settings object — apply it last.
    if (s.parallel !== undefined) photoRenderer.setParallel(s.parallel)
    else if (s.fov != null)       photoRenderer.setFOV(s.fov)
  }

  function syncToState() {
    const s = photoRenderer.getSettings()

    if (outlineChk)       outlineChk.checked      = !!s.outline
    if (outlineThick)     outlineThick.value      = s.outlineThickness ?? 1.4
    if (outlineThickLbl)  outlineThickLbl.textContent  = `${(s.outlineThickness ?? 1.4).toFixed(1)} px`
    if (outlineStr)       outlineStr.value        = s.outlineStrength ?? 1
    if (outlineStrLbl)    outlineStrLbl.textContent    = `${Math.round((s.outlineStrength ?? 1) * 100)}%`
    if (outlineDepth)     outlineDepth.value      = s.outlineDepthSensitivity ?? 0.35
    if (outlineDepthLbl)  outlineDepthLbl.textContent  = (s.outlineDepthSensitivity ?? 0.35).toFixed(2)
    if (outlineCrease)    outlineCrease.value     = s.outlineCreaseSensitivity ?? 0.85
    if (outlineCreaseLbl) outlineCreaseLbl.textContent = (s.outlineCreaseSensitivity ?? 0.85).toFixed(2)
    if (outlineColor)     outlineColor.value      = s.outlineColor ?? '#1b1f24'

    if (cueChk)    cueChk.checked   = !!s.depthCue
    if (cueStr)    cueStr.value     = s.depthCueStrength ?? 0.35
    if (cueStrLbl) cueStrLbl.textContent = `${Math.round((s.depthCueStrength ?? 0.35) * 100)}%`
    if (cueColor)  cueColor.value   = s.depthCueColor ?? '#ffffff'

    if (aoChk)       aoChk.checked   = !!s.ao
    if (aoRadius)    aoRadius.value  = s.aoRadius ?? 2.0
    if (aoRadiusLbl) aoRadiusLbl.textContent = `${(s.aoRadius ?? 2.0).toFixed(1)} nm`
    if (aoInt)       aoInt.value     = s.aoIntensity ?? 1.0
    if (aoIntLbl)    aoIntLbl.textContent = `${(s.aoIntensity ?? 1.0).toFixed(2)}×`

    if (orbitFullChk) orbitFullChk.checked = s.orbitFullQuality !== false  // default ON

    if (parallelChk) parallelChk.checked = !!s.parallel

    _syncRows()
  }

  return { applySettings, syncToState }
}
