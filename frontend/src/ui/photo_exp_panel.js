/**
 * Experimental photo-mode panel — the controls for scene/photo_exp_mode.js.
 *
 * Thin by design: it reads DOM elements, pushes values into the mode controller,
 * and renders a status line. All rendering decisions live in the mode; this file
 * only translates clicks into calls, so the experiment can be re-skinned or
 * thrown away without touching the renderer.
 */

import { getSectionCollapsed, setSectionCollapsed } from './section_collapse_state.js'
import { PRESET_LABELS } from '../scene/photo_renderer/material_presets.js'

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
 * @param {object} expMode — controller from createExpPhotoMode()
 * @param {{onExit: () => void}} deps
 */
export function initPhotoExpPanel(expMode, { onExit } = {}) {
  const $ = (id) => document.getElementById(id)

  const els = {
    exit:      $('photoexp-exit-btn'),
    status:    $('photoexp-status'),
    pinLights: $('photoexp-pin-lights'),
    keyShadow: $('photoexp-key-shadow'),
    keyShadowControls:  $('photoexp-key-shadow-controls'),
    keyShadowMapSize:   $('photoexp-key-shadow-mapsize'),
    keyShadowRes:       $('photoexp-key-shadow-res'),
    keyShadowBias:      $('photoexp-key-shadow-bias'),
    keyShadowBiasLabel: $('photoexp-key-shadow-bias-label'),
    keyAzimuth:        $('photoexp-key-azimuth'),
    keyAzimuthLabel:   $('photoexp-key-azimuth-label'),
    keyElevation:      $('photoexp-key-elevation'),
    keyElevationLabel: $('photoexp-key-elevation-label'),
    keyDir:            $('photoexp-key-dir'),
    keyDirReset:       $('photoexp-key-dir-reset'),
    shadowStrength:      $('photoexp-shadow-strength'),
    shadowStrengthLabel: $('photoexp-shadow-strength-label'),
    shadowStrength:      $('photoexp-shadow-strength'),
    shadowStrengthLabel: $('photoexp-shadow-strength-label'),
    keyIntensity:        $('photoexp-key-intensity'),
    keyIntensityLabel:   $('photoexp-key-intensity-label'),
    fillIntensity:       $('photoexp-fill-intensity'),
    fillIntensityLabel:  $('photoexp-fill-intensity-label'),
    ambientIntensity:      $('photoexp-ambient-intensity'),
    ambientIntensityLabel: $('photoexp-ambient-intensity-label'),
    maxContrast: $('photoexp-max-contrast'),
    shadowDepth: $('photoexp-shadow-depth'),
    outline:            $('photoexp-outline'),
    outlineControls:    $('photoexp-outline-controls'),
    outlineColor:       $('photoexp-outline-color'),
    outlineStrength:    $('photoexp-outline-strength'),
    outlineStrengthLab: $('photoexp-outline-strength-label'),
    outlineThickness:   $('photoexp-outline-thickness'),
    outlineThicknessLab:$('photoexp-outline-thickness-label'),
    outlineJump:        $('photoexp-outline-jump'),
    outlineJumpLab:     $('photoexp-outline-jump-label'),
    depthCue:           $('photoexp-depthcue'),
    depthCueControls:   $('photoexp-depthcue-controls'),
    depthCueColor:      $('photoexp-depthcue-color'),
    depthCueStrength:   $('photoexp-depthcue-strength'),
    depthCueStrengthLab:$('photoexp-depthcue-strength-label'),
    matFull:      $('photoexp-mat-full'),
    matCylinders: $('photoexp-mat-cylinders'),
    matSurface:   $('photoexp-mat-surface'),
    matAtomistic: $('photoexp-mat-atomistic'),
    fov:        $('photoexp-fov'),
    fovLabel:   $('photoexp-fov-label'),
    parallel:   $('photoexp-parallel'),
    resPreset:  $('photoexp-res-preset'),
    resW:       $('photoexp-res-w'),
    resH:       $('photoexp-res-h'),
    exportNote: $('photoexp-export-note'),
    exportBtn:  $('photoexp-export-btn'),
    bgType:  $('photoexp-bg-type'),
    bgColor: $('photoexp-bg-color'),
  }

  let _statusTimer = null

  function _refreshStatus() {
    if (els.status) els.status.textContent = formatShadowStatus(expMode.getStatus())
  }

  function _refreshResolution() {
    if (!els.keyShadowRes) return
    const s = expMode.getSettings()
    const r = shadowResolution(expMode.getStatus()?.radius ?? 0, s.keyShadowMapSize)
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
    const s = expMode.getSettings()
    if (els.pinLights) els.pinLights.checked = s.pinLights
    if (els.keyShadow) els.keyShadow.checked = s.keyShadow
    if (els.keyShadowMapSize)   els.keyShadowMapSize.value = String(s.keyShadowMapSize)
    if (els.keyShadowBias)      els.keyShadowBias.value = String(s.keyShadowBias)
    if (els.keyShadowBiasLabel) els.keyShadowBiasLabel.textContent = `${s.keyShadowBias.toFixed(1)}×`
    if (els.shadowStrength)      els.shadowStrength.value = String(s.shadowStrength)
    if (els.shadowStrengthLabel) els.shadowStrengthLabel.textContent = s.shadowStrength.toFixed(2)
    if (els.keyShadowControls)  els.keyShadowControls.style.display = s.keyShadow ? 'flex' : 'none'
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
    const s = expMode.getSettings()
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
    const s = expMode.getSettings()
    const pct = Math.round(shadowDepthFraction(s) * 100)
    els.shadowDepth.textContent =
      `A cast shadow removes ${pct}% of the light here (key ${s.keyIntensity.toFixed(2)} of `
      + `${(s.keyIntensity + s.fillIntensity + s.ambientIntensity).toFixed(2)} total). `
      + `Lower Fill and Ambient to deepen it.`
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


  els.pinLights?.addEventListener('change', () => expMode.setPinLights(els.pinLights.checked))

  els.keyShadow?.addEventListener('change', () => {
    expMode.setKeyShadow(els.keyShadow.checked)
    if (els.keyShadowControls) {
      els.keyShadowControls.style.display = els.keyShadow.checked ? 'flex' : 'none'
    }
    _refreshStatus()
  })

  els.keyShadowMapSize?.addEventListener('change', () => {
    expMode.setKeyShadowMapSize(Number(els.keyShadowMapSize.value))
    _refreshResolution()
  })

  els.keyShadowBias?.addEventListener('input', () => {
    const v = Number(els.keyShadowBias.value)
    expMode.setKeyShadowBias(v)
    if (els.keyShadowBiasLabel) els.keyShadowBiasLabel.textContent = `${v.toFixed(1)}×`
  })

  els.shadowStrength?.addEventListener('input', () => {
    const v = Number(els.shadowStrength.value)
    expMode.setShadowStrength(v)
    if (els.shadowStrengthLabel) els.shadowStrengthLabel.textContent = v.toFixed(2)
  })

  for (const [el, lab, setter, unit] of [
    [els.keyAzimuth,   els.keyAzimuthLabel,   v => expMode.setKeyAzimuth(v),   '°'],
    [els.keyElevation, els.keyElevationLabel, v => expMode.setKeyElevation(v), '°'],
  ]) {
    el?.addEventListener('input', () => {
      const v = Number(el.value)
      setter(v)
      if (lab) lab.textContent = `${v.toFixed(0)}${unit}`
      _refreshKeyDir()
    })
  }

  _bindIntensity(els.keyIntensity,     els.keyIntensityLabel,     v => expMode.setKeyIntensity(v))
  _bindIntensity(els.fillIntensity,    els.fillIntensityLabel,    v => expMode.setFillIntensity(v))
  _bindIntensity(els.ambientIntensity, els.ambientIntensityLabel, v => expMode.setAmbientIntensity(v))
  _bindIntensity(els.shadowStrength,   els.shadowStrengthLabel,   v => expMode.setShadowStrength(v))

  els.maxContrast?.addEventListener('click', () => {
    expMode.setKeyIntensity(2.0)
    expMode.setFillIntensity(0)
    expMode.setAmbientIntensity(0.15)
    syncToState()
  })

  els.bgType?.addEventListener('change', () => {
    expMode.setBackground(els.bgType.value, undefined)
    if (els.bgColor) els.bgColor.disabled = els.bgType.value === 'transparent'
  })

  els.bgColor?.addEventListener('input', () => expMode.setBackground(undefined, els.bgColor.value))

  // ── Collapsible cards ──────────────────────────────────────────────────────
  // Same markup, classes and persistence as the Simulations-tab cards
  // (see ui/chain_sim_panel.js): a clickable <h2> with a rotating chevron and a
  // sibling body div, with per-tab collapse state in localStorage.
  function _initCard(id) {
    const heading = $(`photoexp-${id}-heading`)
    const body    = $(`photoexp-${id}-body`)
    const arrow   = $(`photoexp-${id}-arrow`)
    if (!heading || !body) return
    let collapsed = getSectionCollapsed('photo-exp', `photoexp-${id}-panel`, false)
    body.style.display = collapsed ? 'none' : ''
    arrow?.classList.toggle('is-collapsed', collapsed)
    heading.addEventListener('click', () => {
      collapsed = !collapsed
      body.style.display = collapsed ? 'none' : ''
      arrow?.classList.toggle('is-collapsed', collapsed)
      setSectionCollapsed('photo-exp', `photoexp-${id}-panel`, collapsed)
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
    sel.addEventListener('change', () => expMode.setMaterialPreset(repr, sel.value))
  }

  els.outline?.addEventListener('change', () => {
    expMode.setOutline(els.outline.checked)
    if (els.outlineControls) els.outlineControls.style.display = els.outline.checked ? 'flex' : 'none'
  })
  els.depthCue?.addEventListener('change', () => {
    expMode.setDepthCue(els.depthCue.checked)
    if (els.depthCueControls) els.depthCueControls.style.display = els.depthCue.checked ? 'flex' : 'none'
  })
  els.outlineColor?.addEventListener('input', () => expMode.setOutlineColor(els.outlineColor.value))
  els.depthCueColor?.addEventListener('input', () => expMode.setDepthCueColor(els.depthCueColor.value))

  /** slider → setter → label, with a fixed number of decimals. */
  function _bindRange(el, lab, setter, dp = 2) {
    el?.addEventListener('input', () => {
      const v = Number(el.value)
      setter(v)
      if (lab) lab.textContent = v.toFixed(dp)
    })
  }
  _bindRange(els.outlineStrength,  els.outlineStrengthLab,  v => expMode.setOutlineStrength(v))
  _bindRange(els.outlineThickness, els.outlineThicknessLab, v => expMode.setOutlineThickness(v), 1)
  _bindRange(els.outlineJump,      els.outlineJumpLab,      v => expMode.setOutlineDepthJump(v), 3)
  _bindRange(els.depthCueStrength, els.depthCueStrengthLab, v => expMode.setDepthCueStrength(v))

  // ── Camera ─────────────────────────────────────────────────────────────────
  els.fov?.addEventListener('input', () => {
    const v = Number(els.fov.value)
    expMode.setFOV(v)
    if (els.fovLabel) els.fovLabel.textContent = `${v}°`
    if (els.parallel) els.parallel.checked = expMode.getSettings().parallel
  })
  els.parallel?.addEventListener('change', () => {
    expMode.setParallel(els.parallel.checked)
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
    expMode.setExportSize(w, h)
    _refreshExportNote()
  }

  els.resPreset?.addEventListener('change', () => _applyResPreset(els.resPreset.value))
  for (const el of [els.resW, els.resH]) {
    el?.addEventListener('change', () => {
      if (els.resPreset) els.resPreset.value = 'custom'
      expMode.setExportSize(Number(els.resW.value), Number(els.resH.value))
      _refreshExportNote()
    })
  }

  els.exportBtn?.addEventListener('click', async () => {
    if (!els.exportBtn) return
    const label = els.exportBtn.textContent
    els.exportBtn.disabled = true
    els.exportBtn.textContent = 'Rendering…'
    try {
      const s = expMode.getSettings()
      const blob = await expMode.renderToBlob(s.exportWidth, s.exportHeight)
      if (blob) {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `nadoc-figure-${s.exportWidth}x${s.exportHeight}.png`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      console.error('[photo-exp] export failed:', err)
      if (els.exportNote) els.exportNote.textContent = `Export failed: ${err.message}`
    } finally {
      els.exportBtn.disabled = false
      els.exportBtn.textContent = label
    }
  })

  _initCard('lighting')
  _initCard('camera')
  _initCard('export')
  _initCard('figure')
  _initCard('materials')
  _initCard('bg')

  els.keyDirReset?.addEventListener('click', () => {
    expMode.resetKeyDirection()
    syncToState()
  })

  return {
    syncToState,
    onEnter: () => { syncToState(); _startStatusPolling() },
    onExit:  () => { _stopStatusPolling() },
    dispose: _stopStatusPolling,
  }
}
