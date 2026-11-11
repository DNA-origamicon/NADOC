import * as THREE from 'three'
import { pointInVolume } from './view_volumes.js'

/** Detached viewing state: never edit the job region or molecular document. */
export function copyZoomBox(box) {
  if (!box || ![box.min_corner, box.max_corner].every(a => Array.isArray(a) && a.length === 3 && a.every(Number.isFinite))) return null
  if (box.max_corner.some((x, i) => x <= box.min_corner[i])) return null
  const rotation = box.rotation ?? [0, 0, 0, 1]
  if (rotation.length !== 4 || !rotation.every(Number.isFinite) || !Math.hypot(...rotation)) return null
  return { shape: 'box', min_corner: [...box.min_corner], max_corner: [...box.max_corner], rotation: [...rotation] }
}

export function zoomBoxBounds(volume) {
  const bounds = new THREE.Box3(), center = new THREE.Vector3().fromArray(volume.min_corner).add(new THREE.Vector3(...volume.max_corner)).multiplyScalar(.5)
  const q = new THREE.Quaternion(...volume.rotation)
  for (const x of [volume.min_corner[0], volume.max_corner[0]]) for (const y of [volume.min_corner[1], volume.max_corner[1]]) for (const z of [volume.min_corner[2], volume.max_corner[2]]) {
    bounds.expandByPoint(new THREE.Vector3(x,y,z).sub(center).applyQuaternion(q).add(center))
  }
  return bounds
}

export function entriesInZoomBox(entries, volume, matrix = new THREE.Matrix4()) {
  return entries.filter(e => pointInVolume(e.pos.clone().applyMatrix4(matrix).toArray(), volume))
}
