// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { initSectionView, isSectionContent, sectionStencilGeometryFor, sectionStencilMaterial } from './section_view.js'
import { makeImpostorPhongMaterial } from './impostor_material.js'

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
  it('uses closed sphere proxies so atom impostors contribute to the section cap', () => {
    const source = makeImpostorPhongMaterial({ radius: 0.35 })
    const mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), source, 1)
    const geometry = sectionStencilGeometryFor(mesh)
    geometry.computeBoundingSphere()
    expect(geometry.type).toBe('SphereGeometry')
    expect(geometry.boundingSphere.radius).toBeCloseTo(0.35)
    const material = sectionStencilMaterial(source, new THREE.Plane(), THREE.BackSide)
    expect(material.userData.isImpostor).toBeUndefined()
    expect(material.onBeforeCompile).not.toBe(source.onBeforeCompile)
    geometry.dispose()
  })
  it('does not place a sphere cap at the origin for GPU-positioned assembly impostors', () => {
    const source = makeImpostorPhongMaterial({ radius: 0.35 })
    source.customProgramCacheKey = () => `sharedInstanced_${source.uuid}`
    const mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), source, 1)
    expect(sectionStencilGeometryFor(mesh)).toBeNull()
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
  it('keeps three independent planes, isolates winding passes, and preserves session poses', () => {
    document.body.innerHTML = '<div id="right-view-actions"><div class="ox-card__body"></div></div><canvas></canvas>'
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera()
    const renderer = { domElement: document.querySelector('canvas'), localClippingEnabled: false }
    const material = new THREE.MeshBasicMaterial()
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(), material))
    const view = initSectionView({ scene, camera, renderer, document,
      controls: { target: new THREE.Vector3(), enabled: true }, addFrameCallback() {}, removeFrameCallback() {} })
    view.setEnabled(true)
    const first = view.planes[0]
    first.anchor.rotation.set(.2, .3, .4)
    const second = view.addPlane()
    expect(second.anchor.quaternion.equals(first.anchor.quaternion)).toBe(true)
    second.anchor.rotation.set(0, Math.PI / 2, 0)
    view.selectPlane(first.id)
    const third = view.addPlane()
    expect(third.anchor.quaternion.equals(second.anchor.quaternion)).toBe(true)
    third.anchor.rotation.set(Math.PI / 2, 0, 0)
    view.sync()
    expect(material.clippingPlanes).toHaveLength(3)
    for (const entry of view.planes) {
      expect(entry.cap.material.clippingPlanes).toEqual(view.planes.filter(p => p !== entry).map(p => p.plane))
      const winding = entry.group.children.filter(o => o.isMesh && o !== entry.cap)
      expect(winding).toHaveLength(2)
      for (const mesh of winding) expect(mesh.material.clippingPlanes).toEqual([entry.plane])
    }
    document.querySelector('[aria-label="Toggle plane 2 visibility"]').click()
    expect(material.clippingPlanes).toEqual([first.plane, third.plane])
    expect(second.group.visible).toBe(false)
    const pose = third.anchor.quaternion.clone()
    view.setEnabled(false)
    expect(material.clippingPlanes).toBeNull()
    view.setEnabled(true)
    expect(view.planes).toHaveLength(3)
    expect(third.anchor.quaternion.equals(pose)).toBe(true)
    expect(material.clippingPlanes).toEqual([first.plane, third.plane])
    view.deletePlane()
    expect(material.clippingPlanes).toEqual([first.plane])
    view.dispose()
    expect(material.clippingPlanes).toBeNull()
  })

})
