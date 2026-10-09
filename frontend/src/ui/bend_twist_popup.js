/**
 * Bend & Twist parameter popup.
 *
 * Opened by main.js when the deformation editor reaches the BOTH state.
 * Communicates back to the editor via the callback object passed to init().
 *
 * Compass rose: draggable SVG arm; 0° = +X in bundle cross-section,
 * angles increase counter-clockwise (standard math convention).
 */

import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { BDNA_RISE_PER_BP } from '../constants.js'
import { store } from '../state/store.js'
import { showToast } from './toast.js'
import { moveRotateSelectionLabels } from '../scene/move_rotate_panel.js'
import { targetState } from '../scene/deformation_targets.js'
import { validateDeformation } from '../api/client.js'
import {
  setDeformSessionClusterIds,
  getDeformDefaultClusterIds,
  getDeformSessionTargets,
} from '../scene/deformation_editor.js'

// ── DOM refs (grabbed once on init) ─────────────────────────────────────────

let _selectionUI = null
let _selectionSection = null
let _floating = null
let _pickingHint = null
const _pickingDisabled = new Map()
let _popup        = null
let _title        = null
let _twistCtrl    = null
let _bendCtrl     = null
let _twistValue   = null
let _twistLabel   = null
let _twistUnit    = null
let _twistRH      = null
let _twistLH      = null
let _twistTotal   = null
let _twistPerNm   = null
let _bendDir      = null
let _bendAngle    = null
let _bendRadius   = null
let _polymerCircle = null
let _polymerCircleLabel = null
let _polymerCount = null
let _polymerCountRow = null
let _compassArm   = null
let _compassHdl   = null
let _previewChk   = null
let _cancelBtn    = null
let _applyBtn     = null
let _planeABp     = null  // <input type="number"> for plane A bp
let _planeBBp     = null  // <input type="number"> for plane B bp
let _planeANm     = null  // <span> showing plane A nm
let _planeBNm     = null  // <span> showing plane B nm
let _clusterSection = null  // <div id="def-cluster-section">
let _clusterList    = null  // <div id="def-cluster-list"> — contains checkboxes
let _clusterEmpty   = null  // <div id="def-cluster-empty-msg">
let _clusterAllBtn  = null
let _clusterNoneBtn = null
let _bendHint       = null  // <div id="def-bend-hint"> — κ + closure hint
let _feasibility    = null  // <div id="def-feasibility"> — yield/achievability readout

let _callbacks   = null  // { onPreview, onConfirm, onCancel, onPlaneChanged }
let _toolType    = null  // 'twist' | 'bend'
let _dragging    = false
let _selectedClusterIds = []  // current cluster scope (mirrors checkbox state)
let _validateTimer = null     // debounce handle for the live /validate POST
let _bendDriver = 'angle'     // field most recently edited by the user

/** Radius for a circular bend spanning `spanBp` base pairs at `angleDeg`. */
export function bendRadiusNm(angleDeg, spanBp) {
  const thetaRad = Math.abs(Number(angleDeg)) * Math.PI / 180
  if (!Number.isFinite(thetaRad) || thetaRad < 1e-12) return Infinity
  return Math.max(1, Math.abs(Number(spanBp))) * BDNA_RISE_PER_BP / thetaRad
}

/** Bend angle subtended by `spanBp` base pairs at `radiusNm`. */
export function bendAngleDeg(radiusNm, spanBp) {
  const radius = Number(radiusNm)
  if (!Number.isFinite(radius) || radius <= 0) return 0
  const arcLengthNm = Math.max(1, Math.abs(Number(spanBp))) * BDNA_RISE_PER_BP
  return arcLengthNm / radius * 180 / Math.PI
}

/** True only for a design carrying routed connector staples and a periodic seam. */
export function hasPolymerizationStrands(design) {
  const d = design?.design ?? design
  const hasConnector = (d?.strands ?? []).some(strand =>
    String(strand?.notes ?? '').toLowerCase().includes('polymerization connector'),
  )
  const hasPeriodicSeam = (d?.forced_ligations ?? []).some(ligation =>
    ligation?.is_periodic_seam === true,
  )
  return hasConnector && hasPeriodicSeam
}

