/**
 * Zoom scope — a circular magnifier lens that tracks the cursor when Space is held.
 *
 * Uses a secondary Three.js renderer + camera to produce a sharp re-render of the
 * cursor region rather than upscaling pixels from the framebuffer.
 *
 * camera.setViewOffset(W, H, x, y, srcW, srcH) shifts the projection frustum so
 * that only the srcW×srcH CSS-pixel sub-region centred on the cursor is rendered,
 * then the secondary renderer stretches it to fill the LENS_SIZE×LENS_SIZE canvas.
 *
 * Hover pre-selection: projects each backbone entry's world position to NDC and
 * finds the closest to the cursor.  The full strand is highlighted via a dedicated
 * glow layer (additive-blended InstancedMesh, same mechanism as selection glow) so
 * it is completely independent of instanceColor/instanceMatrix buffer update timing.
 * getHoverEntry() exposes the nearest entry so selection_manager can use it as a
 * click fallback when the raycast misses (common when zoomed out).
 */

import * as THREE from 'three'
import { createGlowLayer } from './glow_layer.js'
import { store } from '../state/store.js'

const LENS_SIZE = 240           // CSS px diameter of the lens
const ZOOM      = 3.5           // magnification factor
const R         = LENS_SIZE / 2 // lens radius in px

// NDC proximity threshold for hover detection (~2.5% of half-screen width)
const NDC_THRESH_SQ = 0.025 * 0.025

// Hover glow colour — light sky blue, distinct from the selection glow (green)
const HOVER_GLOW_COLOR = 0x88ccff

