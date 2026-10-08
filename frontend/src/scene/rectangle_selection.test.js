import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
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
