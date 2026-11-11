import { expect, it } from 'vitest'
import * as THREE from 'three'
import { copyZoomBox, entriesInZoomBox, zoomBoxBounds } from './zoom_volume_box.js'

it('copies only the inner box and preserves its orientation without sharing arrays', () => {
  const source = { min_corner: [9,-2,-1], max_corner: [11,2,1], rotation: [0,0,Math.SQRT1_2,Math.SQRT1_2], shell_nm: 3 }
  const box = copyZoomBox(source)
  expect(box.shell_nm).toBeUndefined()
  source.min_corner[0] = 0
  expect(box.min_corner[0]).toBe(9)
  const inside = { pos: new THREE.Vector3(11.5,0,0) }, outside = { pos: new THREE.Vector3(10,1.5,0) }
  expect(entriesInZoomBox([inside,outside], box)).toEqual([inside])
  const bounds = zoomBoxBounds(box)
  expect(bounds.min.x).toBeCloseTo(8); expect(bounds.max.x).toBeCloseTo(12)
  expect(bounds.min.y).toBeCloseTo(-1); expect(bounds.max.y).toBeCloseTo(1)
})

it('filters in world space, including transformed assembly instances', () => {
  const box = copyZoomBox({ min_corner: [9,-2,-1], max_corner: [11,2,1] })
  const a = { pos: new THREE.Vector3(0,0,0) }, b = { pos: new THREE.Vector3(4,0,0) }
  expect(entriesInZoomBox([a,b], box, new THREE.Matrix4().makeTranslation(10,0,0))).toEqual([a])
  expect(a.pos.toArray()).toEqual([0,0,0])
  expect(copyZoomBox(null)).toBeNull()
  expect(copyZoomBox({ min_corner: [0,0,0], max_corner: [0,1,1] })).toBeNull()
})
