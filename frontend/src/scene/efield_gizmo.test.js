import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import * as THREE from 'three'
import { initEfieldGizmo } from './efield_gizmo.js'

describe('initEfieldGizmo', () => {
  let scene, camera, canvas, controls, gizmo

  beforeEach(() => {
    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1000)
    camera.position.set(0, 0, 30)
    canvas = document.createElement('canvas')
    controls = { enabled: true }
    gizmo = initEfieldGizmo(scene, camera, canvas, controls)
  })
  afterEach(() => { gizmo?.dispose() })

  it('attach adds a named, visible group to the scene', () => {
    expect(gizmo.isActive()).toBe(false)
    gizmo.attach([0, 0, 0])
    expect(gizmo.isActive()).toBe(true)
    const g = scene.getObjectByName('efield-gizmo')
    expect(g).toBeTruthy()
    expect(g.visible).toBe(true)
    expect(g.getObjectByName('efield-gizmo-handle')).toBeTruthy()
  })

  it('setVector / getVector round-trip', () => {
    gizmo.attach([0, 0, 0])
    gizmo.setVector([1, 2, 3])
    const v = gizmo.getVector()
    expect(v[0]).toBeCloseTo(1)
    expect(v[1]).toBeCloseTo(2)
    expect(v[2]).toBeCloseTo(3)
  })

  it('handle sits at origin + direction*length', () => {
    gizmo.attach([0, 0, 0])
    gizmo.setVector([0, 6, 0])
    const handle = scene.getObjectByName('efield-gizmo-handle')
    expect(handle.position.x).toBeCloseTo(0)
    expect(handle.position.y).toBeCloseTo(6)
    expect(handle.position.z).toBeCloseTo(0)
  })

  it('attach at a non-zero origin offsets the handle', () => {
    gizmo.attach([5, 0, 0])
    gizmo.setVector([0, 0, 4])
    const handle = scene.getObjectByName('efield-gizmo-handle')
    expect(handle.position.x).toBeCloseTo(5)
    expect(handle.position.z).toBeCloseTo(4)
  })

  it('detach hides the group and re-enables controls', () => {
    gizmo.attach([0, 0, 0])
    controls.enabled = false
    gizmo.detach()
    expect(gizmo.isActive()).toBe(false)
    expect(scene.getObjectByName('efield-gizmo').visible).toBe(false)
    expect(controls.enabled).toBe(true)
  })

  it('re-attach reuses the same group (no duplicate)', () => {
    gizmo.attach([0, 0, 0])
    gizmo.detach()
    gizmo.attach([0, 0, 0])
    const groups = []
    scene.traverse(o => { if (o.name === 'efield-gizmo') groups.push(o) })
    expect(groups).toHaveLength(1)
  })
})
