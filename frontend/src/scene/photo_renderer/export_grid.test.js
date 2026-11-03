import { expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { prepareExportGrids } from './export_grid.js'

it('scales visible grids, preserves surface placement and restores the live scene', () => {
  const scene = new THREE.Scene(), group = new THREE.Group()
  const grid = new THREE.GridHelper(100, 10), hidden = new THREE.GridHelper()
  hidden.visible = false
  scene.add(group, hidden); group.add(grid)
  grid.position.set(2, 3, 4); grid.rotation.x = Math.PI / 2
  const restore = prepareExportGrids(scene, 4)
  const proxy = group.getObjectByName('photoExportGrid')
  expect(proxy.material.linewidth).toBe(4)
  expect(proxy.matrix.equals(grid.matrix)).toBe(true)
  expect(proxy.userData.noAO).toBe(true)
  expect(grid.visible).toBe(false)
  expect(scene.children).toHaveLength(2)
  const dispose = vi.spyOn(proxy.geometry, 'dispose')
  restore()
  expect(grid.visible).toBe(true)
  expect(hidden.visible).toBe(false)
  expect(proxy.parent).toBeNull()
  expect(dispose).toHaveBeenCalledOnce()
})
