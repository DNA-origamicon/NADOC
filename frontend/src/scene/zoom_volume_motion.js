import * as THREE from 'three'
import { baseKey, atomBaseKey } from './base_ref.js'
import { bindSurfaceMotion } from './surface_motion.js'

const key = n => baseKey(n, n.copy ?? n.copy_k ?? 0)
const atomKey = a => `${atomBaseKey(a)}:${a.name || a.serial}`

/** Physical display poses only; never writes the document or simulation inputs. */
export function zoomMotionFrame(geometry, updates, liveEntries = []) {
  const byKey = new Map((updates ?? []).map(n => [key(n), n]))
  const live = new Map(liveEntries.map(e => [baseKey(e.nuc, e._copy ?? e.nuc.copy_k ?? e.nuc.copy ?? 0), e.pos]))
  return geometry.map(n => {
    const u = byKey.get(key(n))
    const pos = live.get(key(n))?.toArray() ?? u?.backbone_position ?? n.backbone_position
    return { ...n, ...u, copy: u?.copy ?? n.copy_k ?? n.copy ?? 0, backbone_position: pos,
      nx: u?.nx ?? n.base_normal?.[0] ?? 1, ny: u?.ny ?? n.base_normal?.[1] ?? 0, nz: u?.nz ?? n.base_normal?.[2] ?? 0,
      tx: u?.tx ?? n.axis_tangent?.[0] ?? 0, ty: u?.ty ?? n.axis_tangent?.[1] ?? 0, tz: u?.tz ?? n.axis_tangent?.[2] ?? 1 }
  })
}
function pose(n) {
  const x = new THREE.Vector3(n.nx,n.ny,n.nz).normalize()
  const z = new THREE.Vector3(n.tx,n.ty,n.tz).normalize()
  if (x.lengthSq() < 1e-12) x.set(1,0,0)
  z.addScaledVector(x,-z.dot(x))
  if (z.lengthSq() < 1e-12) {
    z.set(Math.abs(x.x) < .8 ? 1 : 0,Math.abs(x.x) < .8 ? 0 : 1,0)
    z.addScaledVector(x,-z.dot(x))
  }
  z.normalize()
  const y = new THREE.Vector3().crossVectors(z,x).normalize()
  z.crossVectors(x,y).normalize()
  return new THREE.Matrix4().makeBasis(x,y,z).setPosition(...n.backbone_position)
}
const packed = frame => Float64Array.from(frame.flatMap(n => [...n.backbone_position,n.nx,n.ny,n.nz,n.tx,n.ty,n.tz]))

/** Reuse the layer's meshes during playback; no per-frame HTTP or rebuilds. */
export function createZoomLayerMotion(display, geometry) {
  const rest = zoomMotionFrame(geometry, null)
  const inverse = new Map(rest.map(n => [key(n),pose(n).invert()]))
  const surfaces = new WeakMap()
  return {
    apply(frame, liveAtoms = null, active = true) {
      const transforms = new Map(frame.map(n => [key(n),pose(n).multiply(inverse.get(key(n)) ?? new THREE.Matrix4())]))
      for (const entry of display.entries.values()) {
        if (!entry.ready) continue
        if (entry.cg) {
          entry.cg.applyFemPositions(active ? frame : null)
          entry.cg.applyRepOverrides(entry.columns)
        } else if (entry.kind === 'atom') {
          const atoms = [], positions = [], p = new THREE.Vector3()
          entry.renderer.visitAtoms(a => {
            atoms.push(a.serial)
            const exact = liveAtoms?.get(atomKey(a))
            if (exact) positions.push(...exact)
            else {
              p.set(a.x,a.y,a.z)
              const transform = transforms.get(atomBaseKey(a))
              if (transform) p.applyMatrix4(transform)
              positions.push(p.x,p.y,p.z)
            }
          })
          entry.renderer.applyCompactFrame({serialMap:atoms,dense:Float32Array.from(positions)})
        } else if (entry.motionMesh) {
          if (!surfaces.has(entry)) surfaces.set(entry,bindSurfaceMotion(entry.motionMesh,rest.map(n => [n.helix_id,n.bp_index,n.direction]),packed(rest)))
          const motion = surfaces.get(entry)
          if (motion) entry.renderer.applyDeformedFrame(entry.motionMesh,motion.deform(packed(frame)))
        }
      }
    },
  }
}

export function zoomLiveAtoms(renderer) {
  const result = new Map()
  renderer?.visitAtoms((atom, pos) => result.set(atomKey(atom),pos.toArray()))
  return result
}
