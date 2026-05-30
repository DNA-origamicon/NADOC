/**
 * Strand-animation RENDERER — draws a strand-list (see model.js) into a THREE
 * scene in NADOC's ball-and-slab style, decoupled from the page/panel/camera.
 *
 * This is the second drop-in piece: a host (this page, or the main animation
 * toolset) calls `createStrandRenderer(scene)` once, then `update(strands)`
 * each frame/edit with the output of `buildStrandGeometry(params, phi)`. It
 * owns two InstancedMeshes (backbone balls + base slabs, packed strand after
 * strand) and a pooled THREE.Line per strand for the backbone connector. It
 * adds/removes only its own objects to the given `scene`, grows buffers as
 * needed, and never touches DOM, params, or the camera.
 *
 * Bead/slab dimensions + slab orientation/offset are copied verbatim from
 * scene/helix_renderer.js so the look matches the main 3D view (kept local so
 * this stays dependency-light; no import of that 4k-line module).
 */

import * as THREE from 'three'
import { ROLE_COLOR } from './model.js'

// ── ball-and-slab constants — MUST match scene/helix_renderer.js ─────────────
const BEAD_RADIUS = 0.10
const HELIX_RADIUS = 1.0
const SLAB = { length: 0.30, width: 0.06, thickness: 0.70, distance: 0.55 }
const GEO_SPHERE = new THREE.SphereGeometry(BEAD_RADIUS, 10, 8)
const GEO_BOX = new THREE.BoxGeometry(1, 1, 1)

function slabQuaternion(bnDir, tanDir, out) {
  const tangential = new THREE.Vector3().crossVectors(tanDir, bnDir).normalize()
  const m = new THREE.Matrix4().makeBasis(tangential, tanDir, bnDir)
  return out.setFromRotationMatrix(m)
}

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
  const _tan = new THREE.Vector3()
  const _bn = new THREE.Vector3()
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

  function _writeInstance(idx, pos, tan, bn, o, colorHex) {
    _v.set(pos[o], pos[o + 1], pos[o + 2])
    _m.compose(_v, _ID, _scaleBead)
    iBeads.setMatrixAt(idx, _m); iBeads.setColorAt(idx, _color.setHex(colorHex))
    _tan.set(tan[o], tan[o + 1], tan[o + 2]); _bn.set(bn[o], bn[o + 1], bn[o + 2])
    slabQuaternion(_bn, _tan, _q)
    _v.addScaledVector(_bn, HELIX_RADIUS - SLAB.distance)
    _m.compose(_v, _q, _scaleSlab)
    iSlabs.setMatrixAt(idx, _m); iSlabs.setColorAt(idx, _color.setHex(colorHex))
  }

  /** Draw the given strand list. Safe to call every frame. */
  function update(strands) {
    let total = 0, maxLen = 0
    for (const st of strands) { const c = st.pos.length / 3; total += c; if (c > maxLen) maxLen = c }
    _ensureInstanced(total)
    _ensureLines(strands.length, maxLen)

    let base = 0
    for (let s = 0; s < strands.length; s++) {
      const st = strands[s]
      const cnt = st.pos.length / 3
      const col = roleColor[st.role] ?? 0xffffff
      for (let i = 0; i < cnt; i++) _writeInstance(base + i, st.pos, st.tan, st.bn, i * 3, col)
      const ln = lines[s]
      const lp = ln.geometry.getAttribute('position')
      lp.array.set(st.pos); lp.needsUpdate = true
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
