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
    expect(scene.getObjectByName('efield-gizmo-rotation-controls')).toBeTruthy()
    expect(scene.getObjectByName('efield-gizmo-rotation-target')).toBeTruthy()
  })

  it('setVector preserves direction and exposes a unit direction', () => {
    gizmo.attach([0, 0, 0])
    gizmo.setVector([1, 2, 3])
    const v = gizmo.getVector()
    const n = Math.sqrt(14)
    expect(v[0]).toBeCloseTo(1 / n)
    expect(v[1]).toBeCloseTo(2 / n)
    expect(v[2]).toBeCloseTo(3 / n)
  })

  it('direction rotates the TransformControls target like the cluster tool', () => {
    gizmo.attach([0, 0, 0])
    gizmo.setVector([0, 6, 0])
    const target = scene.getObjectByName('efield-gizmo-rotation-target')
    expect(target.quaternion.x).toBeCloseTo(0)
    expect(target.quaternion.y).toBeCloseTo(0)
    expect(target.quaternion.z).toBeCloseTo(0)
    expect(target.quaternion.w).toBeCloseTo(1)
  })

  it('attach at a non-zero origin offsets the cluster-style rotation target', () => {
    gizmo.attach([5, 0, 0])
    gizmo.setVector([0, 0, 4])
    const target = scene.getObjectByName('efield-gizmo-rotation-target')
    expect(target.position.x).toBeCloseTo(5)
    expect(target.position.z).toBeCloseTo(0)
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

  it('caps the magnitude-driven arrow at 25 nm', () => {
    gizmo.attach([0, 0, 0])
    gizmo.setArrowLength(100)
    const shaft = scene.getObjectByName('efield-gizmo-arrow-shaft')
    // 25 nm total minus the capped 4 nm arrow head.
    expect(shaft.scale.y).toBeCloseTo(21)
  })

  it('caps far-zoom rotation circles at 25 nm diameter', () => {
    camera.position.set(0, 0, 900)
    gizmo.attach([0, 0, 0])
    const helper = scene.getObjectByName('efield-gizmo-rotation-controls')
    helper.updateMatrixWorld(true)

    const ringScales = []
    helper.traverse(o => {
      if (o.name === 'X' || o.name === 'Y' || o.name === 'Z' || o.name === 'E') {
        ringScales.push(o.scale.x)
      }
    })
    expect(ringScales.length).toBeGreaterThan(0)
    // Unit-radius ring geometry: scale 12.5 gives a 25 nm diameter.
    expect(Math.max(...ringScales)).toBeLessThanOrEqual(12.5 + 1e-6)
  })

  it('can hide rotation controls while leaving the field arrow visible', () => {
    gizmo.attach([0, 0, 0])
    const helper = scene.getObjectByName('efield-gizmo-rotation-controls')
    gizmo.setControlsVisible(false)
    expect(helper.visible).toBe(false)
    expect(scene.getObjectByName('efield-gizmo').visible).toBe(true)
    gizmo.setControlsVisible(true)
    expect(helper.visible).toBe(true)
  })
})
