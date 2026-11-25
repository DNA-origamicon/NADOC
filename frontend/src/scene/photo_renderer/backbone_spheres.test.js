import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { makeImpostorPhongMaterial, IMPOSTOR_QUAD } from '../impostor_material.js'
import { swapToFlatMaterials } from '../photo_mode.js'
import { photoBackboneRadius, makePhotoBackboneGeometry } from './backbone_spheres.js'
import { materialAvailability } from './material_availability.js'

it('uses real photo spheres at the original radius, preserving transforms/colors and restoring both resources', () => {
  const scene = new THREE.Scene()
  const mat = makeImpostorPhongMaterial({ radius: .15 })
  const mesh = new THREE.InstancedMesh(IMPOSTOR_QUAD, mat, 2)
  mesh.name = 'backboneSpheres'
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(3, 4, 5))
  mesh.setColorAt(0, new THREE.Color('red'))
  const matrix = mesh.instanceMatrix.array.slice(), colors = mesh.instanceColor.array.slice()
  const reinstall = vi.fn()
  mesh.userData.sharedInstanced = true
  mesh.userData.applySharedInstancing = reinstall
  scene.add(mesh)
  expect(materialAvailability(scene)).toEqual({ representations: ['full'], unsupported: 0 })
  const swap = swapToFlatMaterials(scene)
  const geo = mesh.geometry, dispose = vi.spyOn(geo, 'dispose')
  expect(geo.type).toBe('SphereGeometry')
  expect(geo.parameters.radius).toBe(.15)
  expect(mesh.material.isMeshPhysicalMaterial).toBe(true)
  expect(mesh.material.side).toBe(THREE.FrontSide)
  expect(mesh.material.userData.isImpostor).toBeUndefined()
  expect(reinstall).toHaveBeenCalledWith(mesh.material)
  expect(mesh.instanceMatrix.array).toEqual(matrix)
  expect(mesh.instanceColor.array).toEqual(colors)
  swap.restore()
  expect(mesh.geometry).toBe(IMPOSTOR_QUAD)
  expect(mesh.material).toBe(mat)
  expect(dispose).toHaveBeenCalledTimes(1)
  swap.restore()
  expect(dispose).toHaveBeenCalledTimes(1)
  mat.dispose()
})

it('refuses unknown/atomistic shader contracts and invalid radii', () => {
  const mesh = new THREE.Mesh(IMPOSTOR_QUAD, makeImpostorPhongMaterial({ radius: .15 }))
  mesh.name = 'atomSpheres'
  expect(makePhotoBackboneGeometry(mesh)).toBeNull()
  mesh.name = 'backboneSpheres'
  mesh.userData.sharedInstanced = true
  expect(photoBackboneRadius(mesh)).toBeNull()
  mesh.userData.sharedInstanced = false
  mesh.material.userData.impostorRadius = NaN
  expect(photoBackboneRadius(mesh)).toBeNull()
  mesh.material.dispose()
})
