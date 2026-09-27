import * as THREE from 'three'
import { makeImpostorPhongMaterial } from './impostor_material.js'

// Explicit, renderer-owned contracts. Unknown/custom shaders still fail export.
const sources = new WeakMap()
export function registerPreparedAssemblyMaterial(material, spec) {
  sources.set(material, { ...spec, compile: material.onBeforeCompile })
}
export function preparedAssemblyMaterial(material) {
  const spec = sources.get(material)
  return spec && spec.compile === material.onBeforeCompile ? spec : null
}

/** Freeze the same texture rows and LOD range used by the assembly shader.
 * Output uses the existing prepared-view format; no editor or topology data travels.
 */
export function bakePreparedAssemblyInstances(mesh) {
  if (!mesh.isInstancedMesh) return mesh
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  const spec = preparedAssemblyMaterial(materials[0])
  if (!spec) return mesh
  const { xform, visibility, local, positions, color, baseCount = 1, offset, radius } = spec
  const outer = xform.value.image.data, visible = visibility.value.image.data
  const inner = local?.value?.image.data, points = positions?.value?.image.data, colors = color?.value?.image.data
  const start = offset?.value ?? 0
  const rows = []
  for (let i = 0; i < mesh.count; i++) {
    const row = Math.floor(i / baseCount) + start
    if (visible[row * 16] >= .5) rows.push(i)
  }
  const matrices = new Float32Array(rows.length * 16), rgb = colors ? new Float32Array(rows.length * 3) : null
  const a = new THREE.Matrix4(), b = new THREE.Matrix4()
  for (let j = 0; j < rows.length; j++) {
    const i = rows[j], row = Math.floor(i / baseCount) + start, index = i % baseCount
    a.fromArray(outer, row * 16)
    if (inner) a.multiply(b.fromArray(inner, index * 16))
    else if (points) a.multiply(b.makeTranslation(points[index * 4], points[index * 4 + 1], points[index * 4 + 2]))
    // Assembly billboards use a fixed radius; the guest impostor shader scales
    // by instanceMatrix, so retain only the composed center for spheres.
    if (radius != null) a.makeTranslation(a.elements[12], a.elements[13], a.elements[14])
    a.toArray(matrices, j * 16)
    if (rgb) rgb.set(colors.subarray(index * 4, index * 4 + 3), j * 3)
  }
  const frozen = Object.create(mesh)
  frozen.count = rows.length
  frozen.instanceMatrix = new THREE.InstancedBufferAttribute(matrices, 16)
  frozen.instanceColor = rgb ? new THREE.InstancedBufferAttribute(rgb, 3) : null
  const frozenMaterials = materials.map(material => {
    const contract = preparedAssemblyMaterial(material)
    if (!contract) throw new Error('Unsupported mixed assembly materials')
    // Copy material properties without copying the editor shader or its textures.
    const result = radius == null ? new material.constructor() : makeImpostorPhongMaterial({ radius })
    const properties = Object.create(material); properties.userData = {}
    result.copy(properties)
    result.userData = {}
    if (radius == null) result.onBeforeCompile = contract.baseCompile ?? THREE.Material.prototype.onBeforeCompile
    return result
  })
  frozen.material = Array.isArray(mesh.material) ? frozenMaterials : frozenMaterials[0]
  return frozen
}
