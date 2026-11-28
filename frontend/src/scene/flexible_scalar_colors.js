import * as THREE from 'three'
import { parseBaseKey } from './base_ref.js'

/** Tube rings are sampled by arc length; map them back to nucleotide intervals. */
export function setFlexibleTubeColorCoordinates(geometry, curve, pointCount) {
  const uv = geometry.getAttribute('uv')
  geometry.userData.flexColorT = Array.from({ length: uv.count }, (_, i) =>
    curve.getUtoTmapping(uv.getX(i)) * (pointCount - 1))
}

/** Scalar colors override native flexible/cluster colors, including black and copy keys.
 * Missing measurements keep native colors; never infer a value for unpaired ssDNA.
 */
export function applyFlexibleScalarColors(group, design, keyOf, colors, displayOf) {
  const get = key => {
    if (!key || !colors) return undefined
    const read = k => colors instanceof Map ? colors.get(k) : colors[k]
    const ref = parseBaseKey(key)
    return (ref?.copy === 0 ? read(`${key}:0`) : undefined) ?? read(key)
  }
  const records = new Map((design?.flexible_connections ?? []).map(c => {
    const native = displayOf(c).color
    const keys = [c.anchor_a, ...(c.segment_bead_keys ?? []), c.anchor_b].map(keyOf)
    return [c.id, { native, colors: keys.map(key => get(key) ?? native), active: keys.some(key => get(key) != null) }]
  }))
  const color = new THREE.Color(), other = new THREE.Color()
  for (const mesh of group.children) {
    const rec = records.get(mesh.userData.connectionId)
    if (!rec) continue
    const mat = mesh.material
    mat.color.setHex(rec.active ? 0xffffff : rec.native)
    if (mesh.isInstancedMesh) {
      if (rec.active || mesh.instanceColor) {
        for (let i = 0; i < mesh.count; i++) mesh.setColorAt(i, color.setHex(rec.active ? (rec.colors[i + 1] ?? rec.native) : 0xffffff))
        mesh.instanceColor.needsUpdate = true
      }
    } else if (mesh.geometry.userData.flexColorT) {
      const geometry = mesh.geometry
      if (rec.active) {
        const values = new Float32Array(geometry.getAttribute('position').count * 3)
        geometry.userData.flexColorT.forEach((t, i) => {
          const lo = Math.min(Math.floor(t), rec.colors.length - 1), hi = Math.min(lo + 1, rec.colors.length - 1)
          color.setHex(rec.colors[lo]).lerp(other.setHex(rec.colors[hi]), t - lo).toArray(values, i * 3)
        })
        geometry.setAttribute('color', new THREE.BufferAttribute(values, 3))
      }
      mat.vertexColors = rec.active
    }
    mat.needsUpdate = true
  }
}
