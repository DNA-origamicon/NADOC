import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { createClusterSelection, installSelectionTint, selectionBaseCompiler } from './selection_tint.js'
import { installInstanceAlpha, applyInstanceAlphaMaterial } from './instance_alpha.js'
import { makeImpostorPhongMaterial, preparedImpostorSpec } from './impostor_material.js'

const shader = () => ({ uniforms: {}, vertexShader: '#include <common>\n#include <begin_vertex>\n#include <project_vertex>', fragmentShader: '#include <common>\n#include <color_fragment>\n#include <opaque_fragment>' })
function mesh() {
  const m = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial(), 2)
  m.setMatrixAt(0, new THREE.Matrix4()); m.setMatrixAt(1, new THREE.Matrix4().makeTranslation(10, 0, 0))
  m.setColorAt(0, new THREE.Color(0xff0000)); m.setColorAt(1, new THREE.Color(0x0000ff))
  return m
}

describe('cluster selection tint', () => {
  it('preserves colors, alpha pointers and matrices, clears only its own channel', () => {
    const scene = new THREE.Scene(), m = mesh(); scene.add(m)
    installInstanceAlpha(m)
    const alpha = m._instanceAlpha, matrices = [...m.instanceMatrix.array], colors = [...m.instanceColor.array]
    const layer = createClusterSelection(scene)
    layer.setGroups([[{ instMesh: m, id: 0 }]])
    expect(m.geometry.getAttribute('instanceSelection').array).toEqual(new Float32Array([1, 0]))
    expect(m.geometry.getAttribute('instanceAlpha')).toBe(alpha)
    expect([...m.instanceMatrix.array]).toEqual(matrices)
    expect([...m.instanceColor.array]).toEqual(colors)
    alpha.setX(0, 0.3)
    m.setColorAt(0, new THREE.Color(0x123456))
    layer.clear()
    expect(m.geometry.getAttribute('instanceSelection').getX(0)).toBe(0)
    expect(alpha.getX(0)).toBeCloseTo(0.3)
    expect(new THREE.Color().fromArray(m.instanceColor.array).getHex()).toBe(0x123456)
    layer.dispose(); expect(scene.getObjectByName('clusterSelectionCorners')).toBeUndefined()
  })
  it('composes alpha installed before or after selection, without changing transparency itself', () => {
    for (const first of [true, false]) {
      const m = mesh()
      if (first) installInstanceAlpha(m)
      installSelectionTint(m)
      if (!first) { expect(m.material.transparent).toBe(false); applyInstanceAlphaMaterial(m.material) }
      const s = shader(); m.material.onBeforeCompile(s)
      expect(s.vertexShader.match(/attribute float instanceSelection;/g)).toHaveLength(1)
      expect(s.fragmentShader).toContain('diffuseColor.a *= vInstanceAlpha')
      expect(s.fragmentShader).toContain('outgoingLight = mix')
    }
  })
  it('keeps the trusted sphere-impostor compiler and rejects an unrelated replacement', () => {
    const m = mesh(); m.material = makeImpostorPhongMaterial({ radius: 0.2 })
    installSelectionTint(m)
    expect(preparedImpostorSpec(m.material)?.radius).toBe(0.2)
    const s = shader(); m.material.onBeforeCompile(s)
    expect(s.vertexShader).toContain('vSelection = instanceSelection')
    expect(s.vertexShader).toContain('v_impR')
    const other = mesh(); installSelectionTint(other)
    expect(selectionBaseCompiler(other.material)).toBe(THREE.Material.prototype.onBeforeCompile)
    const unknown = () => {}; other.material.onBeforeCompile = unknown
    expect(selectionBaseCompiler(other.material)).toBe(unknown)
  })
  it('tints curved non-instanced tubes without replacing their color or transform', () => {
    const scene = new THREE.Scene()
    const m = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 10), new THREE.MeshLambertMaterial({ color: 0x123456 }))
    scene.add(m)
    const layer = createClusterSelection(scene)
    layer.setGroups([[{ instMesh: m, id: 0 }]])
    expect([...m.geometry.getAttribute('instanceSelection').array].every(x => x === 1)).toBe(true)
    expect(m.material.color.getHex()).toBe(0x123456)
    layer.clear()
    expect([...m.geometry.getAttribute('instanceSelection').array].every(x => x === 0)).toBe(true)
    expect(m.material.color.getHex()).toBe(0x123456)
    layer.dispose()
  })
  it('keeps separate cluster bounds and follows changed instance positions', () => {
    const scene = new THREE.Scene(), m = mesh(); scene.add(m)
    const layer = createClusterSelection(scene)
    layer.setGroups([[{ instMesh: m, id: 0 }], [{ instMesh: m, id: 1 }]])
    const corners = scene.getObjectByName('clusterSelectionCorners')
    expect(corners.geometry.attributes.position.count).toBe(96)
    const before = corners.geometry.attributes.position.getX(0)
    m.setMatrixAt(0, new THREE.Matrix4().makeTranslation(2, 0, 0)); m.instanceMatrix.needsUpdate = true
    layer.refresh()
    expect(corners.geometry.attributes.position.getX(0) - before).toBeCloseTo(2)
    layer.clear(); expect(corners.visible).toBe(false)
  })
})

it('does not upload or rebuild unchanged selection and limits changed tint ranges', () => {
  const scene = new THREE.Scene(), m = mesh(); scene.add(m)
  const layer = createClusterSelection(scene), groups = [[{ instMesh: m, id: 0 }]]
  layer.setGroups(groups)
  const attr = m.geometry.attributes.instanceSelection, corners = scene.getObjectByName('clusterSelectionCorners')
  const position = corners.geometry.attributes.position, version = attr.version
  attr.clearUpdateRanges()
  layer.setGroups([[{ instMesh: m, id: 0 }]])
  expect(attr.version).toBe(version)
  expect(corners.geometry.attributes.position).toBe(position)
  layer.setGroups([[{ instMesh: m, id: 0 }, { instMesh: m, id: 1 }]])
  expect(attr.updateRanges).toEqual([{ start: 1, count: 1 }])
  expect([...attr.array]).toEqual([1, 1])
  layer.clear() // pending edits must stay included until the renderer consumes them
  expect(attr.updateRanges).toEqual([{ start: 0, count: 2 }])
  layer.dispose()
})
it('invalidates corner bounds for parent transforms, visibility and edited geometry', () => {
  const scene = new THREE.Scene(), parent = new THREE.Group(), m = mesh(); scene.add(parent); parent.add(m)
  const layer = createClusterSelection(scene); layer.setGroups([[{ instMesh: m, id: 0 }]])
  const corners = scene.getObjectByName('clusterSelectionCorners'), before = corners.geometry.attributes.position.getX(0)
  parent.position.x = 3; layer.refresh()
  expect(corners.geometry.attributes.position.getX(0) - before).toBeCloseTo(3)
  parent.visible = false; layer.refresh(); expect(corners.visible).toBe(false)
  parent.visible = true; layer.refresh(); expect(corners.visible).toBe(true)
  const position = m.geometry.attributes.position
  for (let i = 0; i < position.count; i++) position.setX(i, position.getX(i) + 4)
  position.needsUpdate = true; layer.refresh()
  expect(corners.geometry.attributes.position.getX(0) - before).toBeCloseTo(7)
  layer.dispose()
})
