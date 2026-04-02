/**
 * Bend & Twist parameter popup.
 *
 * Opened by main.js when the deformation editor reaches the BOTH state.
 * Communicates back to the editor via the callback object passed to init().
 *
 * Compass rose: draggable SVG arm; 0° = +X in bundle cross-section,
 * angles increase counter-clockwise (standard math convention).
 */

import { BDNA_RISE_PER_BP } from '../constants.js'

// ── DOM refs (grabbed once on init) ─────────────────────────────────────────

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
let _compassArm   = null
let _compassHdl   = null
let _previewChk   = null
let _cancelBtn    = null
let _applyBtn     = null
let _planeABp     = null  // <input type="number"> for plane A bp
let _planeBBp     = null  // <input type="number"> for plane B bp
let _planeANm     = null  // <span> showing plane A nm
let _planeBNm     = null  // <span> showing plane B nm

let _callbacks   = null  // { onPreview, onConfirm, onCancel, onPlaneChanged }
let _toolType    = null  // 'twist' | 'bend'
let _dragging    = false

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Wire up all popup DOM elements and event listeners.
 * Call once at startup.
 *
 * @param {{ onPreview, onConfirm, onCancel }} callbacks
 */
export function initBendTwistPopup(callbacks) {
  _callbacks = callbacks

  _popup      = document.getElementById('deform-panel')
  _title      = document.getElementById('def-panel-title')
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
  _compassArm = document.getElementById('def-compass-arm')
  _compassHdl = document.getElementById('def-compass-handle')
  _previewChk = document.getElementById('def-preview-check')
  _cancelBtn  = document.getElementById('def-cancel-btn')
  _applyBtn   = document.getElementById('def-apply-btn')
  _planeABp   = document.getElementById('def-plane-a-bp')
  _planeBBp   = document.getElementById('def-plane-b-bp')
  _planeANm   = document.getElementById('def-plane-a-nm')
  _planeBNm   = document.getElementById('def-plane-b-nm')

  if (!_popup) return   // DOM not ready

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
  _bendAngle.addEventListener('input', _firePreview)

  // Plane position inputs — reposition the plane and re-preview
  _planeABp?.addEventListener('change', () => {
    const bp = Math.max(0, Math.round(parseFloat(_planeABp.value) || 0))
    _planeABp.value = bp
    if (_planeANm) _planeANm.textContent = (bp * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
    _callbacks?.onPlaneChanged?.('A', bp)
  })
  _planeBBp?.addEventListener('change', () => {
    const bp = Math.max(0, Math.round(parseFloat(_planeBBp.value) || 0))
    _planeBBp.value = bp
    if (_planeBNm) _planeBNm.textContent = (bp * BDNA_RISE_PER_BP).toFixed(2) + ' nm'
    _callbacks?.onPlaneChanged?.('B', bp)
  })

  // Preview checkbox
  _previewChk.addEventListener('change', _firePreview)

  // Compass rose drag
  _initCompassDrag()

  // Buttons
  _cancelBtn.addEventListener('click', () => {
    _hide()
    _callbacks?.onCancel()
  })
  _applyBtn.addEventListener('click', () => {
    const params = _readParams()  // read BEFORE _hide() clears _toolType
    _hide()
    _callbacks?.onConfirm(params)
  })
}

/**
 * Open the popup for the given tool type.
 * @param {'twist'|'bend'} toolType
 * @param {number} bpA     - current bp index of plane A
 * @param {number} bpB     - current bp index of plane B
 * @param {object} [params] - optional existing op params to pre-populate instead of defaults
 */
export function openPopup(toolType, bpA = 0, bpB = 0, params = null) {
  if (!_popup) return
  _toolType = toolType

  _title.textContent = toolType === 'twist' ? 'Twist' : 'Bend'
  _twistCtrl.style.display = toolType === 'twist' ? '' : 'none'
  _bendCtrl.style.display  = toolType === 'bend'  ? '' : 'none'

  // Set plane position inputs
  setPlanePositions(bpA, bpB)

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
      _bendAngle.value = params.angle_deg ?? 0
      _bendDir.value   = params.direction_deg ?? 0
      _updateCompassFromInput()
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
      _updateCompassFromInput()
    }
  }

  _previewChk.checked = true
  _popup.style.display = 'block'
  _firePreview()
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
}

export function closePopup() {
  _hide()
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _hide() {
  if (_popup) _popup.style.display = 'none'
  _toolType = null
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
    return {
      kind:          'bend',
      angle_deg: ((parseFloat(_bendAngle.value) || 0) % 360 + 360) % 360,
      direction_deg: ((parseFloat(_bendDir.value) || 0) % 360 + 360) % 360,
    }
  }
}

function _firePreview() {
  if (!_previewChk?.checked) return
  _callbacks?.onPreview(_readParams())
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
