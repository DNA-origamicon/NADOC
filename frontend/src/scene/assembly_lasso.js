/**
 * Assembly drag-rectangle ("lasso") multi-select extracted from main.js. Hold
 * Ctrl/Meta and drag; instances whose ENTIRE world-AABB (all 8 corners) projects
 * inside the rect are selected on pointerup. `instancesInRect` is the PURE
 * hit-test core; the factory owns the in-flight drag state + DOM overlay and is
 * wired with a lazy instance-centers getter + an onSelect callback (main.js does
 * the store write). Unit-tested in assembly_lasso.test.js.
 */
import * as THREE from 'three'

/**
 * Ids of instances fully contained in the canvas-relative rect [cx1,cy1]–[cx2,cy2].
 * Strict: every one of the 8 AABB corners must project inside the rect AND within
 * the camera z-range (a partially-visible / off-screen part is skipped).
 * @param {Array} centers  [{ id, center:{x,y,z}, size:{x,y,z} }]
 * @param {THREE.Camera} camera
 * @param {{width:number,height:number}} canvasSize
 */
export function instancesInRect(centers, camera, { width, height }, cx1, cy1, cx2, cy2) {
  const hits = []
  const v = new THREE.Vector3()
  for (const c of centers ?? []) {
    if (!c.size) continue
    const hx = c.size.x * 0.5, hy = c.size.y * 0.5, hz = c.size.z * 0.5
    const ccx = c.center.x, ccy = c.center.y, ccz = c.center.z
    let allInside = true
    for (let i = 0; i < 8 && allInside; i++) {
      v.set(ccx + (i & 1 ? hx : -hx), ccy + (i & 2 ? hy : -hy), ccz + (i & 4 ? hz : -hz)).project(camera)
      if (v.z < -1 || v.z > 1) { allInside = false; break }
      const sx = ((v.x + 1) / 2) * width
      const sy = ((-v.y + 1) / 2) * height
      if (sx < cx1 || sx > cx2 || sy < cy1 || sy > cy2) allInside = false
    }
    if (allInside) hits.push(c.id)
  }
  return hits
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
export function initAssemblyLasso({ canvas, camera, controls, getInstanceCenters, onSelect, onClick }) {
  let state = null   // { startX, startY, overlayEl, additive } | null

  function createOverlay() {
    const div = document.createElement('div')
    div.style.cssText = (
      'position:fixed;border:1.5px dashed #8b5cf6;background:rgba(139,92,246,0.08);' +
      'pointer-events:none;z-index:1000;box-sizing:border-box'
    )
    document.body.appendChild(div)
    return div
  }

  function onMove(e) {
    if (!state?.overlayEl) return
    const el = state.overlayEl
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
    if ((cx2 - cx1) < 4 && (cy2 - cy1) < 4) { onClick?.(endE); return }
    const hits = instancesInRect(getInstanceCenters(), camera, { width: rect.width, height: rect.height }, cx1, cy1, cx2, cy2)
    onSelect(hits, s.additive)
  }

  function onUp(e) { finalize(e) }

  /** Begin a lasso if Ctrl/Meta is held; returns true if started. */
  function start(e) {
    if (!(e.ctrlKey || e.metaKey)) return false
    state = { startX: e.clientX, startY: e.clientY, overlayEl: createOverlay(), additive: e.shiftKey }
    controls.enabled = false
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup',   onUp)
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
