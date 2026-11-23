/** Shaded SNUPI physical-result glyphs, using mrDNA's instanced sphere/stick approach.
 * Consumes the bounded CVIZ transport; never infers molecular bonds or edits a design.
 * Axis/joint pairs are supplied by the solver adapter; nucleotide frames retain every site.
 */
import * as THREE from 'three'
import { colormapHex } from '../ui/colormaps.js'
import { progressiveIndices } from './cando_large_view.js'

const PALETTE = [0x58a6ff, 0xf2a65a, 0x62cba5, 0xc798f2, 0xef7e94, 0x65cbd4]
export function snupiSiteColor(data, i, lo, hi, cmap = 'jet') {
  const scalar = data.scalars[i]
  if (data.meta.kind !== 'deform') {
    return Number.isFinite(scalar) && scalar >= 0
      ? colormapHex(cmap, (scalar - lo) / Math.max(hi - lo, 1e-9)) : 0x94a3b8
  }
  return PALETTE[Math.abs(data.identities?.[4 * i] ?? 0) % PALETTE.length]
}

/** Detail depends on projected tile area, not molecular size. Progressive
 * prefixes cover each tile; zooming in restores every saved site. Tubes/joints
 * always retain every recorded segment to avoid inventing breaks. */
export function snupiGlyphCount(radiusPixels, count) {
  return Math.min(count, Math.max(32, Math.ceil(radiusPixels * radiusPixels * .15)))
}

