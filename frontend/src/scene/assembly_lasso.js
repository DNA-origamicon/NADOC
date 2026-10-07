/**
 * Assembly drag-rectangle ("lasso") multi-select extracted from main.js.
 * Left-drag: left-to-right contains whole bounds, right-to-left crosses bounds. `instancesInRect` is the PURE
 * hit-test core; the factory owns the in-flight drag state + DOM overlay and is
 * wired with a lazy instance-centers getter + an onSelect callback (main.js does
 * the store write). Unit-tested in assembly_lasso.test.js.
 */
import * as THREE from 'three'
import { projectBox, boundsInRect } from './rectangle_selection.js'

/**
 * Ids of instances contained in the canvas-relative rect [cx1,cy1]–[cx2,cy2].
 * Window selection requires all 8 AABB corners inside the rect and camera range.
 * Crossing selection accepts any overlap of the projected bounds.
 * @param {Array} centers  [{ id, center:{x,y,z}, size:{x,y,z} }]
 * @param {THREE.Camera} camera
 * @param {{width:number,height:number}} canvasSize
 */
export function instancesInRect(centers, camera, { width, height }, cx1, cy1, cx2, cy2, crossing = false) {
  const hits = []
  for (const c of centers ?? []) {
    if (!c.size) continue
    const center = new THREE.Vector3(c.center.x, c.center.y, c.center.z)
    const size = new THREE.Vector3(c.size.x, c.size.y, c.size.z)
    const box = new THREE.Box3().setFromCenterAndSize(center, size)
    const bounds = projectBox(box, new THREE.Matrix4(), camera, { width, height })
    if (boundsInRect(bounds, { x1: cx1, y1: cy1, x2: cx2, y2: cy2 }, crossing)) hits.push(c.id)
  }
  return hits
}

/**
 * Toggle `hitId` in/out of the assembly multi-select set (Ctrl+click semantics).
 * The current logical selection is the UNION of the existing multi-set and any
 * single active instance — so a Ctrl+click after a plain single-click ADDS the
 * new part rather than discarding the prior pick (ISSUE-3 decision 1). A
 * Ctrl+click on a part already in the set removes just that part (decision 2).
 * Returns the new id list; the caller is expected to clear activeInstanceId,
 * leaving this set as the sole selection carrier. Pure — unit-tested.
 * @param {string[]|null|undefined} multiIds  current multiSelectedInstanceIds
 * @param {string|null|undefined} activeId    current single active instance
 * @param {string} hitId                       the Ctrl-clicked instance id
 * @returns {string[]}
 */
export function toggleInstanceSelection(multiIds, activeId, hitId) {
  const sel = new Set(multiIds ?? [])
  if (activeId) sel.add(activeId)
  if (sel.has(hitId)) sel.delete(hitId)
  else sel.add(hitId)
  return [...sel]
}

/**
 * @param {object} deps
 * @param {HTMLElement} deps.canvas
 * @param {THREE.Camera} deps.camera
 * @param {{enabled:boolean}} deps.controls   OrbitControls (disabled during drag)
 * @param {() => Array} deps.getInstanceCenters
 * @param {(hits:string[], additive:boolean)=>void} deps.onSelect
 * @returns {{ start:(e)=>boolean, cancel:()=>void }}
 */
export function initAssemblyLasso({ canvas, camera, controls, getInstanceCenters, onSelect, onClick, onPlainClick }) {
  let state = null   // { startX, startY, overlayEl, additive } | null

  function createOverlay() {
    const div = document.createElement('div')
    div.style.cssText = (
      'position:fixed;border:1.5px solid #8b5cf6;background:rgba(139,92,246,0.08);' +
      'pointer-events:none;z-index:1000;box-sizing:border-box'
    )
    div.style.display = 'none'
    document.body.appendChild(div)
    return div
  }

  function onMove(e) {
    if (!state?.overlayEl || state.modified) return
    const el = state.overlayEl
    el.style.display = ''
    el.style.borderStyle = e.clientX < state.startX ? 'dashed' : 'solid'
    el.style.left   = Math.min(state.startX, e.clientX) + 'px'
    el.style.top    = Math.min(state.startY, e.clientY) + 'px'
    el.style.width  = Math.abs(e.clientX - state.startX) + 'px'
    el.style.height = Math.abs(e.clientY - state.startY) + 'px'
  }

  // Esc aborts an in-flight drag (listener added on start, removed on end).
  function onKey(e) { if (e.key === 'Escape') cancel() }

  function detach() {
    canvas.removeEventListener('pointermove', onMove)
    canvas.removeEventListener('pointerup',   onUp)
    canvas.removeEventListener('pointercancel', cancel)
    window.removeEventListener('keydown', onKey)
  }

  function finalize(endE) {
    const s = state
    state = null
    detach()
    controls.enabled = true
    if (!s) return
    s.overlayEl?.remove()
    const rect = canvas.getBoundingClientRect()
    const cx1 = Math.min(s.startX, endE.clientX) - rect.left
    const cx2 = Math.max(s.startX, endE.clientX) - rect.left
    const cy1 = Math.min(s.startY, endE.clientY) - rect.top
    const cy2 = Math.max(s.startY, endE.clientY) - rect.top
    // Tiny rect = a click, not a drag → a Ctrl-click; let the caller toggle the pick.
    if ((cx2 - cx1) < 4 && (cy2 - cy1) < 4) {
      if (s.modified) onClick?.(endE)
      else onPlainClick?.(endE)
      return
    }
    if (s.modified) return
    const hits = instancesInRect(getInstanceCenters(), camera, { width: rect.width, height: rect.height }, cx1, cy1, cx2, cy2, endE.clientX < s.startX)
    onSelect(hits, s.additive)
  }

  function onUp(e) { finalize(e) }

  /** Track a left gesture; Ctrl/Meta clicks toggle but modified drags do nothing. */
  function start(e) {
    if (e.button != null && e.button !== 0) return false
    if (e.altKey) return false
    state = { startX: e.clientX, startY: e.clientY, overlayEl: createOverlay(), additive: e.shiftKey, modified: e.ctrlKey || e.metaKey }
    controls.enabled = false
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup',   onUp)
    canvas.addEventListener('pointercancel', cancel)
    if (e.pointerId != null) canvas.setPointerCapture?.(e.pointerId)
    window.addEventListener('keydown', onKey)
    return true
  }

  /** Abort an in-flight drag (Esc, or assembly-mode exit). */
  function cancel() {
    if (!state) return
    state.overlayEl?.remove()
    detach()
    state = null
    controls.enabled = true
  }

  return { start, cancel }
}
