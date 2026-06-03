/**
 * Measurement tool — a 3D line + distance readout between exactly two
 * ctrl-clicked beads (press 'M'). Extracted from main.js.
 *
 * Stateful: it owns a THREE.Line in the scene and a fixed DOM readout box, and
 * it self-wires to the selection manager's ctrl-bead changes. So it's a factory
 * — pass its dependencies in and drive it through the returned API. Tested with
 * a mock scene + selectionManager (see measurement_tool.test.js).
 *
 * @param {object}   deps
 * @param {THREE.Scene} deps.scene
 * @param {object}   deps.selectionManager       — needs onCtrlBeadsChange(cb)
 * @param {Function} [deps.onSelectionHudChange] — called on every ctrl-bead change
 * @returns {{ show: Function, clear: Function, isActive: () => boolean, dispose: Function }}
 */
import * as THREE from 'three'

export function initMeasurementTool({ scene, selectionManager, onSelectionHudChange = () => {} }) {
  let line   = null   // THREE.Line currently in scene, or null
  let active = false
  let box    = null   // DOM element for distance readout

  function clear() {
    if (line) { scene.remove(line); line.geometry.dispose(); line.material.dispose(); line = null }
    if (box)  { box.style.display = 'none' }
    active = false
  }

  function show(posA, posB) {
    clear()
    const dist = posA.distanceTo(posB)

    const geo = new THREE.BufferGeometry().setFromPoints([posA, posB])
    const mat = new THREE.LineBasicMaterial({ color: 0x00e5ff, linewidth: 2, depthTest: false, transparent: true, opacity: 0.9 })
    line = new THREE.Line(geo, mat)
    line.renderOrder = 999
    scene.add(line)

    if (!box) {
      box = document.createElement('div')
      box.style.cssText =
        'position:fixed;left:12px;bottom:12px;z-index:500;display:none;pointer-events:none;' +
        'background:rgba(10,18,30,0.88);border:1px solid #00e5ff;border-radius:6px;' +
        'color:#00e5ff;font-family:var(--font-ui);font-size:13px;padding:6px 14px;' +
        'box-shadow:0 2px 8px rgba(0,0,0,0.5);'
      document.body.appendChild(box)
    }
    box.textContent = `Distance: ${dist.toFixed(3)} nm`
    box.style.display = 'block'
    active = true
  }

  // Clear the measurement when the ctrl-bead set is no longer a pair, and keep
  // the selection-count HUD in sync on every ctrl-bead change.
  selectionManager.onCtrlBeadsChange(beads => {
    if (active && beads.length !== 2) clear()
    onSelectionHudChange()
  })

  return {
    show,
    clear,
    isActive: () => active,
    dispose() {
      clear()
      if (box) { box.remove(); box = null }
    },
  }
}
