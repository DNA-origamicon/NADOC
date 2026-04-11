/**
 * Expanded Helix Spacing — cosmetic-only lateral expansion of helix positions.
 *
 * Toggled by 'Q'. Animates over 300 ms. A slider panel (upper-right) lets the
 * user tune the target spacing from 2.25 nm (natural) to 10 nm.
 *
 * Architecture: reuses applyUnfoldOffsets() on all renderers — the spacing
 * offsets are per-helix 3D translation vectors (zero along the helix axis,
 * non-zero laterally). The Design model is never modified.
 *
 * Auto-disabled when unfold view or slice plane activates.
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'

const ANIM_DURATION_MS  = 300
const DEFAULT_SPACING_NM = 5.0
const MIN_SPACING_NM    = 2.25   // natural HC / SQ helix spacing
const MAX_SPACING_NM    = 10.0

// ── Offset computation ────────────────────────────────────────────────────────

/**
 * Detect the dominant helix axis direction from the first helix.
 * Returns 'Z', 'Y', or 'X' — the axis along which helices are extruded.
 * Lateral expansion is applied to the OTHER two axes.
 */
function _axisDir(design) {
  const h = design.helices[0]
  if (!h) return 'Z'
  const dx = Math.abs(h.axis_end.x - h.axis_start.x)
  const dy = Math.abs(h.axis_end.y - h.axis_start.y)
  const dz = Math.abs(h.axis_end.z - h.axis_start.z)
  if (dz >= dx && dz >= dy) return 'Z'
  if (dy >= dx && dy >= dz) return 'Y'
  return 'X'
}

/**
 * Compute per-helix 3D offset vectors for expanding spacing to `spacingNm`.
 * Offsets are zero along the helix axis; lateral components scale each helix
 * outward from the centroid of all helix lateral positions.
 *
 * @param {object} design       – Design model (design.helices used)
 * @param {number} spacingNm    – Target centre-to-centre spacing in nm
 * @returns {Map<string, THREE.Vector3>}  helix_id → world-space offset at t=1
 */
function _computeOffsets(design, spacingNm) {
  const helices = design.helices
  if (!helices.length) return new Map()

  const axis = _axisDir(design)
  const scale = spacingNm / MIN_SPACING_NM   // e.g. 5.0 / 2.25 ≈ 2.22×
  console.log(`[EXPAND] _computeOffsets: ${helices.length} helices, axis=${axis}, spacing=${spacingNm.toFixed(2)} nm, scale=${scale.toFixed(3)}`)

  // For each helix, extract its two lateral coordinates.
  const lats = helices.map(h => {
    const s = h.axis_start
    if (axis === 'Z') return { id: h.id, u: s.x, v: s.y }
    if (axis === 'Y') return { id: h.id, u: s.x, v: s.z }
    return                 { id: h.id, u: s.y, v: s.z }
  })

  // Centroid of lateral positions
  const cu = lats.reduce((a, l) => a + l.u, 0) / lats.length
  const cv = lats.reduce((a, l) => a + l.v, 0) / lats.length

  const offsets = new Map()
  for (const l of lats) {
    const du = (l.u - cu) * (scale - 1)
    const dv = (l.v - cv) * (scale - 1)
    let dx = 0, dy = 0, dz = 0
    if (axis === 'Z') { dx = du; dy = dv }
    else if (axis === 'Y') { dx = du; dz = dv }
    else              { dy = du; dz = dv }
    offsets.set(l.id, new THREE.Vector3(dx, dy, dz))
    console.log(`[EXPAND]   helix ${l.id.slice(0, 8)}: offset=(${dx.toFixed(3)}, ${dy.toFixed(3)}, ${dz.toFixed(3)})`)
  }
  return offsets
}

// ── XB arc map for expanded spacing ──────────────────────────────────────────

const _XB_ZERO = new THREE.Vector3()

/**
 * Build an extArcMap for expanded spacing.
 * Maps extension_id → Map<bp_index, {x,y,z}> target position at t=1.
 * Each bead is shifted by its parent helix's lateral offset.
 *
 * @param {Map<string, THREE.Vector3>} offsets  helix_id → world-space offset
 * @param {object} design  current Design
 * @returns {Map<string, Map<number, {x,y,z}>>}
 */
function _buildExtArcMap(offsets, design) {
  const extArcMap = new Map()
  if (!design?.extensions?.length) return extArcMap

  const { currentGeometry } = store.getState()
  if (!currentGeometry?.length) return extArcMap

  // Index extension nucleotides by extension_id → Map<bp_index, nuc>
  const extNucs = new Map()
  for (const nuc of currentGeometry) {
    if (!nuc.extension_id) continue
    if (!extNucs.has(nuc.extension_id)) extNucs.set(nuc.extension_id, new Map())
    extNucs.get(nuc.extension_id).set(nuc.bp_index, nuc)
  }

  for (const ext of design.extensions) {
    const nucMap = extNucs.get(ext.id)
    if (!nucMap?.size) continue

    const strand = design.strands?.find(s => s.id === ext.strand_id)
    if (!strand) continue

    const termDom = ext.end === 'five_prime'
      ? strand.domains[0]
      : strand.domains[strand.domains.length - 1]
    if (!termDom) continue

    const helixOff = offsets.get(termDom.helix_id) ?? _XB_ZERO
    const beadPosMap = new Map()
    for (const [bpIdx, nuc] of nucMap) {
      beadPosMap.set(bpIdx, {
        x: nuc.backbone_position[0] + helixOff.x,
        y: nuc.backbone_position[1] + helixOff.y,
        z: nuc.backbone_position[2] + helixOff.z,
      })
    }
    extArcMap.set(ext.id, beadPosMap)
  }
  return extArcMap
}

