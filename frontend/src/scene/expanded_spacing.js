/**
 * Expanded Helix Spacing — cosmetic-only lateral expansion of helix positions.
 *
 * Two modes share one offset channel and one animation:
 *   'manual'     — toggled by 'Q'. A slider panel (upper-right) tunes the target
 *                  spacing from 2.25 nm (natural) to 10 nm.
 *   'extra-base' — View ▸ Adjust for Extra Bases. Snaps to the MD-measured
 *                  relaxed spacing for the design's largest extra-base count
 *                  (see `extra_base_spacing.js` for the numbers and provenance).
 *                  No slider — the spacing is a measurement, not a preference.
 *
 * They are mutually exclusive by construction: `_mode` decides which target
 * spacing `_targetSpacing()` returns, so there is never a second writer racing
 * this one for the offsets.
 *
 * Architecture: reuses applyUnfoldOffsets() on all renderers — the spacing
 * offsets are per-helix 3D translation vectors (zero along the helix axis,
 * non-zero laterally). The Design model is never modified: this is display
 * state only, and nothing here is ever written back to topology.
 *
 * Auto-disabled when unfold view or slice plane activates.
 */

import * as THREE from 'three'
import { store }  from '../state/store.js'
import { adjustedSpacingForDesign } from './extra_base_spacing.js'
import {
  DEFAULT_EXPANDED_HELIX_SPACING_NM,
  NATURAL_HELIX_SPACING_NM,
  expandedHelixOffsetFrame,
} from './expanded_helix_offsets.js'

const ANIM_DURATION_MS  = 300
const DEFAULT_SPACING_NM = DEFAULT_EXPANDED_HELIX_SPACING_NM
const MAX_SPACING_NM    = 10.0

