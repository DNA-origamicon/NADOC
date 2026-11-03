import { expect, it } from 'vitest'
import * as THREE from 'three'
import { createVRBatchEncoder } from './vr_view_batch_encoder.js'

function fixture() {
  const g = new THREE.BoxGeometry(1, 2, 3), mat = new THREE.MeshPhongMaterial({ color: 0xabcdef, opacity: .7 })
  return { g, mat, group: g.groups[0], encoder: createVRBatchEncoder() }
}
it('retains the exact original local position, normal, material and UV record order', () => {
  const { g, mat, group, encoder } = fixture(), uv = [.1, .2, .6, .9], expected = []
  for (let j = group.start; j < group.start + group.count; j++) {
    const i = g.index.getX(j), p = g.attributes.position, n = g.attributes.normal, a = g.attributes.uv
    expected.push(p.getX(i), p.getY(i), p.getZ(i), mat.color.r, mat.color.g, mat.color.b,
      mat.opacity, uv[0] + a.getX(i) * (uv[2] - uv[0]), uv[1] + (1 - a.getY(i)) * (uv[3] - uv[1]), n.getX(i), n.getY(i), n.getZ(i))
  }
  const first = encoder.vertices(g, mat, group, uv)
  expect(first).toEqual(new Float32Array(expected))
  expect(encoder.vertices(g, mat, group, uv)).toBe(first)
  g.attributes.position.setX(0, 42); g.attributes.position.needsUpdate = true
  const second = encoder.vertices(g, mat, group, uv)
  expect(second[0]).toBe(42); expect(first[0]).not.toBe(42)
})
it('invalidates colors, opacity, attributes, indices, draw range and atlas coordinates', () => {
  const { g, mat, group, encoder } = fixture()
  let uv = null, previous = encoder.vertices(g, mat, group, uv)
  for (const change of [
    () => { mat.color.setRGB(.2, .3, .4) }, () => { mat.opacity = .2 },
    () => { mat.vertexColors = true; g.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 3).fill(.5), 3)) },
    () => { g.attributes.normal = g.attributes.normal.clone() },
    () => { g.index.needsUpdate = true }, () => { g.setDrawRange(3, 3) },
    () => { uv = [0, 0, 1, 1] }, () => { uv[0] = .25 },
  ]) {
    change(); const next = encoder.vertices(g, mat, group, uv)
    expect(next).not.toBe(previous); previous = next
  }
  expect(previous.length).toBe(36)
})
it('packs exact current world matrices and colors while excluding invisible/degenerate instances', () => {
  const { g, mat, encoder } = fixture(), mesh = new THREE.InstancedMesh(g, mat, 4)
  mesh.position.set(10, 20, 30); mesh.updateMatrixWorld(true)
  for (let i = 0; i < 4; i++) mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i, i + 1, i + 2))
  g.setAttribute('instanceAlpha', new THREE.InstancedBufferAttribute(new Float32Array([1, 0, .5, 1]), 1))
  mesh.setMatrixAt(3, new THREE.Matrix4().makeScale(0, 0, 0))
  mesh.setColorAt(2, new THREE.Color(.2, .3, .4))
  const expected = [], m = new THREE.Matrix4(), c = new THREE.Color()
  for (const i of [0, 2]) {
    mesh.getMatrixAt(i, m); m.premultiply(mesh.matrixWorld).scale(new THREE.Vector3(2, 2, 2)); mesh.getColorAt(i, c)
    expected.push(...m.elements, c.r, c.g, c.b, i ? .5 : 1)
  }
  const first = encoder.instances(mesh, { radius: 2 })
  expect(first).toEqual(new Float32Array(expected))
  expect(encoder.instances(mesh,{radius:2})).toBe(first)
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(9, 9, 9))
  const next = encoder.instances(mesh, { radius: 2 })
  expect(next[12]).toBe(19); expect(first[12]).toBe(10)
})
it('invalidates interleaved attribute uploads and supports unindexed unlit templates', () => {
  const { mat, encoder } = fixture(), g = new THREE.BufferGeometry()
  const data = new THREE.InterleavedBuffer(new Float32Array([0,0,0, 1,0,0, 0,1,0]), 3)
  g.setAttribute('position', new THREE.InterleavedBufferAttribute(data, 3, 0))
  const group = {start:0,count:3}, first = encoder.vertices(g, mat, group, null)
  expect([...first.slice(7,12)]).toEqual([-1,-1,0,0,0])
  data.array[0] = 4; data.needsUpdate = true
  expect(encoder.vertices(g, mat, group, null)[0]).toBe(4)
  expect(first[0]).toBe(0)
})

it('invalidates reused instance alpha when its interpretation changes',()=>{
 const {g,mat,encoder}=fixture(),mesh=new THREE.InstancedMesh(g,mat,1)
 mesh.setMatrixAt(0,new THREE.Matrix4());mesh.updateMatrixWorld(true)
 const alpha=new THREE.InstancedBufferAttribute(new Uint8Array([128]),1,false)
 g.setAttribute('instanceAlpha',alpha)
 expect(encoder.instances(mesh)[19]).toBe(128)
 alpha.normalized=true
 expect(encoder.instances(mesh)[19]).toBeCloseTo(128/255)
})
