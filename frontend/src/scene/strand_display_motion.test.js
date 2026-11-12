import { expect, it } from 'vitest'
import * as THREE from 'three'
import { bindStrandDisplayMotion } from './strand_display_motion.js'

function entry(bp, copy = 0) {
  const instMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 1)
  const connectorMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 1)
  instMesh.setColorAt(0, new THREE.Color('red'))
  return { instMesh, id: 0, connectorMesh, connectorId: 0,
    nuc: { helix_id: 'h', bp_index: bp, direction: 'FORWARD' }, _copy: copy, pos: new THREE.Vector3() }
}
const translated = x => new THREE.Matrix4().makeRotationZ(.7).setPosition(x,2,3)
function fixture() {
  const a = entry(0), loop = entry(0, 1), b = entry(0), loopB = entry(0, 1)
  const root = new THREE.Group(), scene = new THREE.Scene()
  scene.add(root)
  root.add(b.instMesh, b.connectorMesh, loopB.instMesh)
  const source = { cg: { backboneEntries: [a, loop] } }
  const display = { root, cg: { backboneEntries: [loopB, b] } }
  return { a, loop, b, loopB, source, display, scene }
}
it('copies exact live instance transforms, insertion identities and rods without copying colors', () => {
  const f = fixture()
  f.a.instMesh.setColorAt(0, new THREE.Color('blue'))
  f.a.instMesh.setMatrixAt(0, translated(8)); f.loop.instMesh.setMatrixAt(0, translated(9))
  f.a.connectorMesh.setMatrixAt(0, translated(10)); f.a.pos.set(8,2,3)
  const binding = bindStrandDisplayMotion(f.display, () => f.source, f.scene)
  const actual = new THREE.Matrix4(), expected = new THREE.Matrix4(), color = new THREE.Color()
  for (const [origin, target] of [[f.a, f.b], [f.loop, f.loopB]]) {
    origin.instMesh.getMatrixAt(0, expected); target.instMesh.getMatrixAt(0, actual)
    expect(actual.elements).toEqual(expected.elements)
  }
  f.b.connectorMesh.getMatrixAt(0, actual); f.a.connectorMesh.getMatrixAt(0, expected)
  expect(actual.elements).toEqual(expected.elements)
  expect(f.b.pos.toArray()).toEqual([8,2,3])
  f.b.instMesh.getColorAt(0, color); expect(color.getHex()).toBe(0xff0000)
  // Motion and restoration follow the live buffer, with no additive drift.
  for (const x of [20, 0]) {
    f.a.instMesh.setMatrixAt(0, translated(x)); binding.sync()
    f.b.instMesh.getMatrixAt(0, actual); f.a.instMesh.getMatrixAt(0, expected)
    expect(actual.elements).toEqual(expected.elements)
  }
  binding.dispose()
})
it('rebinds after a native rebuild before scene buffer uploads and restores hooks', () => {
  const f = fixture(), previous = f.scene.onBeforeRender
  const binding = bindStrandDisplayMotion(f.display, () => f.source, f.scene)
  const replacement = entry(0); replacement.instMesh.setMatrixAt(0, translated(30))
  f.source.cg = { backboneEntries: [replacement] }
  const renderer = { info: { render: { frame: 1 } } }, matrix = new THREE.Matrix4()
  f.scene.onBeforeRender(renderer)
  f.b.instMesh.getMatrixAt(0, matrix); expect(matrix.elements[12]).toBe(30)
  replacement.instMesh.setMatrixAt(0, translated(40))
  f.scene.onBeforeRender(renderer)
  f.b.instMesh.getMatrixAt(0, matrix); expect(matrix.elements[12]).toBe(40)
  renderer.info.render.frame++
  f.scene.onBeforeRender(renderer)
  f.b.instMesh.getMatrixAt(0, matrix); expect(matrix.elements[12]).toBe(40)
  binding.dispose(); expect(f.scene.onBeforeRender).toBe(previous)
})

it('follows crossover beads, slabs and both connector families by crossover identity', () => {
  const f = fixture()
  const extras = (beadStartIdx, connStartIdx) => {
    const result = { arcData: [{ xoId: 'x', beadCount: 1, beadStartIdx, connStartIdx }] }
    for (const name of ['beadsMesh', 'slabsMesh', 'slabConnMesh', 'connMesh']) {
      result[name] = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 6)
    }
    return result
  }
  f.source.extras = extras(2, 3); f.display.extras = extras(0, 0)
  for (const name of ['beadsMesh', 'slabsMesh', 'slabConnMesh', 'connMesh']) {
    for (let i = 0; i < 6; i++) f.source.extras[name].setMatrixAt(i, translated(i + 10))
  }
  const binding = bindStrandDisplayMotion(f.display, () => f.source, f.scene)
  const matrix = new THREE.Matrix4()
  for (const name of ['beadsMesh', 'slabsMesh', 'slabConnMesh', 'connMesh']) {
    f.display.extras[name].getMatrixAt(0, matrix)
    expect(matrix.elements[12]).toBe(name === 'connMesh' ? 13 : 12)
  }
  f.display.extras.connMesh.getMatrixAt(1, matrix); expect(matrix.elements[12]).toBe(14)
  binding.dispose()
})
