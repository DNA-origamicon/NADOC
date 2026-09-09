// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initSectionView, isSectionContent, sectionStencilMaterial } from './section_view.js'

describe('section view', () => {
  it('excludes tools and includes instanced solids', () => {
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(), new THREE.MeshPhongMaterial(), 2)
    expect(isSectionContent(mesh)).toBe(true)
    const group = new THREE.Group()
    group.userData.helper = true
    group.add(mesh)
    expect(isSectionContent(mesh)).toBe(false)
  })
  it('excludes invisible picking and depth-only materials', () => {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0 }))
    expect(isSectionContent(mesh)).toBe(false)
    mesh.material.opacity = 1
    expect(isSectionContent(mesh)).toBe(true)
    mesh.material.colorWrite = false
    expect(isSectionContent(mesh)).toBe(false)
  })
  it('preserves custom instance shaders in winding passes', () => {
    const source = new THREE.MeshPhongMaterial()
    source.onBeforeCompile = () => {}
    const plane = new THREE.Plane()
    const material = sectionStencilMaterial(source, plane, THREE.BackSide)
    expect(material.onBeforeCompile).toBe(source.onBeforeCompile)
    expect(material.stencilZPass).toBe(THREE.IncrementWrapStencilOp)
    expect(material.clippingPlanes).toEqual([plane])
    expect(material.colorWrite).toBe(false)
  })
  it('tracks replaced representations and restores exact clipping and navigation state', () => {
    document.body.innerHTML = '<div id="right-view-actions"><div class="ox-card__body"></div></div><canvas></canvas>'
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
    camera.position.z = 5
    const renderer = { domElement: document.querySelector('canvas'), localClippingEnabled: false }
    const controls = { target: new THREE.Vector3(), enabled: false }
    const original = [new THREE.Plane(new THREE.Vector3(1, 0, 0), 4)]
    const material = new THREE.MeshPhongMaterial({ clippingPlanes: original })
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(), material)
    scene.add(sphere)
    const callbacks = new Set()
    const view = initSectionView({ scene, camera, renderer, controls, document,
      getPartCentroid: () => new THREE.Vector3(10, -3, 7),
      addFrameCallback: fn => callbacks.add(fn), removeFrameCallback: fn => callbacks.delete(fn) })
    view.setEnabled(true)
    expect(material.clippingPlanes).toHaveLength(2)
    expect(view.plane.distanceToPoint(new THREE.Vector3())).toBeCloseTo(0)
    view.anchor.position.z = 0.5
    view.sync()
    expect(view.plane.distanceToPoint(new THREE.Vector3(0, 0, 0.5))).toBeCloseTo(0)
    const replacement = new THREE.MeshBasicMaterial()
    sphere.material = replacement
    view.sync()
    expect(replacement.clippingPlanes).toContain(view.plane)
    document.getElementById('section-reset-btn').click()
    expect(view.anchor.position.toArray()).toEqual([10, -3, 7])
    expect(view.anchor.rotation.toArray()).toEqual([Math.PI, 0, 0, 'XYZ'])
    view.setEnabled(false)
    expect(material.clippingPlanes).toBe(original)
    expect(replacement.clippingPlanes).toBe(null)
    expect(renderer.localClippingEnabled).toBe(false)
    expect(controls.enabled).toBe(false)
    expect(sphere.visible).toBe(true)
    view.dispose()
    expect(callbacks.size).toBe(0)
  })
})
