import * as THREE from 'three'
import { createGlowLayer } from './glow_layer.js'
import { baseKey } from './base_ref.js'

/** Independent display overlay; never writes the editor's selection. */
export function initZoomVolumeHighlight(scene, id) {
  const group = new THREE.Group(); group.name = `Zoom highlight ${id}`; group.visible = false; scene.add(group)
  const glow = createGlowLayer(group, 0x67c5ff, 3.5, `Zoom highlight atoms ${id}`)
  const boxes = [], sources = []
  let lastAtoms = null, centers = new Map()
  const helper = obj => { obj.userData.helper = true; obj.userData.setupOnly = true; obj.raycast = () => {} }
  helper(group)
  return {
    add(entries, matrix = null, externalBounds = null) {
      sources.push(...entries.map(e => ({ entry:e, key:baseKey(e.nuc,e.nuc.copy_k ?? e.nuc.copy ?? 0), matrix })))
      if (externalBounds && !externalBounds.isEmpty()) {
        const box = new THREE.Box3Helper(externalBounds.clone(), 0x67c5ff); helper(box); group.add(box); boxes.push(box)
      }
      lastAtoms = null
    },
    update(enabled, atoms = null) {
      group.visible = !!enabled
      if (!enabled) return
      if (atoms !== lastAtoms) {
        centers = new Map(); const wanted = new Set(sources.filter(s => !s.matrix).map(s => s.key))
        for (const [key,p] of atoms ?? []) {
          const residue = key.slice(0,key.lastIndexOf(':'))
          if (!wanted.has(residue)) continue
          let c=centers.get(residue);if(!c){c={pos:new THREE.Vector3(),n:0};centers.set(residue,c)}
          c.pos.add(new THREE.Vector3(...p));c.n++
        }
        for(const c of centers.values())c.pos.divideScalar(c.n)
        lastAtoms = atoms
      }
      glow.setEntries(sources.map(s => ({pos:s.matrix ? s.entry.pos.clone().applyMatrix4(s.matrix) : centers.get(s.key)?.pos ?? s.entry.pos})))
      helper(glow.getMesh())
    },
    clear() { sources.length=0;glow.clear();lastAtoms=null;centers.clear();for(const b of boxes){b.removeFromParent();b.geometry.dispose();b.material.dispose()}boxes.length=0;group.visible=false },
    dispose() { this.clear();glow.dispose();group.removeFromParent() },
  }
}
