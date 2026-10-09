import * as THREE from 'three'
import { installInstanceAlpha } from './instance_alpha.js'
import { selfClosingPolymerSeam } from './polymer_seams.js'

export const POLYMER_PREVIEW_ALPHA = [0.55, 0.3, 0.1]
const key = n => `${n.helix_id}:${n.bp_index}:${n.direction}`

/** Only periodic connections have continuation previews, never ordinary free ends. */
export function polymerizationPreviewEnds(design, entries, slabs = []) {
  const beads = new Map(entries.map(e => [key(e.nuc), e]))
  const plates = new Map(slabs.map(e => [key(e.nuc), e]))
  const ends = [], seen = new Set()
  for (const seam of design?.forced_ligations ?? []) {
    if (!seam.is_periodic_seam) continue
    for (const side of ['three_prime', 'five_prime']) {
      const id = `${seam[`${side}_helix_id`]}:${seam[`${side}_bp`]}:${seam[`${side}_direction`]}`
      const end = beads.get(id)
      if (!end || seen.has(id)) continue
      const n = end.nuc
      // The immediate interior neighbour supplies the local helical step. Do
      // not extrapolate across the seam itself or another strand/crossover.
      const inner = [-1, 1].map(d => beads.get(`${n.helix_id}:${n.bp_index + d}:${n.direction}`))
        .find(e => e && e.nuc.strand_id === n.strand_id && e.nuc.domain_index === n.domain_index)
      if (!inner) continue
      seen.add(id)
      ends.push({ seam, end, inner, slab: plates.get(id), innerSlab: plates.get(key(inner.nuc)) })
    }
  }
  return ends
}

/** Rigid screw step: applying it repeatedly continues the local duplex twist. */
export function continuationStep(endFrame, innerFrame) {
  return endFrame.clone().multiply(innerFrame.clone().invert())
}

export function createPolymerizationPreview(root, design, entries, slabs, beadRadius = .1) {
  const ends = polymerizationPreviewEnds(design, entries, slabs)
  if (!ends.length) return null
  const group = new THREE.Group(); group.name = 'polymerizationContinuation'; group.userData.setupOnly = true
  root.add(group)
  const count = ends.length * 3
  function mesh(geometry, name) {
    const result = new THREE.InstancedMesh(geometry, new THREE.MeshPhongMaterial({ color: 0xffffff }), count)
    installInstanceAlpha(result)
    geometry.dispose() // installInstanceAlpha owns a clone of this private template.
    result.material.depthWrite = false
    result.name = name; result.frustumCulled = false; result.raycast = () => {}
    result.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    group.add(result)
    return result
  }
  const beads = mesh(new THREE.SphereGeometry(beadRadius, 8, 6), 'polymerizationPreviewBeads')
  const plates = mesh(new THREE.BoxGeometry(1, 1, 1), 'polymerizationPreviewBases')
  const bonds = mesh(new THREE.CylinderGeometry(.035, .035, 1, 6), 'polymerizationPreviewBonds')
  const matrix = new THREE.Matrix4(), endMatrix = new THREE.Matrix4(), innerMatrix = new THREE.Matrix4()
  const endFrame = new THREE.Matrix4(), innerFrame = new THREE.Matrix4(), slabMatrix = new THREE.Matrix4()
  const position = new THREE.Vector3(), scale = new THREE.Vector3(), orientation = new THREE.Quaternion()
  const prior = new THREE.Vector3(), current = new THREE.Vector3(), direction = new THREE.Vector3()
  const color = new THREE.Color(), unit = new THREE.Vector3(1, 1, 1), yAxis = new THREE.Vector3(0, 1, 0)
  const sources = [...new Set(ends.flatMap(e => [e.end, e.inner, e.slab, e.innerSlab].filter(Boolean).map(e => e.instMesh)))]
  let previous = ''
  let currentDesign = design
  const alpha = e => e?.instMesh.visible === false ? 0 : (e?.instMesh.geometry.getAttribute('instanceAlpha')?.getX(e.id) ?? 1) * (e?.instMesh.material.opacity ?? 1)
  function frame(entry, slab, output) {
    entry.instMesh.getMatrixAt(entry.id, matrix)
    position.setFromMatrixPosition(matrix)
    if (slab) {
      slab.instMesh.getMatrixAt(slab.id, output)
      output.decompose(current, orientation, scale)
    } else orientation.fromArray(entry.nuc.slab_quaternion ?? [0, 0, 0, 1])
    output.compose(position, orientation, unit)
  }
  function refresh() {
    const signature = sources.map(m => [m.instanceMatrix.version, m.instanceColor?.version,
      m.geometry.getAttribute('instanceAlpha')?.version, m.visible, m.material.opacity].join(':')).join('|')
    if (signature === previous) return
    previous = signature
    let i = 0
    group.visible = ends.some(e => !selfClosingPolymerSeam(currentDesign, e.seam))
    for (const e of ends) {
      frame(e.end, e.slab, endFrame); frame(e.inner, e.innerSlab, innerFrame)
      const step = continuationStep(endFrame, innerFrame)
      e.end.instMesh.getMatrixAt(e.end.id, endMatrix)
      e.inner.instMesh.getMatrixAt(e.inner.id, innerMatrix)
      const visible = !selfClosingPolymerSeam(currentDesign, e.seam) &&
        endMatrix.determinant() !== 0 && innerMatrix.determinant() !== 0
      if (e.slab) e.slab.instMesh.getMatrixAt(e.slab.id, slabMatrix)
      prior.setFromMatrixPosition(endMatrix)
      for (let k = 0; k < 3; k++, i++) {
        endMatrix.premultiply(step)
        beads.setMatrixAt(i, endMatrix)
        e.end.instMesh.getColorAt(e.end.id, color); beads.setColorAt(i, color); bonds.setColorAt(i, color)
        const opacity = visible ? POLYMER_PREVIEW_ALPHA[k] * alpha(e.end) : 0
        beads._instanceAlpha.setX(i, opacity); bonds._instanceAlpha.setX(i, opacity)
        if (e.slab) {
          slabMatrix.premultiply(step); plates.setMatrixAt(i, slabMatrix)
          e.slab.instMesh.getColorAt(e.slab.id, color); plates.setColorAt(i, color)
        }
        plates._instanceAlpha.setX(i, e.slab ? POLYMER_PREVIEW_ALPHA[k] * alpha(e.slab) * (visible ? 1 : 0) : 0)
        current.setFromMatrixPosition(endMatrix)
        direction.subVectors(current, prior)
        const length = direction.length()
        orientation.setFromUnitVectors(yAxis, direction.normalize())
        position.copy(prior).add(current).multiplyScalar(.5)
        matrix.compose(position, orientation, scale.set(1, length, 1)); bonds.setMatrixAt(i, matrix)
        prior.copy(current)
      }
    }
    for (const m of [beads, plates, bonds]) {
      m.instanceMatrix.needsUpdate = true
      if (m.instanceColor) m.instanceColor.needsUpdate = true
      m._instanceAlpha.needsUpdate = true
    }
  }
  // Scene matrix traversal happens before WebGL uploads. Refresh only when the
  // source instance buffers change, including live deformation and visibility.
  const updateWorld = group.updateMatrixWorld
  group.updateMatrixWorld = function (force) { refresh(); updateWorld.call(this, force) }
  refresh()
  return { group, refresh, setDesign(nextDesign) {
    if (currentDesign === nextDesign) return
    currentDesign = nextDesign
    previous = ''
    refresh()
  } }
}