export function initZoomScope(canvas, scene, mainCamera, designRenderer) {
  // ── Secondary Three.js renderer ───────────────────────────────────────────
  const lensCanvas = document.createElement('canvas')
  lensCanvas.style.cssText = `position:absolute;top:0;left:0;width:${LENS_SIZE}px;height:${LENS_SIZE}px;`

  const secondRenderer = new THREE.WebGLRenderer({ canvas: lensCanvas, antialias: true })
  secondRenderer.setSize(LENS_SIZE, LENS_SIZE)
  secondRenderer.setPixelRatio(window.devicePixelRatio || 1)
  secondRenderer.outputColorSpace = THREE.SRGBColorSpace

  // Secondary camera — position/quaternion synced to main each frame
  const zoomCamera = new THREE.PerspectiveCamera(
    mainCamera.fov, 1.0, mainCamera.near, mainCamera.far,
  )

  // ── Hover glow layer ──────────────────────────────────────────────────────
  // A separate additive-blend InstancedMesh, independent of the main bead
  // instanceColor buffers.  Works exactly like the selection glow in
  // selection_manager.js but with a different colour.
  const _hoverGlow = createGlowLayer(scene, HOVER_GLOW_COLOR)

  // ── Lens container ────────────────────────────────────────────────────────
  const lens = document.createElement('div')
  lens.style.cssText = [
    'position:fixed',
    `width:${LENS_SIZE}px`,
    `height:${LENS_SIZE}px`,
    'border-radius:50%',
    'border:1.5px solid rgba(255,255,255,0.25)',
    'box-shadow:0 0 0 1px rgba(0,0,0,0.6),0 6px 28px rgba(0,0,0,0.55)',
    'overflow:hidden',
    'pointer-events:none',
    'display:none',
    'z-index:9999',
    'transform:translate(-50%,-50%)',
    'will-change:transform',
  ].join(';')
  lens.appendChild(lensCanvas)

  // ── Crosshair SVG overlay ─────────────────────────────────────────────────
  const CL  = 22
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('viewBox', `0 0 ${LENS_SIZE} ${LENS_SIZE}`)
  svg.style.cssText = `position:absolute;top:0;left:0;width:${LENS_SIZE}px;height:${LENS_SIZE}px;pointer-events:none;`
  svg.innerHTML = `
    <line x1="${R}" y1="${R - CL}" x2="${R}" y2="${R + CL}" stroke="rgba(255,255,255,0.75)" stroke-width="1"/>
    <line x1="${R - CL}" y1="${R}" x2="${R + CL}" y2="${R}" stroke="rgba(255,255,255,0.75)" stroke-width="1"/>
    <circle cx="${R}" cy="${R}" r="3.5" stroke="rgba(255,255,255,0.6)" stroke-width="1" fill="none"/>
  `
  lens.appendChild(svg)

  document.body.appendChild(lens)

  // ── Hover state ───────────────────────────────────────────────────────────
  let _hoverEntry = null   // entry currently shown in the glow layer

  // ── NDC probe ─────────────────────────────────────────────────────────────
  const _probePos = new THREE.Vector3()

  function _probe() {
    if (!designRenderer) return null
    const rect = canvas.getBoundingClientRect()
    const relX = _cx - rect.left
    const relY = _cy - rect.top
    if (relX < 0 || relX > rect.width || relY < 0 || relY > rect.height) return null

    const ndcX = (relX / rect.width)  *  2 - 1
    const ndcY = -(relY / rect.height) * 2 + 1

    const { selectableTypes } = store.getState()
    const entries = designRenderer.getBackboneEntries().filter(e => {
      const isScaffold = e.nuc?.strand_type === 'scaffold'
      const isEnd      = e.nuc?.is_five_prime || e.nuc?.is_three_prime
      if (!(isScaffold ? selectableTypes.scaffold : selectableTypes.staples)) return false
      if (selectableTypes.ends && isEnd) return true
      return selectableTypes.strands !== false
    })

    let bestEntry  = null
    let bestDistSq = NDC_THRESH_SQ

    for (const entry of entries) {
      _probePos.copy(entry.pos).project(mainCamera)
      if (_probePos.z > 1.0) continue   // behind camera
      const dx = _probePos.x - ndcX
      const dy = _probePos.y - ndcY
      const dSq = dx * dx + dy * dy
      if (dSq < bestDistSq) { bestDistSq = dSq; bestEntry = entry }
    }

    return bestEntry
  }

  // ── Hover update ──────────────────────────────────────────────────────────
  function _updateHover() {
    const newEntry = _probe()
    if (newEntry === _hoverEntry) return   // unchanged — nothing to do
    _hoverEntry = newEntry
    if (newEntry) {
      const strandId = newEntry.nuc.strand_id
      const strandEntries = designRenderer.getBackboneEntries()
        .filter(e => e.nuc.strand_id === strandId)
      _hoverGlow.setEntries(strandEntries)
    } else {
      _hoverGlow.clear()
    }
  }

  // ── Lens render loop ──────────────────────────────────────────────────────
  let _active = false
  let _rafId  = null
  let _cx = 0, _cy = 0

  function _drawFrame() {
    if (!_active) return
    _rafId = requestAnimationFrame(_drawFrame)

    _updateHover()

    const rect = canvas.getBoundingClientRect()
    const W    = rect.width
    const H    = rect.height
    const cx   = _cx - rect.left
    const cy   = _cy - rect.top

    const srcSize = LENS_SIZE / ZOOM
    zoomCamera.position.copy(mainCamera.position)
    zoomCamera.quaternion.copy(mainCamera.quaternion)
    zoomCamera.fov  = mainCamera.fov
    zoomCamera.near = mainCamera.near
    zoomCamera.far  = mainCamera.far
    zoomCamera.setViewOffset(W, H, cx - srcSize / 2, cy - srcSize / 2, srcSize, srcSize)

    secondRenderer.render(scene, zoomCamera)
  }

  // ── Activate / deactivate ─────────────────────────────────────────────────
  function _activate() {
    if (_active) return
    _active = true
    canvas.style.cursor = 'none'
    lens.style.display  = 'block'
    _positionLens()
    _rafId = requestAnimationFrame(_drawFrame)
  }

  function _deactivate() {
    if (!_active) return
    _active = false
    _hoverGlow.clear()
    _hoverEntry = null
    canvas.style.cursor = ''
    lens.style.display  = 'none'
    if (_rafId) { cancelAnimationFrame(_rafId); _rafId = null }
  }

  function _positionLens() {
    lens.style.left = _cx + 'px'
    lens.style.top  = _cy + 'px'
  }

  // ── Input handlers ────────────────────────────────────────────────────────
  let _spaceHeld = false

  document.addEventListener('keydown', e => {
    if (e.repeat || e.key !== ' ') return
    const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'
    if (inInput) return
    e.preventDefault()
    _spaceHeld = true
    _activate()
  })

  document.addEventListener('keyup', e => {
    if (e.key !== ' ') return
    _spaceHeld = false
    _deactivate()
  })

  window.addEventListener('blur', () => { _spaceHeld = false; _deactivate() })

  document.addEventListener('mousemove', e => {
    _cx = e.clientX
    _cy = e.clientY
    if (_active) _positionLens()
  })

  return { isActive: () => _active, getHoverEntry: () => _hoverEntry }
}
