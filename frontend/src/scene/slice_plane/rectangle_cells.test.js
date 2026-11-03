import { it, expect } from 'vitest'
import * as THREE from 'three'
import { rectangleCells } from './rectangle_cells.js'

const camera = new THREE.OrthographicCamera(-5, 5, 5, -5, .1, 100)
camera.position.z = 10
camera.updateMatrixWorld()
const viewport = { left: 100, top: 50, width: 100, height: 100 }
const cell = (state = 'free') => ({ state, fill: new THREE.Mesh(new THREE.CircleGeometry(1, 32)) })
const select = (cells, start, end) => rectangleCells(cells, camera, viewport, start, end)
it('requires full extents rightward and includes touching extents leftward', () => {
  const c = cell()
  expect(select([c], { x: 145, y: 95 }, { x: 155, y: 105 })).toEqual([])
  expect(select([c], { x: 139, y: 89 }, { x: 161, y: 111 })).toEqual([c])
  expect(select([c], { x: 165, y: 95 }, { x: 155, y: 105 })).toEqual([c])
  expect(select([c], { x: 175, y: 95 }, { x: 165, y: 105 })).toEqual([])
})
it('skips occupied cells and preserves grid order for free and continuation cells', () => {
  const cells = [cell(), cell('occupied'), cell('continuable')]
  expect(select(cells, { x: 100, y: 50 }, { x: 200, y: 150 })).toEqual([cells[0], cells[2]])
})
it('uses parent transforms and excludes geometry behind the camera', () => {
  const c = cell(), parent = new THREE.Group()
  parent.add(c.fill)
  parent.position.x = 3
  expect(select([c], { x: 139, y: 89 }, { x: 161, y: 111 })).toEqual([])
  expect(select([c], { x: 169, y: 89 }, { x: 191, y: 111 })).toEqual([c])
  parent.position.z = 20
  expect(select([c], { x: 100, y: 50 }, { x: 200, y: 150 })).toEqual([])
})
