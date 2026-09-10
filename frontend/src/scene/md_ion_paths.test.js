import { it, expect } from 'vitest'
import * as THREE from 'three'
import { initMdIonPaths } from './md_ion_paths.js'
it('batches paths by species, updates real wide lines, and leaves shared renderer visibility to its owner', () => {
  const scene = new THREE.Scene(), design = new THREE.Group(), hidden = new THREE.Group()
  hidden.visible = false; scene.add(design, hidden)
  const overlay = initMdIonPaths(scene)
  overlay.setData({ paths: [{ species: 'NA', positions: [0, -1, 0, 0, 1, 0] }, { species: 'NA', positions: [1, -1, 0, 1, 1, 0] }], pore: { radius_nm: 4, normal: [0, 1, 0] } })
  const group = scene.getObjectByName('mdIonPaths')
  expect(group.children.length).toBe(2)
  expect(design.visible).toBe(true)
  overlay.setWidth(7)
  expect(group.children[0].material.linewidth).toBe(7)
  expect(group.children[0].geometry.attributes.instanceStart.count).toBe(2)
  overlay.clear()
  expect(design.visible).toBe(true)
  expect(hidden.visible).toBe(false)
  expect(group.children.length).toBe(0)
})

it('shows stable complete-path subsets without rebuilding the origami or nanopore', () => {
  const scene = new THREE.Scene(), overlay = initMdIonPaths(scene)
  const paths = Array.from({ length: 10 }, (_, i) => ({ ion_serial: i + 1, crossing_frame: 20 + i,
    species: i % 2 ? 'NA' : 'CL', positions: [i, -1, 0, i, 0, 0, i, 1, 0] }))
  const graphene = Array.from({ length: 6 }, (_, i) => [Math.cos(i * Math.PI / 3) * 0.142, Math.sin(i * Math.PI / 3) * 0.142, 0]).flat()
  overlay.setData({ paths, origami: { positions: [0, 2, 0, 0.5, 2, 0], backbone_edges: [[0, 1]] }, graphene,
    pore: { radius_nm: 4, normal: [0, 1, 0] } })
  const group = scene.getObjectByName('mdIonPaths')
  const average = new THREE.Group(); average.name = 'sharedRmsfAverage'; scene.add(average)
  const membrane = group.getObjectByName('Graphene nanopore')
  const lines = group.children.filter(c => c.isLineSegments2)
  const geometries = lines.map(c => c.geometry)
  expect(group.getObjectByName('origamiRmsfAverage')).toBeUndefined()
  expect(membrane.geometry.index.count).toBeGreaterThan(0)
  const count = () => lines.reduce((sum, c) => sum + c.geometry.instanceCount, 0)
  expect(count()).toBe(20)
  expect(overlay.setPercentage(30)).toEqual({ shown: 3, total: 10, percentage: 30 })
  expect(count()).toBe(6) // three entire paths, each with two segments
  const subset = lines.map(c => c.geometry.instanceCount)
  overlay.setPercentage(70)
  lines.forEach((c, i) => expect(c.geometry.instanceCount).toBeGreaterThanOrEqual(subset[i]))
  overlay.setPercentage(30)
  expect(lines.map(c => c.geometry.instanceCount)).toEqual(subset)
  overlay.setPercentage(0)
  expect(count()).toBe(0)
  expect(average.visible).toBe(true)
  expect(membrane.visible).toBe(true)
  expect(lines.map(c => c.geometry)).toEqual(geometries)
  overlay.setData({ paths, graphene, pore: { radius_nm: 4, normal: [0, 1, 0] } })
  expect(group.children.filter(c => c.isLineSegments2).every(c => !c.visible)).toBe(true)
  overlay.dispose()
  expect(scene.getObjectByName('mdIonPaths')).toBeUndefined()
})

it('coalesces overlapping large windows but keeps distinct periodic images', () => {
  const scene = new THREE.Scene(), overlay = initMdIonPaths(scene)
  const track = new Float32Array(301 * 3)
  for (let i = 0; i < 301; i++) track[i * 3] = i * 0.01
  const paths = [
    { ion_serial: 1, crossing_frame: 30, species: 'NA', track: 0, point_start: 0, point_count: 201, offset: [0, 0, 0] },
    { ion_serial: 1, crossing_frame: 50, species: 'NA', track: 0, point_start: 100, point_count: 201, offset: [0, 0, 0] },
  ]
  overlay.setData({ paths, tracks: [track], pore: { radius_nm: 1, normal: [0, 1, 0] } })
  const lines = scene.getObjectByName('ionPaths-NA')
  expect(lines.geometry.instanceCount).toBe(300) // 400 segments with 100 overlapping
  overlay.setPercentage(50)
  expect(lines.geometry.instanceCount).toBe(200) // one complete window
  overlay.setPercentage(100)
  expect(lines.geometry.instanceCount).toBe(300)
  paths[1] = { ...paths[1], offset: [10, 0, 0] }
  overlay.setData({ paths, tracks: [track], pore: { radius_nm: 1, normal: [0, 1, 0] } })
  expect(scene.getObjectByName('ionPaths-NA').geometry.instanceCount).toBe(400)
  expect(() => overlay.setData(null)).toThrow('Invalid ion-path data')
  expect(scene.getObjectByName('ionPaths-NA').geometry.instanceCount).toBe(400)
  overlay.dispose()
})

it('uses the supplied alignment matrix for paths and every graphene representation', () => {
  const scene = new THREE.Scene(), overlay = initMdIonPaths(scene)
  const matrix = new THREE.Matrix4().makeRotationZ(Math.PI / 2).setPosition(3, 8, -2)
  overlay.setData({ paths: [], pore: { radius_nm: 1, normal: [0, 1, 0] }, origami: { display_transform: matrix.toArray() } })
  const group = scene.getObjectByName('mdIonPaths')
  expect(group.matrix.equals(matrix)).toBe(true)
  expect(group.localToWorld(new THREE.Vector3(0, 2, 0)).toArray()).toEqual([1, 8, -2])
  overlay.dispose()
})
