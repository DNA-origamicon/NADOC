/**
 * Surface capture-strand setup UI — the "Add surface strands" sub-section of the
 * oxDNA "Hard surface" card (Dynamics tab).  Lets the user disperse ssDNA capture
 * strands (complementary to the origami overhangs) across a coverage patch so the
 * origami hybridizes to the surface and immobilizes.
 *
 * Owns the fields + a live count preview + the normalized spec.  A hard surface must be
 * enabled first (the strands attach to its plane) — the enable checkbox is gated on it.
 * The build itself lives in backend/physics/oxdna_surface_strands.py; the 3D preview
 * (translucent patch + anchor dots + centre gizmo) lives in scene/surface_strands_overlay.js
 * and is driven from onChange.  Placement / count math: scene/surface_strands_math.js (pure).
 *
 * Factory: initOxdnaSurfaceStrandsSetup({ onChange, generateSequence, ids }) →
 *   { getStrandsSpec, isEnabled, applyConfig, setSurfaceEnabled, setOffset, refresh }.
 *   getStrandsSpec() → normalized spec (see surfaceStrandsSpec) or null when off.
 *   generateSequence(length) → Promise<string|null> — the "Gen" button reuses the same
 *   Johnson-et-al. overhang algorithm (POST /design/random-sequence).
 *   setSurfaceEnabled(on) — the hard-surface prerequisite gate (call on floor toggle).
 *   setOffset(xNm, yNm) — the centre gizmo pushes the dragged patch centre back here.
 */

import { surfaceStrandsSpec, surfaceStrandArea } from '../scene/surface_strands_math.js'

const DEFAULT_IDS = {
  enable: 'oxdna-surfstrand-enable', controls: 'oxdna-surfstrand-controls',
  seq: 'oxdna-surfstrand-seq', gen: 'oxdna-surfstrand-gen', end: 'oxdna-surfstrand-end',
  density: 'oxdna-surfstrand-density', shape: 'oxdna-surfstrand-shape',
  size: 'oxdna-surfstrand-size', sizeLabel: 'oxdna-surfstrand-size-label',
  offx: 'oxdna-surfstrand-offx', offy: 'oxdna-surfstrand-offy',
  seed: 'oxdna-surfstrand-seed', seedNew: 'oxdna-surfstrand-seed-new',
  field: 'oxdna-surfstrand-field', status: 'oxdna-surfstrand-status',
  highlight: 'oxdna-surfstrand-highlight', showshape: 'oxdna-surfstrand-showshape',
  color: 'oxdna-surfstrand-color', colorHex: 'oxdna-surfstrand-color-hex',
}

const GEN_DEFAULT_LEN = 8   // fallback when the sequence box is empty

