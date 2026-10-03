import * as THREE from 'three'
import { markAttributeRange } from './attribute_updates.js'

const selectionCompilers = new WeakMap()
export function selectionBaseCompiler(material) {
  const spec = selectionCompilers.get(material)
  return spec?.compile === material.onBeforeCompile ? spec.base : material.onBeforeCompile
}

// Independent of instanceColor and instanceAlpha: repainting or fading a molecule
// must not erase selection, and clearing selection must not restore stale colors.
export function patchSelectionTint(shader) {
  shader.vertexShader = 'attribute float instanceSelection;\nvarying float vSelection;\n' + shader.vertexShader
  shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>',
    '#include <begin_vertex>\nvSelection = instanceSelection;')
  shader.fragmentShader = 'varying float vSelection;\n' + shader.fragmentShader
  shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>',
    'outgoingLight = mix(outgoingLight, vec3(0.22, 1.0, 0.42), 0.48 * vSelection);\n#include <opaque_fragment>')
}

export function installSelectionTint(mesh) {
  if (!mesh?.isMesh) return null
  let attr = mesh.geometry.getAttribute('instanceSelection')
  if (!attr) {
    const previous = mesh.geometry
    mesh.geometry = previous.clone()
    // Renderers keep direct pointers to their live per-instance channels.
    for (const [name, attribute] of Object.entries(previous.attributes))
      if (attribute.isInstancedBufferAttribute) mesh.geometry.setAttribute(name, attribute)
    attr = mesh.isInstancedMesh
      ? new THREE.InstancedBufferAttribute(new Float32Array(mesh.instanceMatrix.count), 1)
      : new THREE.BufferAttribute(new Float32Array(mesh.geometry.attributes.position.count), 1)
    attr.setUsage(THREE.DynamicDrawUsage)
    mesh.geometry.setAttribute('instanceSelection', attr)
  }
  for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
    if (material.userData.selectionTint) continue
    material.userData.selectionTint = true
    // The trusted impostor compiler composes the patch itself, preserving its
    // export/raycast identity and its sphere depth and alpha behavior.
    if (!material.userData.isImpostor) {
      const compile = material.onBeforeCompile
      const cacheKey = material.customProgramCacheKey.bind(material)
      const key = cacheKey()
      material.onBeforeCompile = function (shader, renderer) {
        compile.call(this, shader, renderer)
        if (!shader.vertexShader.includes('attribute float instanceSelection;')) patchSelectionTint(shader)
      }
      material.customProgramCacheKey = () => `${key}:selection-tint-v1:${material.userData.instanceAlphaPatch ? "alpha" : "opaque"}`
      selectionCompilers.set(material, { compile: material.onBeforeCompile, base: compile })
    }
    material.needsUpdate = true
  }
  return attr
}

export function updateSelectionTint(mesh, previous, next) {
  const attr = next.size ? installSelectionTint(mesh) : mesh.geometry.getAttribute('instanceSelection')
  if (!attr) return
  let first = Infinity, last = -1
  const write = (id, value) => {
    if (attr.array[id] === value) return
    attr.setX(id, value); first = Math.min(first, id); last = Math.max(last, id)
  }
  if (mesh.isInstancedMesh) {
    for (const id of previous) if (!next.has(id)) write(id, 0)
    for (const id of next) write(id, 1)
  } else if (!!previous.size !== !!next.size || attr.array[0] !== (next.size ? 1 : 0)) {
    attr.array.fill(next.size ? 1 : 0); first = 0; last = attr.count - 1
  }
  if (last >= 0) markAttributeRange(attr, first, last - first + 1)
}