/**
 * Effective number of bent base-pair steps seen by the routed periodic seams.
 *
 * Polymer copies join at the seam endpoints, which can be staggered relative
 * to the two bend planes. Using the typed plane span here is wrong whenever a
 * seam begins before plane A or ends before plane B (pulleyv2 is exactly this
 * case). The repeat rotation is driven by the overlap of each seam interval
 * with the bend window, so use the mean overlap across routed seam helices.
 */
export function polymerBendSpanBp(design, planeA, planeB) {
  const d = design?.design ?? design
  const bendLo = Math.min(Number(planeA), Number(planeB))
  const bendHi = Math.max(Number(planeA), Number(planeB))
  if (!Number.isFinite(bendLo) || !Number.isFinite(bendHi) || bendHi <= bendLo) return 0
  const overlaps = (d?.forced_ligations ?? [])
    .filter(ligation => ligation?.is_periodic_seam === true)
    .map(ligation => {
      const a = Number(ligation.three_prime_bp)
      const b = Number(ligation.five_prime_bp)
      if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
      const seamLo = Math.min(a, b)
      const seamHi = Math.max(a, b)
      return Math.max(0, Math.min(seamHi, bendHi) - Math.max(seamLo, bendLo))
    })
    .filter(span => span > 0)
  if (!overlaps.length) return 0
  return overlaps.reduce((sum, span) => sum + span, 0) / overlaps.length
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Wire up all popup DOM elements and event listeners.
 * Call once at startup.
 *
 * @param {{ onPreview, onConfirm, onCancel }} callbacks
 */
export function initBendTwistPopup(callbacks) {
  _floating?.dispose()
  _pickingDisabled.clear()
  _callbacks = callbacks

  _popup      = document.getElementById('deform-panel')
  _title      = document.getElementById('def-panel-title')
  _floating = createToolPopup({ panel: _popup, title: 'Twist', panelDisplay: 'flex', onClose: () => { if (_selectionUI) _selectionUI.onCancel(); else { _hide(); _callbacks?.onCancel() } } })
  _pickingHint = el('p', { className: 'tool-picking-hint', attrs: { 'aria-live': 'polite', hidden: true } })
  const fields = _popup.querySelector('.def-fields') ?? _popup
  fields.prepend(_pickingHint)
  _selectionSection = el('div', { id: 'def-current-selection' })
  fields.prepend(_selectionSection)
  _twistCtrl  = document.getElementById('def-twist-controls')
  _bendCtrl   = document.getElementById('def-bend-controls')
  _twistValue = document.getElementById('def-twist-value')
  _twistLabel = document.getElementById('def-twist-value-label')
  _twistUnit  = document.getElementById('def-twist-unit')
  _twistRH    = document.getElementById('def-twist-rh')
  _twistLH    = document.getElementById('def-twist-lh')
  _twistTotal = document.getElementById('def-twist-total-radio')
  _twistPerNm = document.getElementById('def-twist-pernm-radio')
  _bendDir    = document.getElementById('def-bend-dir')
  _bendAngle  = document.getElementById('def-bend-angle')
  _bendRadius = document.getElementById('def-bend-radius')
  _polymerCircle = document.getElementById('def-polymer-circle')
  _polymerCircleLabel = document.getElementById('def-polymer-circle-label')
  _polymerCount = document.getElementById('def-polymer-count')
  _polymerCountRow = document.getElementById('def-polymer-count-row')
  _compassArm = document.getElementById('def-compass-arm')
  _compassHdl = document.getElementById('def-compass-handle')
  _previewChk = document.getElementById('def-preview-check')
  _cancelBtn  = document.getElementById('def-cancel-btn')
  _applyBtn   = document.getElementById('def-apply-btn')
  _planeABp   = document.getElementById('def-plane-a-bp')
  _planeBBp   = document.getElementById('def-plane-b-bp')
  _planeANm   = document.getElementById('def-plane-a-nm')
  _planeBNm   = document.getElementById('def-plane-b-nm')
  _clusterSection = document.getElementById('def-cluster-section')
  _clusterList    = document.getElementById('def-cluster-list')
  _clusterEmpty   = document.getElementById('def-cluster-empty-msg')
  _clusterAllBtn  = document.getElementById('def-cluster-all-btn')
  _clusterNoneBtn = document.getElementById('def-cluster-none-btn')
  _bendHint       = document.getElementById('def-bend-hint')
  _feasibility    = document.getElementById('def-feasibility')

  if (!_popup) return   // DOM not ready

  _clusterAllBtn?.addEventListener('click', () => {
    const clusters = store.getState().currentDesign?.cluster_transforms ?? []
    _setSelectedClusterIds(clusters.map(c => c.id), /*refreshPreview=*/true)
  })
  _clusterNoneBtn?.addEventListener('click', () => {
    _setSelectedClusterIds([], /*refreshPreview=*/true)
  })

  // Twist mode radio: swap label/unit
  _twistTotal.addEventListener('change', () => {
    _twistLabel.textContent = 'Degrees:'
    _twistUnit.textContent  = '°'
    _firePreview()
  })
  _twistPerNm.addEventListener('change', () => {
    _twistLabel.textContent = 'Degrees/nm:'
    _twistUnit.textContent  = '°/nm'
    _firePreview()
  })

  // Any twist param change
  _twistValue.addEventListener('input', _firePreview)
  _twistRH.addEventListener('change', _firePreview)
  _twistLH.addEventListener('change', _firePreview)

  // Bend params
  _bendDir.addEventListener('input', () => {
    _updateCompassFromInput()
    _firePreview()
  })
  _bendAngle.addEventListener('input', () => {
    _bendDriver = 'angle'
    _syncRadiusFromAngle()
    _updateBendHint()
    _firePreview()
  })
  _bendRadius.addEventListener('input', () => {
    _bendDriver = 'radius'
    _syncAngleFromRadius()
    _updateBendHint()
    _firePreview()
  })
  _polymerCircle.addEventListener('change', () => {
    _setPolymerCircleMode(_polymerCircle.checked)
    if (_polymerCircle.checked) _driveBendFromPolymerCount()
  })
  _polymerCount.addEventListener('input', () => {
    if (_validPolymerCount() != null) _driveBendFromPolymerCount()
  })
  _polymerCount.addEventListener('change', () => {
    const count = _validPolymerCount() ?? 1
    _polymerCount.value = String(count)
    _driveBendFromPolymerCount()
  })

  // Plane position inputs — reposition the plane and re-preview
  _planeABp?.addEventListener('change', () => {
    const bp = Math.round(parseFloat(_planeABp.value) || 0)
    _planeABp.value = bp
    if (_planeANm) _planeANm.textContent = (bp * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
    if (_toolType === 'bend') _syncBendFieldsForSpan()
    _callbacks?.onPlaneChanged?.('A', bp)
    if (_toolType === 'bend') _firePreview()
    else _fireValidate()  // window width changed → re-check achievability
  })
  _planeBBp?.addEventListener('change', () => {
    const bp = Math.round(parseFloat(_planeBBp.value) || 0)
    _planeBBp.value = bp
    if (_planeBNm) _planeBNm.textContent = (bp * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
    if (_toolType === 'bend') _syncBendFieldsForSpan()
    _callbacks?.onPlaneChanged?.('B', bp)
    if (_toolType === 'bend') _firePreview()
    else _fireValidate()  // window width changed → re-check achievability
  })

  // Preview checkbox
  _previewChk.addEventListener('change', _firePreview)

  // Compass rose drag
  _initCompassDrag()

  // Buttons
  _cancelBtn.addEventListener('click', () => {
    if (_selectionUI) { _selectionUI.onCancel(); return }
    _hide()
    _callbacks?.onCancel()
  })
  _applyBtn.addEventListener('click', async () => {
    const params = _readParams()
    _applyBtn.disabled = true
    try {
      await _callbacks?.onConfirm(params)
      _hide()
    } catch (error) {
      showToast(error.message ?? 'Could not apply deformation', { severity: 'error' })
    } finally { _applyBtn.disabled = false }
  })
}

/**
 * Open the popup for the given tool type.
 * @param {'twist'|'bend'} toolType
 * @param {number} bpA     - current bp index of plane A
 * @param {number} bpB     - current bp index of plane B
 * @param {object} [params] - optional existing op params to pre-populate instead of defaults
 * @param {string[] | null} [initialClusterIds] - cluster scope to preselect.
 *        When null, uses the editor's default (active cluster, single cluster, or none).
 */
export function openPopup(toolType, bpA = 0, bpB = 0, params = null, initialClusterIds = null,
                          skipInitialPreview = false) {
  if (!_popup) return
  _restorePickingControls()
  _toolType = toolType

  _floating?.setTitle(toolType === 'twist' ? 'Twist' : 'Bend')
  _title.textContent = toolType === 'twist' ? 'Twist' : 'Bend'
  _twistCtrl.style.display = toolType === 'twist' ? '' : 'none'
  _bendCtrl.style.display  = toolType === 'bend'  ? '' : 'none'

  if (toolType === 'bend') _resetPolymerCircleOption()

  // Set plane position inputs
  setPlanePositions(bpA, bpB)

  // Build the cluster picker. Initial selection: explicit list (edit mode), else
  // the editor's default scope (active cluster / single cluster / none).
  const initIds = initialClusterIds ?? getDeformDefaultClusterIds()
  if (getDeformSessionTargets() !== null) {
    _selectedClusterIds = []
    if (_clusterSection) _clusterSection.style.display = 'none'
    if (!_selectionUI && _selectionSection) {
      _selectionSection.hidden = false
      _selectionSection.replaceChildren(el('div', { className: 'mr-section-label', text: 'Current selection' }))
      const labels = moveRotateSelectionLabels(targetState(store.getState().currentDesign, getDeformSessionTargets()))
      for (const label of labels) _selectionSection.append(el('div', { className: 'mr-selection-item', text: label }))
    }
  } else {
    if (!_selectionUI && _selectionSection) _selectionSection.hidden = true
    _rebuildClusterList(initIds)
  }

  if (params) {
    // Pre-populate from existing op params
    if (toolType === 'twist' && params.kind === 'twist') {
      if (params.total_degrees != null) {
        _twistTotal.checked     = true
        _twistValue.value       = Math.abs(params.total_degrees)
        _twistRH.checked        = params.total_degrees >= 0
        _twistLH.checked        = params.total_degrees < 0
        _twistLabel.textContent = 'Degrees:'
        _twistUnit.textContent  = '°'
      } else if (params.degrees_per_nm != null) {
        _twistPerNm.checked     = true
        _twistValue.value       = Math.abs(params.degrees_per_nm)
        _twistRH.checked        = params.degrees_per_nm >= 0
        _twistLH.checked        = params.degrees_per_nm < 0
        _twistLabel.textContent = 'Degrees/nm:'
        _twistUnit.textContent  = '°/nm'
      }
    } else if (toolType === 'bend' && params.kind === 'bend') {
      // Display θ = κ × (plane_b − plane_a) — the angle between the typed planes.
      const span  = _typedBendSpanBp()
      const kappa = params.curvature_deg_per_bp ?? 0
      _bendAngle.value = (kappa * span).toFixed(2)
      _bendDir.value   = params.direction_deg ?? 0
      _bendDriver = 'angle'
      _syncRadiusFromAngle()
      _updateCompassFromInput()
      _updateBendHint()
      const savedCircleCount = Number(params.polymer_circle_count)
      if (!_polymerCircle.disabled && Number.isInteger(savedCircleCount) && savedCircleCount >= 1) {
        _polymerCount.value = String(savedCircleCount)
        _polymerCircle.checked = true
        _setPolymerCircleMode(true)
        if (savedCircleCount === 1) {
          // Reapplying a saved one-copy circle repairs the legacy endpoint
          // overlap through the normal preview/Apply/Undo transaction.
          _updateBendFromPolymerCount()
          _updateBendHint()
          skipInitialPreview = false
        }
      }
    }
  } else {
    // Reset to sensible defaults
    if (toolType === 'twist') {
      _twistTotal.checked = true
      _twistValue.value   = '90'
      _twistRH.checked    = true
      _twistLabel.textContent = 'Degrees:'
      _twistUnit.textContent  = '°'
    } else {
      _bendDir.value   = '0'
      _bendAngle.value = '0'
      _bendRadius.value = ''
      _bendDriver = 'angle'
      _updateCompassFromInput()
      _updateBendHint()
    }
  }

  _previewChk.checked = true
  _floating?.show()
  // In edit mode the op is already applied to the design, so an initial preview
  // would just re-compute identical geometry (a wasted round-trip). Preview fires
  // on the first slider change instead.
  if (!skipInitialPreview) _firePreview()
  else _fireValidate()  // still show feasibility immediately in edit mode
}

/**
 * Update the plane position inputs and nm labels without re-opening the popup.
 * Called by main.js when the user finishes dragging a plane in the 3D scene.
 * @param {number} bpA
 * @param {number} bpB
 */
export function setPlanePositions(bpA, bpB) {
  if (_planeABp) _planeABp.value = bpA
  if (_planeBBp) _planeBBp.value = bpB
  if (_planeANm) _planeANm.textContent = (bpA * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
  if (_planeBNm) _planeBNm.textContent = (bpB * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
  // Effective span (auto-extended for stagger) depends on plane positions —
  // refresh the dependent field and hint so all values describe the same arc.
  if (_toolType === 'bend') {
    _syncBendFieldsForSpan()
  }
  _fireValidate()  // plane drag in the 3D scene changes the window → re-check
}

function _restorePickingControls() {
  for (const [control, disabled] of _pickingDisabled) control.disabled = disabled
  _pickingDisabled.clear()
  for (const node of [_twistCtrl, _bendCtrl, _clusterSection]) if (node) node.inert = false
  if (_pickingHint) _pickingHint.hidden = true
}

/** Keep the tool window present while its reference planes are being picked. */
export function showPickingPopup(toolType, planeA = null) {
  if (!_popup) return
  _restorePickingControls()
  _toolType = null
  clearTimeout(_validateTimer)
  _floating?.setTitle(toolType === 'twist' ? 'Twist' : 'Bend')
  _title.textContent = toolType === 'twist' ? 'Twist' : 'Bend'
  _twistCtrl.style.display = toolType === 'twist' ? '' : 'none'
  _bendCtrl.style.display = toolType === 'bend' ? '' : 'none'
  _planeABp.value = planeA ?? ''
  _planeBBp.value = ''
  _planeANm.textContent = planeA == null ? 'Not selected' : `${(planeA * BDNA_RISE_PER_BP).toFixed(2)} nm`
  _planeBNm.textContent = 'Not selected'
  _pickingHint.textContent = planeA == null ? 'Select plane A (fixed) in the 3D view, then plane B.' : 'Plane A selected. Select plane B in the 3D view to enable the parameters.'
  _pickingHint.hidden = false
  for (const control of _popup.querySelectorAll('input, select, button')) {
    if (control === _cancelBtn || _selectionSection?.contains(control)) continue
    _pickingDisabled.set(control, control.disabled)
    control.disabled = true
  }
  for (const node of [_twistCtrl, _bendCtrl, _clusterSection]) if (node) node.inert = true
  _floating?.show()
}

/** Selection stays in the same floating panel throughout the tool session. */
export function showSelectionPopup(type) {
  showPickingPopup(type)
  if (_pickingHint) _pickingHint.textContent = 'Select clusters, strands, or domains. Planes will be placed at the far ends of the selection.'
  if (_clusterSection) _clusterSection.style.display = 'none'
}

export function setDeformationSelectionUI(config) {
  _selectionUI = config
  if (!_selectionSection) return
  _selectionSection.replaceChildren()
  _selectionSection.hidden = !config
  if (!config) return
  _selectionSection.append(el('div', { className: 'mr-section-label', text: 'Current selection' }))
  const list = el('div', { className: 'mr-selection-box', attrs: { 'aria-live': 'polite' } })
  for (const label of config.labels.length ? config.labels : ['Nothing selected']) {
    list.append(el('div', { className: 'mr-selection-item', text: label }))
  }
  _selectionSection.append(list)
  if (config.error) _selectionSection.append(el('p', { className: 'dim', text: config.error }))
  const button = (id, text, action, disabled = false) => {
    const node = el('button', { className: 'btn btn--sm', text, attrs: { id, type: 'button' }, on: { click: action } })
    node.disabled = disabled
    _selectionSection.append(node)
  }
  button('def-clear-selection', 'Clear selection', config.onClear, !config.labels.length)
  if (config.phase !== 'selection') button('def-change-selection', 'Change selection', config.onChange)
}

export function closePopup() {
  _hide()
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _hide() {
  _restorePickingControls()
  _floating?.hide()
  _toolType = null
  clearTimeout(_validateTimer)
  if (_feasibility) { _feasibility.style.display = 'none'; _feasibility.textContent = '' }
}

function _readParams() {
  if (_toolType === 'twist') {
    const sign = parseFloat(_twistRH.checked ? '1' : '-1')
    const val  = Math.abs(parseFloat(_twistValue.value) || 0) * sign
    if (_twistTotal.checked) {
      return { kind: 'twist', total_degrees: val }
    } else {
      return { kind: 'twist', degrees_per_nm: val }
    }
  } else {
    // User types the visual bend angle θ between plane A and plane B.
    // Canonical storage is per-bp curvature κ = θ / (plane_b − plane_a).
    // The rendered angle between the planes equals exactly θ; helices that
    // don't fully span [plane_a, plane_b] pick up proportionally less rotation
    // (the user moves the planes to bracket all stagger when uniformity matters).
    const span = _typedBendSpanBp()
    const theta = Math.max(0, parseFloat(_bendAngle.value) || 0)
    const params = {
      kind:                  'bend',
      curvature_deg_per_bp:  span > 0 ? theta / span : 0,
      direction_deg: ((parseFloat(_bendDir.value) || 0) % 360 + 360) % 360,
    }
    const circleCount = _polymerCircle?.checked ? _validPolymerCount() : null
    if (circleCount != null) params.polymer_circle_count = circleCount
    return params
  }
}

/** Typed bend window width in bp (planeB − planeA, clamped ≥ 1). */
function _typedBendSpanBp() {
  const planeA = parseFloat(_planeABp?.value) || 0
  const planeB = parseFloat(_planeBBp?.value) || 0
  return Math.max(1, Math.abs(planeB - planeA))
}

function _formatRadius(radiusNm) {
  if (!Number.isFinite(radiusNm)) return ''
  // Enough precision to make angle → radius → angle stable without filling the
  // compact popup with insignificant digits.
  return Number(radiusNm.toPrecision(6)).toString()
}

function _syncRadiusFromAngle() {
  if (!_bendRadius) return
  _bendRadius.value = _formatRadius(
    bendRadiusNm(parseFloat(_bendAngle?.value) || 0, _typedBendSpanBp()),
  )
}

function _syncAngleFromRadius() {
  if (!_bendAngle) return
  const radius = parseFloat(_bendRadius?.value)
  const angle = bendAngleDeg(radius, _typedBendSpanBp())
  _bendAngle.value = Number(angle.toPrecision(6)).toString()
}

function _syncBendFieldsForSpan() {
  if (_bendDriver === 'circle') _updateBendFromPolymerCount()
  else if (_bendDriver === 'radius') _syncAngleFromRadius()
  else _syncRadiusFromAngle()
  _updateBendHint()
}

function _resetPolymerCircleOption() {
  if (!_polymerCircle) return
  const eligible = hasPolymerizationStrands(store.getState().currentDesign)
  _polymerCircle.checked = false
  _polymerCircle.disabled = !eligible
  _polymerCircleLabel?.classList.toggle('is-disabled', !eligible)
  if (_polymerCircleLabel) {
    _polymerCircleLabel.style.opacity = eligible ? '' : '0.5'
    _polymerCircleLabel.title = eligible
      ? 'Set the bend for a closed circle containing this many copies of the current design.'
      : 'Run Route for Polymerization first to create polymerization connector strands.'
  }
  _setPolymerCircleMode(false)
}

function _setPolymerCircleMode(enabled) {
  if (_polymerCountRow) _polymerCountRow.style.display = enabled ? '' : 'none'
  if (_polymerCount) _polymerCount.disabled = !enabled
  if (_bendAngle) _bendAngle.readOnly = enabled
  if (_bendRadius) _bendRadius.readOnly = enabled
  if (enabled) _bendDriver = 'circle'
  else if (_bendDriver === 'circle') _bendDriver = 'angle'
}

function _validPolymerCount() {
  const raw = Number(_polymerCount?.value)
  if (!Number.isFinite(raw) || raw < 1) return null
  return Math.round(raw)
}

function _driveBendFromPolymerCount() {
  const count = _validPolymerCount()
  if (count == null || !_polymerCircle?.checked) return
  _polymerCount.value = String(count)
  _bendDriver = 'circle'
  _updateBendFromPolymerCount()
  _updateBendHint()
  _firePreview()
}

function _updateBendFromPolymerCount() {
  const count = _validPolymerCount()
  if (count == null || !_polymerCircle?.checked) return
  const planeA = parseFloat(_planeABp?.value) || 0
  const planeB = parseFloat(_planeBBp?.value) || 0
  const seamBendSpan = polymerBendSpanBp(store.getState().currentDesign, planeA, planeB)
  const typedSpan = _typedBendSpanBp()
  // Fall back to the typed span only for malformed legacy routing. Normal
  // routed designs always have at least one resolvable periodic seam.
  const bentSpan = seamBendSpan > 0 ? seamBendSpan : typedSpan
  // A single copy joins its own terminal bases: reserve one more bp step for
  // that bond, rather than rotating the last occupied site onto the first.
  // Multiple copies use the periodic repeat transform, which already appends
  // the next-base step when placing each copy.
  const effectiveSpan = bentSpan + (count === 1 ? 1 : 0)
  const curvature = (360 / count) / effectiveSpan
  _bendAngle.value = Number((curvature * typedSpan).toPrecision(8)).toString()
  _syncRadiusFromAngle()
}

/**
 * Update the "κ = X°/bp · spans Y bp" hint below the angle input.
 * Polymer-closure feedback lives in the polymerize panel.
 */
function _updateBendHint() {
  if (!_bendHint) return
  const theta = parseFloat(_bendAngle.value) || 0
  const span = _typedBendSpanBp()
  const kappa = span > 0 ? theta / span : 0
  _bendHint.textContent = `κ = ${kappa.toFixed(4)}°/bp · spans ${span} bp between planes`
}

function _firePreview() {
  // Feasibility check fires regardless of the preview checkbox — the user always
  // wants to know if a bend/twist is unachievable, even with live preview off.
  _fireValidate()
  if (!_previewChk?.checked) return
  Promise.resolve(_callbacks?.onPreview(_readParams())).catch(error =>
    showToast(error.message ?? 'Could not preview deformation', { severity: 'error' }))
}

// ── Feasibility (physically-achievable bend/twist) feedback ──────────────────────

/** Debounced live feasibility check against the backend (no mutation). */
function _fireValidate() {
  if (!_toolType) return
  clearTimeout(_validateTimer)
  _validateTimer = setTimeout(_doValidate, 120)
}

async function _doValidate() {
  if (!_toolType || !_feasibility) return
  const type   = _toolType
  const planeA = Math.round(parseFloat(_planeABp?.value) || 0)
  const planeB = Math.round(parseFloat(_planeBBp?.value) || 0)
  const params = _readParams()
  try {
    const res = await validateDeformation({
      type, planeA, planeB, params, clusterIds: _selectedClusterIds, targets: getDeformSessionTargets() ?? undefined,
    })
    // Ignore stale responses if the tool closed or switched mid-flight.
    if (_toolType === type) _renderFeasibility(res)
  } catch { /* non-fatal: feedback only */ }
}

function _renderFeasibility(r) {
  if (!_feasibility) return
  _feasibility.classList.remove('def-feasibility--warn', 'def-feasibility--block')
  if (!r || r.status === 'ok' || !r.message) {
    _feasibility.style.display = 'none'
    _feasibility.textContent = ''
    return
  }
  _feasibility.style.display = ''
  _feasibility.textContent = r.message
  if (r.status === 'block') {
    _feasibility.classList.add('def-feasibility--block')
    _feasibility.style.color = 'var(--color-danger, #f85149)'
  } else {
    _feasibility.classList.add('def-feasibility--warn')
    _feasibility.style.color = 'var(--color-warning, #d29922)'
  }
}

// ── Cluster scope picker ──────────────────────────────────────────────────────

/**
 * Render the checkbox list for the design's clusters and seed the selection.
 * Hides the section entirely when the design has 0–1 clusters (no choice to make).
 */
function _rebuildClusterList(selectedIds) {
  if (!_clusterList || !_clusterSection) return
  const clusters = store.getState().currentDesign?.cluster_transforms ?? []
  _clusterList.innerHTML = ''

  if (clusters.length <= 1) {
    // 0 clusters: no scoping possible; 1 cluster: implicit, no UI needed.
    _clusterSection.style.display = 'none'
    _selectedClusterIds = clusters.length === 1 ? [clusters[0].id] : []
    setDeformSessionClusterIds(_selectedClusterIds)
    return
  }

  _clusterSection.style.display = ''
  if (_clusterEmpty) _clusterEmpty.style.display = 'none'

  const initSet = new Set(selectedIds ?? [])
  for (const c of clusters) {
    const row = document.createElement('label')
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer'
    const cb = document.createElement('input')
    cb.type = 'checkbox'
    cb.value = c.id
    cb.checked = initSet.has(c.id)
    cb.addEventListener('change', _onClusterCheckboxChange)
    const txt = document.createElement('span')
    txt.textContent = `${c.name || 'Cluster'} (${c.helix_ids.length}h)`
    txt.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
    row.appendChild(cb); row.appendChild(txt)
    _clusterList.appendChild(row)
  }

  _selectedClusterIds = clusters.filter(c => initSet.has(c.id)).map(c => c.id)
  setDeformSessionClusterIds(_selectedClusterIds)
}

function _onClusterCheckboxChange() {
  if (!_clusterList) return
  const ids = []
  for (const cb of _clusterList.querySelectorAll('input[type=checkbox]')) {
    if (cb.checked) ids.push(cb.value)
  }
  _setSelectedClusterIds(ids, /*refreshPreview=*/true)
}

async function _setSelectedClusterIds(ids, refreshPreview) {
  _selectedClusterIds = ids.slice()
  if (_clusterList) {
    const set = new Set(ids)
    for (const cb of _clusterList.querySelectorAll('input[type=checkbox]')) {
      cb.checked = set.has(cb.value)
    }
  }
  // Tell the editor; it rebuilds the live preview op so geometry updates.
  await setDeformSessionClusterIds(_selectedClusterIds)
  if (refreshPreview) _firePreview()
}

// ── Compass rose ──────────────────────────────────────────────────────────────

const COMPASS_R = 27  // arm length in SVG user units

function _angleToSvg(deg) {
  // math convention: 0°=+X, CCW positive; SVG: y-axis flipped
  const rad = (deg * Math.PI) / 180
  return {
    x: COMPASS_R * Math.cos(rad),
    y: -COMPASS_R * Math.sin(rad),
  }
}

function _updateCompassFromInput() {
  if (!_compassArm) return
  const deg = parseFloat(_bendDir.value) || 0
  const { x, y } = _angleToSvg(deg)
  _compassArm.setAttribute('x2', x.toFixed(2))
  _compassArm.setAttribute('y2', y.toFixed(2))
  _compassHdl.setAttribute('cx', x.toFixed(2))
  _compassHdl.setAttribute('cy', y.toFixed(2))
}

function _initCompassDrag() {
  const svg = document.getElementById('def-compass')
  if (!svg) return

  function _onPointerMove(e) {
    if (!_dragging) return
    const rect   = svg.getBoundingClientRect()
    const cx     = rect.left + rect.width  / 2
    const cy     = rect.top  + rect.height / 2
    const dx     = e.clientX - cx
    const dy     = e.clientY - cy
    let deg = Math.round(Math.atan2(-dy, dx) * 180 / Math.PI)
    deg = ((deg % 360) + 360) % 360
    _bendDir.value = deg
    _updateCompassFromInput()
    _firePreview()
  }

  function _onPointerUp() {
    if (_dragging) {
      _dragging = false
      document.removeEventListener('pointermove', _onPointerMove)
      document.removeEventListener('pointerup', _onPointerUp)
    }
  }

  // Dragging the handle OR anywhere on the compass circle
  svg.addEventListener('pointerdown', (e) => {
    e.preventDefault()
    _dragging = true
    document.addEventListener('pointermove', _onPointerMove)
    document.addEventListener('pointerup', _onPointerUp)
    _onPointerMove(e)  // snap immediately on click
  })
}
