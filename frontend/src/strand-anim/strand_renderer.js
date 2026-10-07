/** Render only complete backend-authorized poses, including transient rigid transport. */

import * as THREE from 'three'
import { ROLE_COLOR } from './model.js'
import { placementIntegrityFailure, validateNativePlacement } from '../viewer/native_placement.js'

// Mesh dimensions affect shape only; every center and rotation comes from a pose.
const BEAD_RADIUS = 0.10
const SLAB = { length: 0.30, width: 0.06, thickness: 0.70 }
const GEO_SPHERE = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8)
const GEO_BOX = new THREE.BoxGeometry(1, 1, 1)

/**
 * @param {THREE.Object3D} scene  scene or group to add the meshes/lines to
 * @param {object} [opts]
 * @param {Record<string,number>} [opts.roleColor]  role → hex (defaults to ROLE_COLOR)
 * @param {number} [opts.lineOpacity=0.55]
 * @returns {{ update:(strands:Array)=>void, dispose:()=>void }}
 */
export function createStrandRenderer(scene, { roleColor = ROLE_COLOR, lineOpacity = 0.55 } = {}) {
  let iBeads = null, iSlabs = null, _cap = 0       // instanced bead/slab capacity (grow-only)
  const lines = []                                  // pooled THREE.Line, one per strand
  let _lineCap = 0                                  // per-line vertex capacity (grow-only)

  // Reusable temporaries — no per-frame allocation.
  const _v = new THREE.Vector3()
  const _q = new THREE.Quaternion()
  const _m = new THREE.Matrix4()
  const _ID = new THREE.Quaternion()
  const _scaleBead = new THREE.Vector3(1, 1, 1)
  const _scaleSlab = new THREE.Vector3(SLAB.length, SLAB.width, SLAB.thickness)
  const _color = new THREE.Color()

  function _ensureInstanced(total) {
    if (iBeads && total <= _cap) return
    const cap = Math.max(total, Math.ceil(_cap * 1.5), 64)
    for (const o of [iBeads, iSlabs]) {
      if (!o) continue
      scene.remove(o); o.geometry.dispose(); o.material.dispose()
    }
    iBeads = new THREE.InstancedMesh(GEO_SPHERE, new THREE.MeshPhongMaterial({ color: 0xffffff }), cap)
    iSlabs = new THREE.InstancedMesh(GEO_BOX,
      new THREE.MeshPhongMaterial({ color: 0xffffff, transparent: true, opacity: 0.90 }), cap)
    iBeads.frustumCulled = false; iSlabs.frustumCulled = false
    iBeads.name = 'strandBeads'; iSlabs.name = 'strandSlabs'
    iBeads.setColorAt(0, _color.setHex(0xffffff)); iSlabs.setColorAt(0, _color.setHex(0xffffff))  // alloc instanceColor
    scene.add(iBeads); scene.add(iSlabs)
    _cap = cap
  }

  function _ensureLines(n, maxLen) {
    while (lines.length < n) {
      const ln = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ transparent: true, opacity: lineOpacity }))
      ln.frustumCulled = false
      ln.name = 'strandBackbone' + lines.length
      scene.add(ln)
      lines.push(ln)
    }
    if (maxLen > _lineCap) {
      _lineCap = Math.max(maxLen, Math.ceil(_lineCap * 1.5))
      for (const ln of lines) {
        ln.geometry.dispose()
        ln.geometry = new THREE.BufferGeometry()
        ln.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(_lineCap * 3), 3))
      }
    }
  }

  function _writeInstance(idx, nucleotide, colorHex) {
    _v.fromArray(nucleotide.backbone_position)
    _m.compose(_v, _ID, _scaleBead)
    iBeads.setMatrixAt(idx, _m); iBeads.setColorAt(idx, _color.setHex(colorHex))
    _v.fromArray(nucleotide.slab_position); _q.fromArray(nucleotide.slab_quaternion)
    _m.compose(_v, _q, _scaleSlab)
    iSlabs.setMatrixAt(idx, _m); iSlabs.setColorAt(idx, _color.setHex(colorHex))
  }

  /** Draw the given strand list. Safe to call every frame. */
  function update(strands) {
    let total = 0, maxLen = 0
    for (const st of strands) {
      if (!Array.isArray(st.nucleotides)) placementIntegrityFailure(null, 'animation_nucleotides', null,
        'Strand animation requires complete backend-authorized poses')
      for (const nucleotide of st.nucleotides) {
        validateNativePlacement(nucleotide)
        if (!nucleotide.slab_position) placementIntegrityFailure(nucleotide, 'slab_position', null,
          'This animation requires an authoritative slab pose')
      }
      const c = st.nucleotides.length; total += c; if (c > maxLen) maxLen = c
    }
    _ensureInstanced(total)
    _ensureLines(strands.length, maxLen)

    let base = 0
    for (let s = 0; s < strands.length; s++) {
      const st = strands[s]
      const cnt = st.nucleotides.length
      const col = roleColor[st.role] ?? 0xffffff
      for (let i = 0; i < cnt; i++) _writeInstance(base + i, st.nucleotides[i], col)
      const ln = lines[s]
      const lp = ln.geometry.getAttribute('position')
      for (let i = 0; i < cnt; i++) lp.array.set(st.nucleotides[i].backbone_position, i * 3)
      lp.needsUpdate = true
      ln.geometry.setDrawRange(0, cnt)
      ln.material.color.setHex(col)
      ln.visible = true
      base += cnt
    }
    for (let s = strands.length; s < lines.length; s++) lines[s].visible = false

    iBeads.count = base; iSlabs.count = base
    iBeads.instanceMatrix.needsUpdate = true; iBeads.instanceColor.needsUpdate = true
    iSlabs.instanceMatrix.needsUpdate = true; iSlabs.instanceColor.needsUpdate = true
  }

  function dispose() {
    for (const o of [iBeads, iSlabs, ...lines]) {
      if (!o) continue
      scene.remove(o); o.geometry.dispose(); o.material.dispose()
    }
    lines.length = 0
    iBeads = iSlabs = null
    _cap = 0; _lineCap = 0
  }

  return { update, dispose }
}
