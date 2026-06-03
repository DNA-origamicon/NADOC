/**
 * Assembly overhang hover/pick — proximity-based (project anchors to screen, take
 * the nearest within a pixel radius; no exact-sprite raycast). Extracted from
 * main.js. `nearestAnchorToPoint` is the PURE projection core; the factory owns
 * the transient hover-key state and is wired with lazy getters so it doesn't
 * capture assemblyRenderer at construction time. Unit-tested in
 * overhang_hover_picker.test.js.
 */
import * as THREE from 'three'

export const OVHG_PICK_RADIUS_PX = 36

/**
 * Nearest anchor (by screen distance) to a client point, within `radiusPx`, or
 * null. Anchors are { world: THREE.Vector3-like, ... }. Capped at 1200 anchors
 * (perf — callers fall back to "show all" above that).
 */
export function nearestAnchorToPoint(anchors, camera, rect, clientX, clientY, radiusPx) {
  if (!anchors?.length || anchors.length > 1200) return null
  const v = new THREE.Vector3()
  let best = null, bestD = radiusPx
  for (const a of anchors) {
    v.copy(a.world).project(camera)
    if (v.z < -1 || v.z > 1) continue
    const sx = rect.left + (v.x * 0.5 + 0.5) * rect.width
    const sy = rect.top  + (-v.y * 0.5 + 0.5) * rect.height
    const d = Math.hypot(sx - clientX, sy - clientY)
    if (d < bestD) { bestD = d; best = a }
  }
  return best
}

/**
 * @param {object} deps
 * @param {THREE.Camera} deps.camera
 * @param {HTMLElement} deps.canvas
 * @param {() => Array} deps.getAnchors      lazy: assemblyRenderer.getOverhangAnchors()
 * @param {(oh:any)=>void} deps.setHovered   lazy: assemblyRenderer.setHoveredOverhang()
 * @param {() => boolean} deps.getToolActive overhang tool armed?
 * @returns {{ nearestAt:Function, onHoverMove:Function, reset:Function }}
 */
export function initOverhangHoverPicker({ camera, canvas, getAnchors, setHovered, getToolActive, radiusPx = OVHG_PICK_RADIUS_PX }) {
  let hoverKey = null

  function nearestAt(clientX, clientY, r = radiusPx) {
    const rect = canvas.getBoundingClientRect()
    const best = nearestAnchorToPoint(getAnchors?.(), camera, rect, clientX, clientY, r)
    return best ? { instanceId: best.instanceId, overhangId: best.overhangId, label: best.label } : null
  }

  // Hover: reveal the nearest overhang's label transiently. Skipped while a
  // button is held (orbit/drag) and gated on the overhang tool. Deduped so the
  // renderer is only notified on change.
  function onHoverMove(e) {
    if (e.buttons !== 0) return
    if (!getToolActive()) {
      if (hoverKey !== null) { hoverKey = null; setHovered(null) }
      return
    }
    const oh = nearestAt(e.clientX, e.clientY)
    const key = oh ? `${oh.instanceId}|${oh.overhangId}` : null
    if (key === hoverKey) return
    hoverKey = key
    setHovered(oh)
  }

  function reset() { hoverKey = null; setHovered(null) }

  return { nearestAt, onHoverMove, reset }
}
