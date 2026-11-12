import * as THREE from 'three'

/** Presentation/input state only; the lattice footprint and extrusion inputs survive Next/Previous. */
export function createLatticeAuthoringStage({ pickerNodes, preview, getCells, isSelected, getDirection, getLengthNm, getDesign, getAxes }) {
  let stage = null
  const visibility = new Map(), listeners = new Set()
  function restore() { for (const [node, visible] of visibility) node.visible = visible; visibility.clear() }
  function sync() {
    restore()
    for (const node of stage === 'section' ? [preview] : stage === 'length' ? pickerNodes : []) {
      visibility.set(node, node.visible); node.visible = false
    }
  }
  return {
    set(value) { stage = value; sync() },
    canPick: () => stage !== 'length',
    canCommit: () => stage !== 'section',
    restore,
    sourceReady() { sync(); for (const listener of listeners) listener() },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    bounds(includeLength = false) {
      const all = getCells(), selected = all.filter(isSelected)
      const cells = selected.length ? selected : all
      const box = new THREE.Box3()
      for (const cell of cells) {
        const start = cell.fill.getWorldPosition(new THREE.Vector3())
        box.expandByPoint(start)
        if (includeLength && selected.length) box.expandByPoint(start.clone().addScaledVector(getDirection(cell), getLengthNm()))
      }
      if (includeLength) {
        const axes = getAxes?.() ?? {}
        for (const helix of getDesign?.()?.helices ?? []) {
          const samples = axes[helix.id]?.samples
          if (samples?.length) for (const p of samples) box.expandByPoint(new THREE.Vector3(...p))
          else for (const p of [helix.axis_start, helix.axis_end]) if (p) box.expandByPoint(new THREE.Vector3(p.x, p.y, p.z))
        }
      }
      return box.isEmpty() ? null : box.expandByScalar(1.5)
    },
  }
}