export function initSnupiResultView(scene) {
  let root = null, data = null, box = null, renderer = null
  let meshes = [], geometry = null, material = null
  let lo = 0, hi = 1, cmap = 'jet'
  const dummy = new THREE.Object3D(), a = new THREE.Vector3(), b = new THREE.Vector3()
  const direction = new THREE.Vector3(), y = new THREE.Vector3(0, 1, 0), color = new THREE.Color()
  const lines = () => data?.meta.kind === 'cando'
  function clear() {
    if (root) scene.remove(root)
    geometry?.dispose(); material?.dispose(); meshes.forEach(mesh => mesh.dispose())
    root = null; meshes = []; geometry = null; material = null; data = null; box = null; renderer = null
  }
  function coordinates() {
    if (!root) return
    const stride = lines() ? 2 : 1
    box = new THREE.Box3().setFromArray(data.positions).expandByScalar(lines() ? 1.125 : .24)
    for (const mesh of meshes) {
      mesh.count = mesh.userData.indices.length
      for (let slot = 0; slot < mesh.userData.indices.length; slot++) {
        const i = mesh.userData.start + mesh.userData.indices[slot]
        a.fromArray(data.positions, 3 * i * stride)
        if (lines()) {
          b.fromArray(data.positions, 3 * (2 * i + 1)); direction.subVectors(b, a)
          const length = direction.length()
          dummy.position.copy(a).add(b).multiplyScalar(.5)
          dummy.quaternion.setFromUnitVectors(y, length ? direction.divideScalar(length) : y)
          const radius = i >= data.meta.count / 2 - (data.meta.joints || 0) ? .2 : 1.125
          dummy.scale.set(radius, length, radius)
        } else {
          dummy.position.copy(a); dummy.quaternion.identity(); dummy.scale.setScalar(.24)
        }
        dummy.updateMatrix(); mesh.setMatrixAt(slot, dummy.matrix)
      }
      mesh.instanceMatrix.needsUpdate = true
      mesh.computeBoundingBox(); mesh.computeBoundingSphere()
    }
  }
  function recolor(low, high, map = cmap) {
    lo = low; hi = high; cmap = map
    if (!root) return
    for (const mesh of meshes) {
      for (let slot = 0; slot < mesh.userData.indices.length; slot++) {
        const i = mesh.userData.start + mesh.userData.indices[slot]
        color.setHex(snupiSiteColor(data, lines() ? i * 2 : i, lo, hi, cmap))
        mesh.setColorAt(slot, color)
      }
      mesh.instanceColor.needsUpdate = true
    }
    publish()
  }
  function update(next, map = 'jet') {
    clear(); data = next
    root = new THREE.Group(); root.name = 'snupi-result'; root.userData.count = data.meta.count
    geometry = lines() ? new THREE.CylinderGeometry(1, 1, 1, 8, 1) : new THREE.SphereGeometry(1, 8, 6)
    material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .6, metalness: .05 })
    const count = data.meta.count / (lines() ? 2 : 1)
    for (let start = 0; start < count; start += 4096) {
      const n = Math.min(4096, count - start)
      const mesh = new THREE.InstancedMesh(geometry, material, n)
      mesh.userData.start = start; mesh.userData.indices = progressiveIndices(n)
      mesh.frustumCulled = false; mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      if (!lines()) {
        const center = new THREE.Vector3()
        mesh.onBeforeRender = (webgl, _scene, camera) => {
          const sphere = mesh.boundingSphere
          center.copy(sphere.center).applyMatrix4(mesh.matrixWorld)
          const radius = sphere.radius * mesh.matrixWorld.getMaxScaleOnAxis()
          const pixels = camera.isPerspectiveCamera
            ? radius * webgl.domElement.height / (2 * Math.tan(camera.fov * Math.PI / 360) * Math.max(camera.near, camera.position.distanceTo(center) - radius))
            : radius * webgl.domElement.height * camera.zoom / Math.max(1e-9, camera.top - camera.bottom)
          mesh.count = snupiGlyphCount(pixels, n)
        }
      }
      meshes.push(mesh); root.add(mesh)
    }
    scene.add(root)
    coordinates(); recolor(data.meta.min ?? 0, data.meta.max ?? 1, map)
  }
  function updatePositions(next) {
    if (!root || next.meta.kind !== data.meta.kind || next.meta.count !== data.meta.count) { update(next, cmap); return }
    data.positions.set(next.positions)
    coordinates(); publish()
  }
  function identity(i) {
    const ids = data.identities
    return { helix_id: data.meta.helix_ids[ids[4*i]], bp_index: ids[4*i+1],
      direction: ids[4*i+2] ? 'REVERSE' : 'FORWARD', copy: ids[4*i+3] }
  }
  function publish() {
    if (!renderer || !data?.identities) return
    const updates = [], colors = {}
    for (let i = 0; i < data.meta.count; i++) {
      const n = identity(i)
      updates.push({ ...n, backbone_position: Array.from(data.positions.subarray(3*i, 3*i+3)) })
      const prefix = `${n.helix_id}:${n.bp_index}:${n.direction}`
      colors[`${prefix}:${n.copy}`] = snupiSiteColor(data, i, lo, hi, cmap)
      if (!n.copy) colors[prefix] = colors[`${prefix}:${n.copy}`]
    }
    renderer.applyFemPositions(updates); renderer.applyScalarColors(colors)
  }
  function materialize(target) {
    if (!data?.identities || renderer) return false
    renderer = target; root.visible = false; publish(); return true
  }
  function coloringInfo() {
    if (!data?.identities || !['flex', 'deviation'].includes(data.meta.kind)) return null
    const flex = data.meta.kind === 'flex', values = []
    for (let i = 0; i < data.meta.count; i++) if (data.scalars[i] >= 0) values.push({ ...identity(i), value: data.scalars[i] })
    return { attribute: flex ? 'rmsf' : 'deviation', title: flex ? 'RMSF' : 'Deviation', unit: 'nm', colormap: cmap, lo, hi, values }
  }
  return { update, updatePositions, recolor, clear, materialize, coloringInfo,
    threshold: 0, representation: mode => mode === 'cando' ? 'shaded FEM tubes and crossover joints' : 'zoom-adaptive shaded nucleotide beads',
    active: () => !!root, materialized: () => !!renderer, getBoundingBox: () => box }
}