// ── Module ────────────────────────────────────────────────────────────────────

export function initExpandedSpacing(
  designRenderer,
  getBluntEnds,
  getLoopSkipHighlight,
  getOverhangLocations,
  getSequenceOverlay,
  getUnfoldView,
) {
  let _active    = false
  let _animFrame = null
  let _currentT  = 0
  let _spacingNm = DEFAULT_SPACING_NM

  // ── Slider panel wiring ───────────────────────────────────────────────────
  const _panel    = document.getElementById('spacing-panel')
  const _slider   = document.getElementById('spacing-slider')
  const _valLabel = document.getElementById('spacing-value')

  function _syncSliderLabel(nm) {
    if (_valLabel) _valLabel.textContent = `${nm.toFixed(2)} nm`
  }

  if (_slider) {
    _slider.value = DEFAULT_SPACING_NM
    _syncSliderLabel(DEFAULT_SPACING_NM)
    _slider.addEventListener('input', () => {
      const nm = parseFloat(_slider.value)
      _spacingNm = nm
      _syncSliderLabel(nm)
      if (_active || _currentT > 0) _reapplyImmediate()
    })
  }

  function _showPanel() { _panel?.classList.add('active') }
  function _hidePanel() { _panel?.classList.remove('active') }

  // ── Renderer dispatch ─────────────────────────────────────────────────────

  function _applyAll(offsets, t) {
    const { currentDesign } = store.getState()
    console.log(`[EXPAND] _applyAll: t=${t.toFixed(3)}, offsets=${offsets.size} helices`)
    // helix_renderer / design_renderer: backbone beads, axis arrows, slabs, cones
    designRenderer.applyUnfoldOffsets(offsets, t)
    // Extension beads (__ext_ helices — strand overhangs / extended ends)
    const extArcMap = _buildExtArcMap(offsets, currentDesign)
    designRenderer.applyUnfoldOffsetsExtensions(extArcMap, t)
    // Crossover arcs (lines between helices)
    getUnfoldView?.()?.applyHelixOffsets(offsets, t)
    // Overlays
    getBluntEnds?.()?.applyUnfoldOffsets(offsets, t)
    getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t)
    getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t)
    getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, null)
  }

  function _reapplyImmediate() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    _applyAll(_computeOffsets(currentDesign, _spacingNm), _currentT)
  }

  // ── Animation ─────────────────────────────────────────────────────────────

  function _animate(fromT, toT, offsets, onDone) {
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null }
    const startTime = performance.now()

    function frame(now) {
      const raw = Math.min((now - startTime) / ANIM_DURATION_MS, 1)
      const t   = fromT + (toT - fromT) * raw
      _applyAll(offsets, t)
      _currentT = t
      if (raw >= 1) {
        _animFrame = null
        onDone?.()
      } else {
        _animFrame = requestAnimationFrame(frame)
      }
    }
    _animFrame = requestAnimationFrame(frame)
  }

  // ── Public API ────────────────────────────────────────────────────────────

  function toggle() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return

    const offsets = _computeOffsets(currentDesign, _spacingNm)
    if (_active) {
      console.log(`[EXPAND] toggle OFF: ${currentDesign.helices.length} helices, spacing=${_spacingNm.toFixed(2)} nm, t=${_currentT.toFixed(3)}→0`)
      _animate(_currentT, 0, offsets, () => {
        _active = false
        _hidePanel()
        console.log('[EXPAND] collapse complete — t=0, positions restored')
      })
    } else {
      console.log(`[EXPAND] toggle ON: ${currentDesign.helices.length} helices, spacing=${_spacingNm.toFixed(2)} nm, t=${_currentT.toFixed(3)}→1`)
      _showPanel()
      _animate(_currentT, 1, offsets, () => {
        _active = true
        console.log('[EXPAND] expand complete — t=1')
      })
    }
  }

  /**
   * Animate back to t=0 (natural spacing) without user interaction.
   * Called when unfold view / slice plane activates.
   */
  function forceOff() {
    if (!_active && _currentT === 0) return
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { _active = false; _hidePanel(); return }
    const offsets = _computeOffsets(currentDesign, _spacingNm)
    _animate(_currentT, 0, offsets, () => {
      _active = false
      _hidePanel()
    })
  }

  function setSpacing(nm) {
    _spacingNm = Math.max(MIN_SPACING_NM, Math.min(MAX_SPACING_NM, nm))
    if (_slider) _slider.value = _spacingNm
    _syncSliderLabel(_spacingNm)
    if (_active || _currentT > 0) _reapplyImmediate()
  }

  // ── Re-apply after design/geometry changes ────────────────────────────────
  // When the scene rebuilds (new extrude, design load, etc.) all bead positions
  // reset to their base values.  If spacing is active re-apply immediately so
  // the expanded view is preserved without needing to re-toggle.
  store.subscribeSlice('design', (newState, prevState) => {
    if (
      (newState.currentGeometry !== prevState.currentGeometry ||
       newState.currentDesign  !== prevState.currentDesign) &&
      (_active || _currentT > 0) &&
      newState.currentDesign?.helices?.length
    ) {
      // Snap to current t — no animation, just restore the visual state.
      _applyAll(_computeOffsets(newState.currentDesign, _spacingNm), _currentT)
    }
  })

  return {
    toggle,
    forceOff,
    isActive:   () => _active,
    setSpacing,
    getSpacing: () => _spacingNm,
  }
}