export function createClusterSelection(scene) {
  let selected = new Map()
  let groups = []
  let versions = ''
  const geometry = new THREE.BufferGeometry()
  const material = new THREE.LineBasicMaterial({ color: 0x38ff6b, depthTest: true, depthWrite: false })
  const corners = new THREE.LineSegments(geometry, material)
  corners.name = 'clusterSelectionCorners'
  corners.userData.presentationSelection = 'corners'
  corners.frustumCulled = false
  corners.visible = false
  scene.add(corners)
  const matrix = new THREE.Matrix4(), position = new THREE.Vector3()
  const instanceBounds = new THREE.Box3()
  const boundsVersions = new WeakMap()
  const instanceAttributes = new WeakMap()

  function clear() {
    for (const [mesh, ids] of selected) updateSelectionTint(mesh, ids, new Set())
    selected = new Map(); groups = []; versions = ''; corners.visible = false
  }
  function refresh(force = false) {
    if (!groups.length) return
    const visibleMeshes = new Map()
    for (const mesh of selected.keys()) {
      if (instanceAttributes.get(mesh) !== mesh.instanceMatrix || boundsVersions.get(mesh.geometry)?.attribute !== mesh.geometry.attributes.position) force = true
      instanceAttributes.set(mesh, mesh.instanceMatrix)
      mesh.updateWorldMatrix(true, false)
      let visible = mesh.material?.visible !== false && mesh.material?.opacity !== 0
      for (let parent = mesh; parent; parent = parent.parent) visible &&= parent.visible
      visibleMeshes.set(mesh, visible)
    }
    const next = [...selected.keys()].map(m => `${m.id}:${m.geometry.id}:${m.geometry.attributes.position.version}:${m.instanceMatrix?.version}:${m.count}:${visibleMeshes.get(m)}:${m.matrixWorld.elements.join(',')}`).join('|')
    if (!force && next === versions) return
    versions = next
    for (const mesh of selected.keys()) {
      const g = mesh.geometry, p = g.attributes.position, previous = boundsVersions.get(g)
      if (!g.boundingBox || previous?.attribute !== p || previous.version !== p.version) {
        g.computeBoundingBox(); boundsVersions.set(g, { attribute: p, version: p.version })
      }
    }
    const vertices = []
    for (const group of groups) {
      const bounds = new THREE.Box3()
      for (const entry of group) {
        const mesh = entry.instMesh, id = entry.id
        if (!mesh?.isMesh || (mesh.isInstancedMesh && id >= mesh.count)) continue
        if (!visibleMeshes.get(mesh)) continue
        if (!mesh.isInstancedMesh) {
          if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox()
          bounds.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld))
          continue
        }
        mesh.getMatrixAt(id, matrix)
        matrix.premultiply(mesh.matrixWorld)
        if (matrix.determinant() === 0) continue
        if (mesh.material.userData.isImpostor) {
          position.setFromMatrixPosition(matrix)
          const radius = mesh.material.userData.impostorRadius * matrix.getMaxScaleOnAxis()
          instanceBounds.min.copy(position).addScalar(-radius)
          instanceBounds.max.copy(position).addScalar(radius)
        } else {
          if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox()
          instanceBounds.copy(mesh.geometry.boundingBox).applyMatrix4(matrix)
        }
        bounds.union(instanceBounds)
      }
      if (bounds.isEmpty()) continue
      const size = bounds.getSize(new THREE.Vector3())
      bounds.expandByScalar(Math.max(size.length() * 0.02, 0.3))
      const span = bounds.getSize(new THREE.Vector3()).multiplyScalar(0.16)
      for (let k = 0; k < 8; k++) {
        const a = new THREE.Vector3(k & 1 ? bounds.max.x : bounds.min.x,
          k & 2 ? bounds.max.y : bounds.min.y, k & 4 ? bounds.max.z : bounds.min.z)
        for (let axis = 0; axis < 3; axis++) {
          const b = a.clone(); b.setComponent(axis, b.getComponent(axis) + (k & (1 << axis) ? -1 : 1) * span.getComponent(axis))
          vertices.push(...a, ...b)
        }
      }
    }
    let attr = geometry.getAttribute('position')
    if (!attr || attr.array.length !== vertices.length) {
      attr = new THREE.Float32BufferAttribute(vertices, 3); attr.setUsage(THREE.DynamicDrawUsage)
      geometry.setAttribute('position', attr)
    } else {
      let first = Infinity, last = -1
      for (let i = 0; i < vertices.length; i++) if (attr.array[i] !== Math.fround(vertices[i])) {
        attr.array[i] = vertices[i]; first = Math.min(first, i); last = i
      }
      if (last >= 0) markAttributeRange(attr, first, last - first + 1)
    }
    corners.visible = vertices.length > 0
  }
  return {
    setGroups(next) {
      const sameGroups = groups.length === next.length && groups.every((g, i) =>
        g.length === next[i].length && g.every((e, j) => e.instMesh === next[i][j].instMesh && e.id === next[i][j].id))
      const nextSelected = new Map()
      for (const group of next) for (const { instMesh: mesh, id } of group) {
        if (!mesh?.isMesh || !Number.isInteger(id) || id < 0 || (mesh.isInstancedMesh && id >= mesh.count)) continue
        let ids = nextSelected.get(mesh)
        if (!ids) nextSelected.set(mesh, ids = new Set())
        ids.add(id)
      }
      for (const mesh of new Set([...selected.keys(), ...nextSelected.keys()]))
        updateSelectionTint(mesh, selected.get(mesh) ?? new Set(), nextSelected.get(mesh) ?? new Set())
      selected = nextSelected; groups = next.map(g => g.map(({ instMesh, id }) => ({ instMesh, id })))
      if (!groups.length) corners.visible = false
      refresh(!sameGroups)
    },
    clear, refresh,
    dispose() { clear(); scene.remove(corners); geometry.dispose(); material.dispose() },
  }
}