export function initOxdnaSurfaceStrandsSetup({ onChange = null, generateSequence = null, ids = null } = {}) {
  const id = { ...DEFAULT_IDS, ...(ids || {}) }
  const $ = (k) => document.getElementById(id[k])
  const enableChk = $('enable')
  const controls = $('controls')
  const noop = {
    getStrandsSpec: () => null, isEnabled: () => false, applyConfig: () => {},
    setSurfaceEnabled: () => {}, setOffset: () => {}, refresh: () => {},
  }
  if (!enableChk || !controls) return noop

  const seqIn = $('seq'), genBtn = $('gen'), endSel = $('end'), densIn = $('density'), shapeSel = $('shape')
  const sizeIn = $('size'), sizeLbl = $('sizeLabel'), offxIn = $('offx'), offyIn = $('offy')
  const seedIn = $('seed'), seedNewBtn = $('seedNew'), fieldChk = $('field'), statusEl = $('status')
  const highlightChk = $('highlight'), showshapeChk = $('showshape')
  const colorIn = $('color'), colorHexIn = $('colorHex')

  let _enabled = false
  let _surfaceOn = false   // hard-surface prerequisite

  function _rawFields() {
    return {
      enabled: _enabled,
      sequence: seqIn?.value || '',
      attachEnd: endSel?.value || "5'",
      shape: shapeSel?.value || 'circle',
      sizeNm: sizeIn?.value,
      densityPerUm2: densIn?.value,
      offsetXNm: offxIn?.value,
      offsetYNm: offyIn?.value,
      seed: seedIn?.value,
      subjectToField: fieldChk ? !!fieldChk.checked : true,
    }
  }
  function getStrandsSpec() { return surfaceStrandsSpec(_rawFields()) }
  function isEnabled() { return _enabled }
  // Display controls (drive the 3D overlay via onChange → main).
  function getHighlight() { return highlightChk ? !!highlightChk.checked : true }
  function getShapePreview() { return showshapeChk ? !!showshapeChk.checked : true }
  function getColor() { return colorIn?.value || '#00ffff' }   // wheel is the canonical value (hex syncs to it)

  function _setStatus(text, color = '#8b949e') {
    if (statusEl) { statusEl.textContent = text; statusEl.style.color = color }
  }
  function _syncControlsVisibility() {
    if (controls) controls.style.display = _enabled ? 'flex' : 'none'
  }
  // Circle → "Diameter", square → "Width"; the single size box means both.
  function _syncSizeLabel() {
    if (sizeLbl) sizeLbl.textContent = (shapeSel?.value === 'square') ? 'Width' : 'Diameter'
  }

  function _render() {
    onChange?.()
    _syncSizeLabel()
    if (!_surfaceOn) { _setStatus('Enable the hard surface first — capture strands attach to it.'); return }
    if (!_enabled) { _setStatus('Off — tick "Add surface strands" to disperse capture strands.'); return }
    const spec = getStrandsSpec()
    if (!spec || !spec.sequence) { _setStatus('Enter a capture-strand sequence (A/C/G/T).', '#e0a800'); return }
    if (!(spec.densityPerUm2 > 0) || !(spec.sizeNm > 0)) { _setStatus('Set a density and coverage size > 0.', '#e0a800'); return }
    const area = surfaceStrandArea(spec)
    const noun = spec.count === 1 ? 'strand' : 'strands'
    _setStatus(`${spec.count} ${noun} · ${spec.densityPerUm2}/µm² over ${Math.round(area)} nm² ${spec.shape}.`, '#e0a800')
  }

  // Reuse the overhang Gen algorithm: length = current sequence length (or a default).
  async function _gen() {
    if (!generateSequence) return
    const len = (seqIn?.value || '').replace(/[^ACGTacgt]/g, '').length || GEN_DEFAULT_LEN
    genBtn.disabled = true
    try {
      const seq = await generateSequence(len)
      if (seq && seqIn) { seqIn.value = seq; _render() }
    } catch { /* best-effort — leave the field as-is on failure */ }
    finally { genBtn.disabled = false }
  }

  // Pick a fresh random seed → re-scatters the preview (determinism is per-seed).
  function _newSeed() {
    if (!seedIn) return
    seedIn.value = String(Math.floor(Math.random() * 1_000_000_000))
    _render()
  }

  // ── Inputs ───────────────────────────────────────────────────────────────────
  enableChk.addEventListener('change', () => {
    if (!_surfaceOn) { enableChk.checked = false; return }   // gated: surface required
    _enabled = !!enableChk.checked
    if (_enabled) {   // first turning the options ON → highlight + coverage shape on
      if (highlightChk) highlightChk.checked = true
      if (showshapeChk) showshapeChk.checked = true
    }
    _syncControlsVisibility(); _render()
  })
  for (const el of [seqIn, endSel, densIn, sizeIn, offxIn, offyIn, seedIn]) el?.addEventListener('input', _render)
  shapeSel?.addEventListener('change', _render)
  fieldChk?.addEventListener('change', _render)
  for (const el of [highlightChk, showshapeChk]) el?.addEventListener('change', _render)
  // Colour: wheel and hex text stay in sync; both drive the strand colour.
  colorIn?.addEventListener('input', () => { if (colorHexIn) colorHexIn.value = colorIn.value; _render() })
  colorHexIn?.addEventListener('input', () => {
    const v = (colorHexIn.value || '').trim()
    if (/^#[0-9a-fA-F]{6}$/.test(v)) { if (colorIn) colorIn.value = v.toLowerCase(); _render() }
  })
  genBtn?.addEventListener('click', _gen)
  seedNewBtn?.addEventListener('click', _newSeed)
  _syncControlsVisibility(); _syncSizeLabel()

  // Hard-surface prerequisite gate.  Off → force the strands off and disable the checkbox.
  function setSurfaceEnabled(on) {
    _surfaceOn = !!on
    if (enableChk) {
      enableChk.disabled = !_surfaceOn
      enableChk.style.cursor = _surfaceOn ? 'pointer' : 'not-allowed'
    }
    if (!_surfaceOn && _enabled) {
      _enabled = false
      if (enableChk) enableChk.checked = false
      _syncControlsVisibility()
    }
    _render()
  }

  // The centre gizmo drag pushes the new in-plane (x, y) offset back into the fields.
  function setOffset(xNm, yNm) {
    if (offxIn && Number.isFinite(xNm)) offxIn.value = String(Math.round(xNm * 10) / 10)
    if (offyIn && Number.isFinite(yNm)) offyIn.value = String(Math.round(yNm * 10) / 10)
    _render()
  }

  // Repopulate from a stored spec (echo-back when a job is selected). Null → off.
  function applyConfig(spec) {
    _enabled = !!(spec && spec.enabled)
    if (enableChk) enableChk.checked = _enabled
    if (spec) {
      if (seqIn && spec.sequence != null) seqIn.value = spec.sequence
      if (endSel && spec.attachEnd) endSel.value = spec.attachEnd
      if (shapeSel && spec.shape) shapeSel.value = spec.shape
      if (sizeIn && spec.sizeNm != null) sizeIn.value = String(spec.sizeNm)
      if (densIn && spec.densityPerUm2 != null) densIn.value = String(spec.densityPerUm2)
      if (offxIn && spec.offsetXNm != null) offxIn.value = String(spec.offsetXNm)
      if (offyIn && spec.offsetYNm != null) offyIn.value = String(spec.offsetYNm)
      if (seedIn && spec.seed != null) seedIn.value = String(spec.seed)
      if (fieldChk) fieldChk.checked = spec.subjectToField !== false
    }
    // Selecting a job entry defaults the display emphasis OFF (toggle on to highlight for figures).
    if (highlightChk) highlightChk.checked = false
    if (showshapeChk) showshapeChk.checked = false
    _syncControlsVisibility(); _render()
  }

  return {
    getStrandsSpec, isEnabled, applyConfig, setSurfaceEnabled, setOffset,
    getHighlight, getShapePreview, getColor, refresh: _render,
  }
}
