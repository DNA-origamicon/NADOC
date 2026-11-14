import * as THREE from 'three'
import { baseKey, atomBaseKey } from './base_ref.js'
import { bindSurfaceMotion } from './surface_motion.js'
import { canonicalAtomName } from './md_inset_atoms.js'

const key = n => baseKey(n, n.copy ?? n.copy_k ?? 0)
// Canonical names: NAMD (CHARMM) O1P/O2P/C5M are the design model's OP1/OP2/C7.
const atomKey = a => `${atomBaseKey(a)}:${a.name ? canonicalAtomName(a.name) : a.serial}`

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

// Chemical ring order used by backend/core/md_base_frames.py (ordered_ring_indices).
const PURINE_RING = ['N9','C8','N7','C5','C6','N1','C2','N3','C4']
const PYRIMIDINE_RING = ['N1','C2','N3','C4','C5','C6']
const measuredUpdate = n => n.measured_base === true && [n.nx,n.ny,n.nz,n.tx,n.ty,n.tz].every(Number.isFinite)

/** NAMD measured-base frame of one rest residue, in the backend's convention:
 * origin P (O5' for a 5' terminus), x = in-plane N1→C4 / N9→C6, z = ring-plane
 * normal signed by the ordered ring. Null when the residue cannot define it. */
export function measuredResidueFrame(atoms) {
  const origin = atoms.get('P') ?? atoms.get("O5'")
  const names = atoms.has('N9') ? PURINE_RING : PYRIMIDINE_RING
  const ring = names.map(name => atoms.get(name))
  if (!origin || ring.some(p => !p)) return null
  const v = ring.map(p => new THREE.Vector3(...p))
  // Newell normal of the ordered ring; sign matches cross(r1 - r0, r2 - r0).
  const normal = new THREE.Vector3()
  for (let i = 0; i < v.length; i++) {
    const a = v[i], b = v[(i + 1) % v.length]
    normal.x += (a.y - b.y) * (a.z + b.z); normal.y += (a.z - b.z) * (a.x + b.x); normal.z += (a.x - b.x) * (a.y + b.y)
  }
  const orient = new THREE.Vector3().subVectors(v[1], v[0]).cross(new THREE.Vector3().subVectors(v[2], v[0]))
  if (normal.dot(orient) < 0) normal.negate()
  if (normal.lengthSq() < 1e-16) return null
  normal.normalize()
  const inward = new THREE.Vector3().subVectors(v[v.length === 9 ? 4 : 3], v[0])
  inward.addScaledVector(normal, -inward.dot(normal))
  if (inward.lengthSq() < 1e-16) return null
  inward.normalize()
  return pose({ backbone_position: origin, nx: inward.x, ny: inward.y, nz: inward.z, tx: normal.x, ty: normal.y, tz: normal.z })
}

/** Inverse measured rest frames for every residue held by an inset atom renderer. */
function measuredRestInverses(renderer) {
  const residues = new Map()
  renderer.visitAtoms(a => {
    const k = atomBaseKey(a)
    if (!residues.has(k)) residues.set(k, new Map())
    residues.get(k).set(a.name, [a.x, a.y, a.z])
  })
  const inverses = new Map()
  for (const [k, atoms] of residues) {
    const frame = measuredResidueFrame(atoms)
    if (frame) inverses.set(k, frame.invert())
  }
  return inverses
}

/** Reuse the layer's meshes during playback; no per-frame HTTP or rebuilds. */
export function createZoomLayerMotion(display, geometry) {
  const rest = zoomMotionFrame(geometry, null)
  const inverse = new Map(rest.map(n => [key(n),pose(n).invert()]))
  const surfaces = new WeakMap(), measuredRest = new WeakMap()
  return {
    apply(frame, liveAtoms = null, active = true) {
      const transforms = new Map(frame.map(n => [key(n),pose(n).multiply(inverse.get(key(n)) ?? new THREE.Matrix4())]))
      // NAMD measured frames are atom-defined (P/O5' origin, base-ring axes), not the
      // design bead/base_normal convention; map them from the same frame on rest atoms.
      const measured = new Map(frame.filter(measuredUpdate).map(n => [key(n),pose(n)]))
      for (const entry of display.entries.values()) {
        if (!entry.ready) continue
        if (entry.cg) {
          entry.cg.applyFemPositions(active ? frame : null)
          entry.cg.applyRepOverrides(entry.columns)
        } else if (entry.kind === 'atom') {
          const atoms = [], positions = [], p = new THREE.Vector3()
          if (measured.size && !measuredRest.has(entry)) measuredRest.set(entry, measuredRestInverses(entry.renderer))
          const restFrames = measured.size ? measuredRest.get(entry) : null
          const residueTransforms = new Map()
          const transformFor = k => {
            if (!residueTransforms.has(k)) {
              const live = measured.get(k), rest = restFrames?.get(k)
              residueTransforms.set(k, live && rest ? live.clone().multiply(rest) : transforms.get(k))
            }
            return residueTransforms.get(k)
          }
          entry.renderer.visitAtoms(a => {
            atoms.push(a.serial)
            const exact = liveAtoms?.get(atomKey(a))
            if (exact) positions.push(...exact)
            else {
              p.set(a.x,a.y,a.z)
              const transform = transformFor(atomBaseKey(a))
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

/** Exact live atoms for the inset: the atomistic main viewport when it is showing MD
 * atoms, otherwise the Display-MD stream's exact atoms for the inset's own residues. */
export function zoomExactAtoms(renderer, insetAtoms = null) {
  const main = zoomLiveAtoms(renderer)
  if (!insetAtoms?.size) return main
  if (!main.size) return insetAtoms
  return new Map([...insetAtoms, ...main])
}
