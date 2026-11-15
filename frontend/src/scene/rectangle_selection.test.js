import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { IMPOSTOR_QUAD, makeImpostorPhongMaterial } from './impostor_material.js'
import { boundsInRect, createRectangleCollector, instanceBounds, segmentInRect } from './rectangle_selection.js'
const rect = { x1: 10, y1: 10, x2: 30, y2: 30 }
const inside = { x1: 15, y1: 15, x2: 25, y2: 25 }
const partial = { x1: 25, y1: 15, x2: 35, y2: 25 }
describe('directional rectangle selection', () => {
  it('requires full containment for windows and overlap for crossing', () => {
    expect(boundsInRect(inside, rect)).toBe(true)
    expect(boundsInRect(partial, rect)).toBe(false)
    expect(boundsInRect(partial, rect, true)).toBe(true)
    expect(boundsInRect({ x1: 0, y1: 0, x2: 40, y2: 40 }, rect, true)).toBe(true)
    expect(boundsInRect({ ...inside, clipped: true }, rect)).toBe(false)
    expect(boundsInRect(null, rect, true)).toBe(false)
  })
  it('does not select a whole strand/cluster from only a contained bead', () => {
    for (const crossing of [false, true]) {
      const c = createRectangleCollector(rect, crossing)
      c.add('strand', inside); c.add('strand', partial)
      c.add('contained', inside)
      expect(c.has('strand')).toBe(crossing)
      expect(c.keys()).toContain('contained')
    }
  })
  it('uses transformed geometry extents instead of only the centre', () => {
    const camera = new THREE.OrthographicCamera(-5, 5, 5, -5, .1, 100)
    camera.position.z = 10; camera.updateMatrixWorld()
    const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshBasicMaterial(), 1)
    mesh.position.x = 2; mesh.updateMatrixWorld()
    mesh.setMatrixAt(0, new THREE.Matrix4())
    const b = instanceBounds({ instMesh: mesh, id: 0 }, camera, { width: 100, height: 100 })
    expect(b.x1).toBeCloseTo(60); expect(b.x2).toBeCloseTo(80)
    expect(boundsInRect(b, { x1: 65, y1: 35, x2: 75, y2: 65 })).toBe(false)
    expect(boundsInRect(b, { x1: 65, y1: 35, x2: 75, y2: 65 }, true)).toBe(true)
  })
  it('captures arcs crossing the box with both endpoints outside, without diagonal false hits', () => {
    expect(segmentInRect({ x1: 0, y1: 20 }, { x1: 40, y1: 20 }, rect)).toBe(true)
    expect(segmentInRect({ x1: 0, y1: 15 }, { x1: 15, y1: 0 }, rect)).toBe(false)
  })
})


it('uses the rendered sphere radius for impostors, not the unit billboard quad', () => {
  const camera = new THREE.OrthographicCamera(-5, 5, 5, -5, .1, 100)
  camera.position.z = 10; camera.updateMatrixWorld()
  const mesh = new THREE.InstancedMesh(IMPOSTOR_QUAD, makeImpostorPhongMaterial({ radius: .1 }), 2)
  mesh.setMatrixAt(0, new THREE.Matrix4())
  mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(.8, 0, 0))
  mesh.updateMatrixWorld()
  const size = { width: 100, height: 100 }
  const selected = { x1: 48, y1: 48, x2: 52, y2: 52 }
  const inside = instanceBounds({ instMesh: mesh, id: 0 }, camera, size)
  const outside = instanceBounds({ instMesh: mesh, id: 1 }, camera, size)
  expect(boundsInRect(inside, selected)).toBe(true)
  expect(boundsInRect(outside, selected, true)).toBe(false)
  expect(inside.x1).toBeCloseTo(49)
  expect(inside.x2).toBeCloseTo(51)
})


it('keeps impostor bounds camera-facing and honors the instance fade scale', () => {
  const camera = new THREE.OrthographicCamera(-5, 5, 5, -5, .1, 100)
  camera.position.set(10,0,0); camera.lookAt(0,0,0); camera.updateMatrixWorld()
  const mesh = new THREE.InstancedMesh(IMPOSTOR_QUAD, makeImpostorPhongMaterial({ radius: .1 }), 1)
  mesh.setMatrixAt(0, new THREE.Matrix4().makeScale(.5,.5,.5))
  mesh.updateMatrixWorld()
  const bounds = instanceBounds({ instMesh:mesh,id:0 },camera,{width:100,height:100})
  expect(bounds.x1).toBeCloseTo(49.5)
  expect(bounds.x2).toBeCloseTo(50.5)
  expect(bounds.y1).toBeCloseTo(49.5)
  expect(bounds.y2).toBeCloseTo(50.5)
})