// ── Offset computation ────────────────────────────────────────────────────────

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
  const frame = expandedHelixOffsetFrame(design, spacingNm)
  if (!frame) return new Map()
  const scale = spacingNm / NATURAL_HELIX_SPACING_NM
  console.log(`[EXPAND] _computeOffsets: ${frame.offsets.size} helices, axis=${frame.axis}, spacing=${spacingNm.toFixed(2)} nm, scale=${scale.toFixed(3)}`)
  const offsets = new Map()
  for (const [id, value] of frame.offsets) {
    const offset = new THREE.Vector3(...value)
    offsets.set(id, offset)
    console.log(`[EXPAND]   helix ${id.slice(0, 8)}: offset=(${offset.x.toFixed(3)}, ${offset.y.toFixed(3)}, ${offset.z.toFixed(3)})`)
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
export function buildExtensionArcMap(offsets, design, geometry = store.getState().currentGeometry) {
  const extArcMap = new Map()
  if (!design?.extensions?.length) return extArcMap

  if (!geometry?.length) return extArcMap

  // Index extension nucleotides by extension_id → Map<bp_index, nuc>
  const extNucs = new Map()
  for (const nuc of geometry) {
    if (!nuc.extension_id) continue
    if (!extNucs.has(nuc.extension_id)) extNucs.set(nuc.extension_id, new Map())
    extNucs.get(nuc.extension_id).set(nuc.bp_index, nuc)
  }

  const strandById = new Map((design.strands ?? []).map(strand => [strand.id, strand]))
  for (const ext of design.extensions) {
    const nucMap = extNucs.get(ext.id)
    if (!nucMap?.size) continue

    const strand = strandById.get(ext.strand_id)
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
  getAtomisticRenderer,
  onModeChange,     // (isExtraBaseAdjustActive: boolean) => void — menu-pill sync
  getAtomSurface,   // () => atom_surface_display — drives the MD-seed atomistic view
) {
  let _active    = false
  let _animFrame = null
  let _currentT  = 0
  let _spacingNm = DEFAULT_SPACING_NM
  let _mode      = 'manual'   // 'manual' (Q + slider) | 'extra-base' (measured)
  // `_active` only flips when the 300 ms animation lands, so it is the SETTLED
  // state.  `_desiredOn` flips synchronously on the click, and is what decides
  // the next toggle's direction and what a menu pill should read — otherwise a
  // second click inside the animation window reads the pre-transition value and
  // expands twice instead of collapsing.
  let _desiredOn = false

  const _isXbAdjust = () => _desiredOn && _mode === 'extra-base'

  /**
   * Publish the extra-base pill state.  Called from EVERY path that can change
   * mode or turn spacing off — the menu toggle, the Q toggle taking ownership,
   * and `forceOff` from slice/unfold/extrude — so the pill cannot go stale.
   */
  function _publishMode() { onModeChange?.(_isXbAdjust()) }

  /**
   * Spacing the current mode wants, in nm.
   *
   * In extra-base mode this is re-derived from the design on every call rather
   * than cached, so editing a crossover's inserts while the view is on moves
   * the helices to match on the next re-apply.
   *
   * @param {object} [design]  defaults to the live store design
   */
  function _targetSpacing(design) {
    if (_mode !== 'extra-base') return _spacingNm
    return adjustedSpacingForDesign(design ?? store.getState().currentDesign)
  }

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
    const extArcMap = buildExtensionArcMap(offsets, currentDesign)
    designRenderer.applyUnfoldOffsetsExtensions(extArcMap, t)
    // Crossover arcs (lines between helices)
    getUnfoldView?.()?.applyHelixOffsets(offsets, t)
    // Overlays
    getBluntEnds?.()?.applyUnfoldOffsets(offsets, t)
    getLoopSkipHighlight?.()?.applyUnfoldOffsets(offsets, t)
    getOverhangLocations?.()?.applyUnfoldOffsets(offsets, t)
    getSequenceOverlay?.()?.applyUnfoldOffsets(offsets, t, null)
    // Atomistic atoms (extra-base atoms interpolate between src/dst helix offsets).
    // SKIPPED while the MD-seed view is on: those atoms were BUILT at the expanded
    // lattice, so offsetting them again would double the expansion.
    if (!getAtomSurface?.()?.isSeedLatticeActive?.()) {
      getAtomisticRenderer?.()?.applyUnfoldOffsets?.(offsets, t)
    }
    // Re-position selection glow spheres to match updated bead positions.
    // Must be last — all entry.pos vectors must be updated before refresh.
    designRenderer.refreshAllGlow()
  }

  // ── MD seed atomistic view ────────────────────────────────────────────────
  //
  // The atomistic reps switch to the t=0 pre-minimisation build while this view is
  // on.  Extra-base positions are NOT touched here: the CG representation is the
  // single definition of where an insert sits, and the atomistic build follows it.

  function _showSeedAtoms()  { getAtomSurface?.()?.setSeedLattice?.('auto') }
  function _clearSeedAtoms() { getAtomSurface?.()?.setSeedLattice?.(null) }

  function _reapplyImmediate() {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return
    _applyAll(_computeOffsets(currentDesign, _targetSpacing(currentDesign)), _currentT)
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

  /**
   * Turn a mode on or off, animating between natural and target spacing.
   * Switching straight from one active mode to the other re-animates from the
   * current offsets to the new target without collapsing through t=0.
   */
  function _setMode(mode, showPanel) {
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) return

    const turningOff = _desiredOn && _mode === mode
    _mode = mode
    _desiredOn = !turningOff
    _publishMode()
    const spacing = _targetSpacing(currentDesign)
    const offsets = _computeOffsets(currentDesign, spacing)

    if (turningOff) {
      console.log(`[EXPAND] ${mode} OFF: ${currentDesign.helices.length} helices, spacing=${spacing.toFixed(2)} nm, t=${_currentT.toFixed(3)}→0`)
      // Drop the seeded inserts first so the collapse animates the ordinary arc all
      // the way back, rather than leaving beads pinned at seed positions until t=0.
      _clearSeedAtoms()
      _animate(_currentT, 0, offsets, () => {
        _active = false
        _hidePanel()
        console.log('[EXPAND] collapse complete — t=0, positions restored')
      })
    } else {
      console.log(`[EXPAND] ${mode} ON: ${currentDesign.helices.length} helices, spacing=${spacing.toFixed(2)} nm, t=${_currentT.toFixed(3)}→1`)
      if (showPanel) _showPanel(); else _hidePanel()
      // Seed positions are absolute at the FINAL spacing, so applying them mid-slide
      // would snap the inserts ahead of the helices. Load once the lattice settles.
      _animate(_currentT, 1, offsets, () => {
        _active = true
        console.log('[EXPAND] expand complete — t=1')
        if (mode === 'extra-base') _showSeedAtoms()
      })
    }
  }

  function toggle() { _setMode('manual', true) }

  /**
   * View ▸ Adjust for Extra Bases — snap the lattice to the MD-measured
   * relaxed spacing for this design's largest extra-base count.
   */
  function toggleExtraBaseAdjust() { _setMode('extra-base', false) }

  /**
   * Animate back to t=0 (natural spacing) without user interaction.
   * Called when unfold view / slice plane activates.
   */
  function forceOff() {
    _desiredOn = false
    _publishMode()
    _clearSeedAtoms()
    if (!_active && _currentT === 0) return
    const { currentDesign } = store.getState()
    if (!currentDesign?.helices?.length) { _active = false; _hidePanel(); return }
    const offsets = _computeOffsets(currentDesign, _targetSpacing(currentDesign))
    _animate(_currentT, 0, offsets, () => {
      _active = false
      _hidePanel()
    })
  }

  function setSpacing(nm) {
    _spacingNm = Math.max(MIN_SPACING_NM, Math.min(MAX_SPACING_NM, nm))
    if (_slider) _slider.value = _spacingNm
    _syncSliderLabel(_spacingNm)
    // A manual spacing edit takes ownership back from the measured mode —
    // otherwise the slider would move nothing and look broken.
    if (_mode === 'extra-base' && (_active || _currentT > 0)) {
      _mode = 'manual'
      _clearSeedAtoms()   // the seed was built for the measured spacing, not this one
      _publishMode()
    }
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
      // In extra-base mode the target is re-derived from the NEW design, so an
      // edit that changes the largest insert count re-spaces the bundle here.
      _applyAll(
        _computeOffsets(newState.currentDesign, _targetSpacing(newState.currentDesign)),
        _currentT,
      )
      // A design edit invalidates the seed build; re-request it so the atomistic
      // reps follow the new topology.
      if (_mode === 'extra-base' && _desiredOn) _showSeedAtoms()
    }
  })

  return {
    toggle,
    toggleExtraBaseAdjust,
    forceOff,
    isActive:   () => _active,
    isExtraBaseAdjustActive: _isXbAdjust,
    setSpacing,
    getSpacing: () => _spacingNm,
  }
}
