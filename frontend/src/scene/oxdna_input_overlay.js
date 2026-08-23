import * as THREE from 'three'
import { BASE_COLORS, C, buildClusterColorLookup, buildNucLetterMap,
  buildStapleColorMap, nucColor } from './helix_renderer/palette.js'

export const OXDNA_LENGTH_NM = 0.8518
export const OXDNA_VISUAL_SIZES_NM = Object.freeze({
  backboneRadius: 0.2 * OXDNA_LENGTH_NM,
  baseRadius: 0.3 * OXDNA_LENGTH_NM,
  baseScale: [0.7, 0.3, 0.7],
  connectorRadius: 0.1 * OXDNA_LENGTH_NM,
  backboneConnectorTopRadius: 0.1 * OXDNA_LENGTH_NM,
  backboneConnectorBottomRadius: 0.02 * OXDNA_LENGTH_NM,
})

const Y = new THREE.Vector3(0, 1, 0)
const tmpDir = new THREE.Vector3()
const tmpMid = new THREE.Vector3(), tmpQuat = new THREE.Quaternion(), tmpScale = new THREE.Vector3()
const tmpMatrix = new THREE.Matrix4(), tmpColor = new THREE.Color()

function frameSites(frame) {
  const r = new THREE.Vector3(...frame.r)
  const a1 = new THREE.Vector3(...frame.a1).normalize()
  const a3 = new THREE.Vector3(...frame.a3).normalize()
  const a2 = new THREE.Vector3().crossVectors(a3, a1).normalize()
  return {
    backbone: r.clone().addScaledVector(a1, -0.34 * OXDNA_LENGTH_NM)
      .addScaledVector(a2, 0.3408 * OXDNA_LENGTH_NM),
    base: r.clone().addScaledVector(a1, 0.34 * OXDNA_LENGTH_NM),
    a3,
  }
}

function cylinderMatrix(from, to, radialScale, out = new THREE.Matrix4()) {
  tmpDir.subVectors(to, from)
  const length = tmpDir.length()
  if (length < 1e-9) return null
  tmpMid.addVectors(from, to).multiplyScalar(0.5)
  tmpQuat.setFromUnitVectors(Y, tmpDir.divideScalar(length))
  tmpScale.set(radialScale, length, radialScale)
  return out.compose(tmpMid, tmpQuat, tmpScale)
}

function material() {
  // Use the editor's shared ambient/key/fill rig to give the backbone beads,
  // ovoid bases, and cylinders the rounded shading visible in oxDNA figures.
  // A restrained Phong highlight reads their shape without bleaching the paper
  // palette. The colour source is the
  // InstancedMesh.instanceColor attribute created by setColorAt().  Do not enable
  // material.vertexColors: these primitive geometries have no per-vertex `color`
  // attribute, so that second colour channel multiplies the instances to black.
  return new THREE.MeshPhongMaterial({
    color: 0xffffff,
    specular: 0x333333,
    shininess: 36,
  })
}

function effectiveColors(colorState = {}) {
  const colors = { ...(colorState.strandColors ?? {}) }
  for (const group of colorState.strandGroups ?? []) {
    if (!group?.color) continue
    const color = parseInt(String(group.color).replace('#', ''), 16)
    if (!Number.isFinite(color)) continue
    for (const strandId of group.strandIds ?? []) colors[strandId] = color
  }
  return colors
}

