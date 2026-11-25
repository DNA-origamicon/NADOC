import { it, expect } from 'vitest'
import * as THREE from 'three'
import { materialAvailability } from './material_availability.js'
it('considers only visible supported representations and reports dedicated shader exclusions', () => {
  const scene = new THREE.Scene(), hidden = new THREE.Group()
  hidden.visible = false; scene.add(hidden)
  const mesh = name => { const m = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial()); m.name = name; return m }
  const surface = mesh('dna-surface'); scene.add(surface)
  hidden.add(mesh('atomSpheres'))
  expect(materialAvailability(scene)).toEqual({ representations: ['surface'], unsupported: 0 })
  const full = mesh('backboneSpheres'); scene.add(full)
  expect(materialAvailability(scene).representations).toEqual(['surface', 'full'])
  full.material.userData.isImpostor = true
  expect(materialAvailability(scene)).toEqual({ representations: ['surface'], unsupported: 1 })
  scene.traverse(obj => { obj.geometry?.dispose(); obj.material?.dispose() })
})
