import * as THREE from 'three'
import { interactionResidues, findBaseInteractions, singleInteractionBase } from './base_interactions.js'

let enabled = false
const listeners = new Set()
export function setBaseInteractionsEnabled(value) {
  enabled = !!value
  for (const refresh of listeners) refresh()
}
export function baseInteractionsEnabled() { return enabled }

/** Shares the preference across part, assembly and local atomistic renderers. */
export function createInteractionOverlay(state) {
  let group = null, previous = null
  function clear() {
    if (!group) return
    group.removeFromParent()
    for (const line of group.children) { line.geometry.dispose(); line.material.dispose() }
    group = null
  }
  function refresh() {
    const selected = singleInteractionBase(state.lastSel, state.mode)
    const signature = [enabled, selected, state.mode, state.atoms,
      ...Object.values(state.elementMeshes).flatMap(mesh => [mesh, mesh.instanceMatrix.version, mesh._instanceAlpha?.version])]
    if (previous?.length === signature.length && signature.every((v, i) => v === previous[i])) return
    previous = signature
    if (state.mode === 'off' || (!enabled && !selected)) { clear(); return }
    const positions = new Map()
    for (const [element, rows] of Object.entries(state.elementAtoms)) {
      const mesh = state.elementMeshes[element], matrices = mesh.instanceMatrix.array
      for (let i = 0; i < rows.length; i++) {
        const offset = i * 16
        if ((mesh._instanceAlpha?.array[i] ?? 1) <= 0 || matrices[offset] === 0) continue
        positions.set(rows[i], [matrices[offset + 12], matrices[offset + 13], matrices[offset + 14]])
      }
    }
    const contacts = findBaseInteractions(interactionResidues(state.atoms, row => positions.get(row)), enabled ? null : selected)
    clear()
    if (!contacts.length) return
    group = new THREE.Group(); group.name = 'base-interactions'
    for (const [type, color] of [['hydrogen', 0x36c6df], ['stacking', 0xe2a63b]]) {
      const matching = contacts.filter(c => c.type === type)
      if (!matching.length) continue
      const geometry = new THREE.BufferGeometry().setFromPoints(matching.flatMap(c => [c.start, c.end]))
      const material = new THREE.LineDashedMaterial({ color, dashSize: .045, gapSize: .035, depthTest: true })
      const line = new THREE.LineSegments(geometry, material)
      line.name = `base-interactions-${type}`
      line.userData.contacts = matching.map(c => ({ keys: c.keys, distance: c.start.distanceTo(c.end) }))
      line.computeLineDistances(); line.raycast = () => {}
      group.add(line)
    }
    state.scene.add(group)
  }
  listeners.add(refresh)
  return { refresh, dispose() { listeners.delete(refresh); clear() } }
}