/** Canonical oxView/paper-style rigid-nucleotide representation. */
export function initOxdnaInputOverlay(scene) {
  let group = null
  let currentFrames = []
  let currentDesign = null
  let currentColorState = {}
  let coloringMode = 'base'

  function applyColors() {
    if (!group) return
    const backbones = group.children.find(mesh => mesh.userData.oxdnaPrimitive === 'backbone')
    const bases = group.children.find(mesh => mesh.userData.oxdnaPrimitive === 'base')
    const connectors = group.children.find(mesh => mesh.userData.oxdnaPrimitive === 'base-connector')
    const bonds = group.children.find(mesh => mesh.userData.oxdnaPrimitive === 'backbone-connector')
    const stapleColors = buildStapleColorMap(currentFrames, currentDesign)
    const customColors = effectiveColors(currentColorState)
    const loopSet = new Set(currentColorState.loopStrandIds ?? [])
    const clusterColor = buildClusterColorLookup(currentDesign)
    const letterMap = buildNucLetterMap(currentDesign, currentFrames)
    const strandColor = frame => nucColor(frame, stapleColors, customColors, loopSet)
    const nucleotideColor = frame => {
      if (coloringMode === 'cluster') return clusterColor(frame) ?? strandColor(frame)
      if (coloringMode === 'overhang-only') return frame.overhang_id != null ? strandColor(frame) : C.dim_gray
      if (coloringMode === 'base') {
        const letter = letterMap.get(frame) ?? String(frame.nucleobase ?? '').toUpperCase()
        return BASE_COLORS[letter] ?? strandColor(frame)
      }
      return strandColor(frame)
    }
    for (let i = 0; i < currentFrames.length; i++) {
      const frame = currentFrames[i]
      const color = nucleotideColor(frame)
      backbones.setColorAt(i, tmpColor.setHex(color))
      connectors.setColorAt(i, tmpColor.setHex(color))
      bases.setColorAt(i, tmpColor.setHex(color))
    }
    let bondIndex = 0
    for (const edge of group.userData.edges ?? []) {
      const frame = currentFrames[edge[0]]
      if (!frame) continue
      bonds.setColorAt(bondIndex++, tmpColor.setHex(nucleotideColor(frame)))
    }
    for (const mesh of [backbones, bases, connectors, bonds]) {
      if (mesh?.instanceColor) mesh.instanceColor.needsUpdate = true
    }
  }
  function clear() {
    if (!group) return
    scene.remove(group)
    group.traverse(object => {
      object.geometry?.dispose?.()
      object.material?.dispose?.()
    })
    group = null
    currentFrames = []
    currentDesign = null
    currentColorState = {}
  }

  function update(frames, edges, mode = 'base', design = null, colorState = {}) {
    clear()
    if (!frames?.length) return
    group = new THREE.Group()
    group.name = 'oxDNA input representation'
    group.userData.oxdnaInput = true
    group.userData.edges = edges ?? []
    currentFrames = frames
    currentDesign = design
    currentColorState = colorState
    coloringMode = ['strand', 'base', 'cluster', 'overhang-only'].includes(mode) ? mode : 'strand'
    const sites = frames.map(frameSites)
    const sphere = new THREE.SphereGeometry(1, 16, 12)
    const baseSphere = new THREE.SphereGeometry(1, 16, 12)
    const cylinder = new THREE.CylinderGeometry(1, 1, 1, 12, 1)
    const tapered = new THREE.CylinderGeometry(
      OXDNA_VISUAL_SIZES_NM.backboneConnectorTopRadius,
      OXDNA_VISUAL_SIZES_NM.backboneConnectorBottomRadius, 1, 12, 1)
    const backbones = new THREE.InstancedMesh(sphere, material(), frames.length)
    const bases = new THREE.InstancedMesh(baseSphere, material(), frames.length)
    const connectors = new THREE.InstancedMesh(cylinder, material(), frames.length)
    const backboneBonds = new THREE.InstancedMesh(tapered, material(), edges?.length ?? 0)
    for (const [mesh, primitive] of [[backbones, 'backbone'], [bases, 'base'],
      [connectors, 'base-connector'], [backboneBonds, 'backbone-connector']]) {
      mesh.frustumCulled = false
      mesh.name = `oxDNA ${primitive}`
      mesh.userData.oxdnaPrimitive = primitive
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      group.add(mesh)
    }

    for (let i = 0; i < frames.length; i++) {
      const frame = frames[i], site = sites[i]
      tmpMatrix.compose(site.backbone, new THREE.Quaternion(), new THREE.Vector3().setScalar(OXDNA_VISUAL_SIZES_NM.backboneRadius))
      backbones.setMatrixAt(i, tmpMatrix)
      tmpQuat.setFromUnitVectors(Y, site.a3)
      tmpScale.fromArray(OXDNA_VISUAL_SIZES_NM.baseScale).multiplyScalar(OXDNA_VISUAL_SIZES_NM.baseRadius)
      tmpMatrix.compose(site.base, tmpQuat, tmpScale)
      bases.setMatrixAt(i, tmpMatrix)
      const conMatrix = cylinderMatrix(site.backbone, site.base, OXDNA_VISUAL_SIZES_NM.connectorRadius, tmpMatrix)
      if (conMatrix) connectors.setMatrixAt(i, conMatrix)
    }
    let bondCount = 0
    for (const [from, to] of edges ?? []) {
      if (!sites[from] || !sites[to]) continue
      const matrix = cylinderMatrix(sites[from].backbone, sites[to].backbone, 1, tmpMatrix)
      if (!matrix) continue
      backboneBonds.setMatrixAt(bondCount, matrix)
      bondCount++
    }
    backboneBonds.count = bondCount
    for (const mesh of [backbones, bases, connectors, backboneBonds]) {
      mesh.instanceMatrix.needsUpdate = true
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    }
    applyColors()
    scene.add(group)
  }

  return {
    update, clear, dispose: clear, group: () => group,
    bounds() {
      if (!currentFrames.length) return null
      const box = new THREE.Box3()
      for (const frame of currentFrames) {
        const sites = frameSites(frame)
        box.expandByPoint(sites.backbone)
        box.expandByPoint(sites.base)
      }
      return box.isEmpty() ? null : { min: box.min.toArray(), max: box.max.toArray() }
    },
    setColoringMode(mode) {
      coloringMode = ['strand', 'base', 'cluster', 'overhang-only'].includes(mode) ? mode : 'strand'
      applyColors()
    },
    coloringMode: () => coloringMode,
  }
}
