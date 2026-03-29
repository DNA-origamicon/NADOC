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
  }
  return offsets
}

// ── XB arc map for expanded spacing ──────────────────────────────────────────

const _XB_ZERO = new THREE.Vector3()

/**
 * Build an xbArcMap for expanded spacing — same interface as unfold_view's
 * _buildXbArcMap, but the "arc" simply shifts each XB bead by a linear blend
 * of its two anchor helix offsets rather than a full Bézier in 2D space.
 *
 * bezierAt(beadT, gx, gy, gz) → THREE.Vector3  target position at t=1
 *
 * @param {Map<string, THREE.Vector3>} offsets  helix_id → world-space offset
 * @param {object} design  current Design
 * @returns {Map<string, {bezierAt: Function}>}
 */
function _buildXbArcMap(offsets, design) {
  const xbArcMap = new Map()
  if (!design?.crossover_bases?.length) return xbArcMap

  const strandById = new Map()
  for (const s of (design.strands ?? [])) strandById.set(s.id, s)
  const crossoverById = new Map()
  for (const c of (design.crossovers ?? [])) crossoverById.set(c.id, c)

  for (const cb of design.crossover_bases) {
    const cx = crossoverById.get(cb.crossover_id)
    if (!cx) continue
    const sA = strandById.get(cx.strand_a_id)
    const sB = strandById.get(cx.strand_b_id)
    if (!sA || !sB) continue
    const hAid = sA.domains[cx.domain_a_index]?.helix_id
    const hBid = sB.domains[cx.domain_b_index]?.helix_id
    if (!hAid || !hBid) continue
    const offA = offsets.get(hAid) ?? _XB_ZERO
    const offB = offsets.get(hBid) ?? _XB_ZERO
    // Capture for closure
    const oax = offA.x, oay = offA.y, oaz = offA.z
    const obx = offB.x, oby = offB.y, obz = offB.z
    xbArcMap.set(cb.id, {
      bezierAt(beadT, gx, gy, gz) {
        return new THREE.Vector3(
          gx + (1 - beadT) * oax + beadT * obx,
          gy + (1 - beadT) * oay + beadT * oby,
          gz + (1 - beadT) * oaz + beadT * obz,
        )
      },
    })
  }
  return xbArcMap
}

// ── Module ────────────────────────────────────────────────────────────────────

export function initExpandedSpacing(
  designRenderer,
  getBluntEnds,
  getCrossoverLocations,
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
    // helix_renderer / design_renderer: backbone beads, axis arrows, slabs, cones
    designRenderer.applyUnfoldOffsets(offsets, t)
    // XB (extra crossover bases) beads
    const xbArcMap = _buildXbArcMap(offsets, currentDesign)
    designRenderer.applyUnfoldOffsetsExtraBases(xbArcMap, t)
    // Crossover arcs (lines between helices)
    getUnfoldView?.()?.applyHelixOffsets(offsets, t)
    // Overlays
    getBluntEnds?.()?.applyUnfoldOffsets(offsets, t)
    getCrossoverLocations?.()?.applyUnfoldOffsets(offsets, t)
    getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t)
    getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t)
    getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, null, xbArcMap)
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
      _animate(_currentT, 0, offsets, () => {
        _active = false
        _hidePanel()
      })
    } else {
      _showPanel()
      _animate(_currentT, 1, offsets, () => { _active = true })
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
  store.subscribe((newState, prevState) => {
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
