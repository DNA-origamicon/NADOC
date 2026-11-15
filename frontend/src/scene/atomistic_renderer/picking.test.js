import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initAtomisticRenderer } from '../atomistic_renderer.js'
import { installInstanceAlphaGeometry } from '../instance_alpha.js'

function setup(mode, sphereImpostors = false) {
  const scene = new THREE.Scene()
  const ar = initAtomisticRenderer(scene)
  ar.setMode(mode)
  ar.update({ sphereImpostors, atoms: [
    { serial: 10, element: 'C', strand_id: 'a', x: 0, y: 0, z: 0 },
    { serial: 20, element: 'O', strand_id: 'b', x: 0.4, y: 0, z: 0 },
  ], bonds: [[10, 20]] })
  const pick = (x, y = 0) => ar.raycastPick(new THREE.Raycaster(
    new THREE.Vector3(x, y, 2), new THREE.Vector3(0, 0, -1)))
  return { ar, scene, pick }
}

describe('displayed atomistic picking', () => {
  it.each([false, true])('picks balls and bond interiors (impostors=%s)', impostors => {
    const { ar, pick } = setup('ballstick', impostors)
    expect(pick(0, 0.04)?.atom.serial).toBe(10)
    expect(pick(0.15)?.atom.serial).toBe(10)
    expect(pick(0.25)?.atom.serial).toBe(20)
    expect(pick(0.2, 0.08)).toBeNull()
    ar.dispose()
  })
  it('picks only cylinders in Stick and only spheres in VDW', () => {
    const { ar, pick } = setup('stick')
    expect(pick(0.15)?.atom.serial).toBe(10)
    expect(pick(0, 0.06)).toBeNull()
    ar.setMode('vdw')
    expect(pick(0.2)).toBeNull()
    expect(pick(0, 0.1)?.atom.serial).toBe(10)
    ar.setMode('off')
    expect(pick(0)).toBeNull()
    ar.dispose()
  })
  it('honors hidden parents and hidden bond instances', () => {
    const { ar, scene, pick } = setup('stick')
    scene.visible = false
    expect(pick(0.15)).toBeNull()
    scene.visible = true
    const bond = scene.children.find(m => m.name === 'atomBonds')
    installInstanceAlphaGeometry(bond)
    bond.geometry.getAttribute('instanceAlpha').setX(0, 0)
    expect(pick(0.15)).toBeNull()
    ar.dispose()
  })
  it('rejects clipped bond fragments', () => {
    const { ar, scene, pick } = setup('stick')
    const bond = scene.children.find(m => m.name === 'atomBonds')
    bond.material.clippingPlanes = [new THREE.Plane(new THREE.Vector3(1, 0, 0), -0.2)]
    expect(pick(0.15)).toBeNull()
    expect(pick(0.25)?.atom.serial).toBe(20)
    ar.dispose()
  })
  it('uses current world transforms and refreshes moved instance bounds', () => {
    const { ar, scene, pick } = setup('stick')
    expect(pick(0.15)?.atom.serial).toBe(10)
    scene.position.x = 3
    expect(pick(3.25)?.atom.serial).toBe(20)
    const bond = scene.children.find(m => m.name === 'atomBonds')
    const matrix = new THREE.Matrix4()
    bond.getMatrixAt(0, matrix)
    matrix.elements[12] += 5
    bond.setMatrixAt(0, matrix)
    bond.instanceMatrix.needsUpdate = true
    expect(pick(3.25)).toBeNull()
    expect(pick(8.25)?.atom.serial).toBe(20)
    ar.dispose()
  })
})
