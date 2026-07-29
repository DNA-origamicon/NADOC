/**
 * Experimental photo-mode panel — the controls for scene/photo_exp_mode.js.
 *
 * Thin by design: it reads DOM elements, pushes values into the mode controller,
 * and renders a status line. All rendering decisions live in the mode; this file
 * only translates clicks into calls, so the experiment can be re-skinned or
 * thrown away without touching the renderer.
 */

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
    _refreshShadowDepth()
    if (els.bgType)  els.bgType.value = s.bgType
    if (els.bgColor) els.bgColor.value = s.bgColor
    _refreshResolution()
    _refreshStatus()
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

  return {
    syncToState,
    onEnter: () => { syncToState(); _startStatusPolling() },
    onExit:  () => { _stopStatusPolling() },
    dispose: _stopStatusPolling,
  }
}
