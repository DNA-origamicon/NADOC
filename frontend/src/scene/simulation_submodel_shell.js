import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'

/** Rounded offset surface: Euclidean distance r from the oriented mobile box. */
export function createSubmodelShell(scene) {
  if (!scene) return { update() {}, dispose() {}, visible: () => false }
  const root = new THREE.Group()
  root.name = 'simulation-submodel-shell'
  scene.add(root)
  let signature = null
  function clear() {
    for (const child of [...root.children]) { child.geometry.dispose(); child.material.dispose(); root.remove(child) }
  }
  function update(box, visible) {
    const r = box?.shell_nm ?? 3
    root.visible = !!box && visible && r > 0
    if (!box) return
    const key = JSON.stringify([box.min_corner, box.max_corner, r])
    if (key !== signature) {
      clear(); signature = key
      if (r > 0) {
        const size = box.max_corner.map((x, i) => x - box.min_corner[i] + 2 * r)
        const geometry = new RoundedBoxGeometry(...size, 5, r)
        const surface = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0x39c6b5, opacity: 0.10, transparent: true, depthWrite: false, side: THREE.DoubleSide }))
        surface.raycast = () => {} // the existing mobile-box editor owns all picking
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 12), new THREE.LineBasicMaterial({ color: 0x39c6b5, opacity: 0.6, transparent: true, depthWrite: false }))
        edges.raycast = () => {}
        root.add(surface, edges)
      }
    }
    root.position.fromArray(box.min_corner.map((x, i) => (x + box.max_corner[i]) / 2))
    root.quaternion.fromArray(box.rotation ?? [0, 0, 0, 1]).normalize()
  }
  return { update, visible: () => root.visible, dispose() { clear(); root.removeFromParent() } }
}
