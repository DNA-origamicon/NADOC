import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { SilhouetteHighlight, registerSilhouetteHighlights, renderSilhouetteHighlights } from './silhouette_highlight.js'

it('keeps atom selection and annotation providers independently registered', () => {
  const scene = new THREE.Scene(), atom = vi.fn(), annotation = vi.fn()
  const removeAtom = registerSilhouetteHighlights(scene, atom)
  const removeAnnotation = registerSilhouetteHighlights(scene, annotation)
  renderSilhouetteHighlights({}, scene, {}, 2)
  expect(atom).toHaveBeenCalledOnce(); expect(annotation).toHaveBeenCalledOnce()
  removeAtom()
  renderSilhouetteHighlights({}, scene, {})
  expect(atom).toHaveBeenCalledOnce(); expect(annotation).toHaveBeenCalledTimes(2)
  removeAnnotation()
})

it('samples live instance/world transforms and material on every rendered frame', () => {
  const scene = new THREE.Scene(), outline = new SilhouetteHighlight({ occlusionScene: scene, exteriorOnly: true })
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial(), 2)
  scene.add(mesh)
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(1, 2, 3))
  mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(9, 9, 9))
  const renderer = {
    getDrawingBufferSize: v => v.set(100, 100), getRenderTarget: () => null,
    getClearColor: c => c.set(0), getClearAlpha: () => 1, shadowMap: { autoUpdate: true },
    autoClear: true, setClearColor: vi.fn(), setRenderTarget: vi.fn(), render: vi.fn(),
  }
  const entries = [{ instMesh: mesh, id: 0 }], camera = new THREE.PerspectiveCamera()
  outline.render(renderer, camera, entries, 0x3fb950, 1)
  expect(renderer.render.mock.calls[0][0]).toBe(scene)
  expect(renderer.render.mock.calls[1][0]).toBe(outline.scene)
  expect(outline.material.uniforms.sceneDepth.value).toBe(outline.occlusionTarget.depthTexture)
  expect(outline.material.uniforms.exteriorOnly.value).toBe(1)
  const proxy = outline.proxies.get(mesh), matrix = new THREE.Matrix4()
  proxy.getMatrixAt(0, matrix)
  expect(matrix.elements.slice(12, 15)).toEqual([1, 2, 3])
  proxy.getMatrixAt(1, matrix)
  expect(matrix.elements).toEqual(Array(16).fill(0))
  mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(4, 5, 6))
  mesh.position.set(7, 8, 9)
  outline.render(renderer, camera, entries, 0x3fb950, 1)
  proxy.getMatrixAt(0, matrix)
  expect(matrix.elements.slice(12, 15)).toEqual([4, 5, 6])
  expect(proxy.matrix.elements.slice(12, 15)).toEqual([7, 8, 9])
  expect(proxy.material).toBe(mesh.material)
  renderer.render.mockClear()
  mesh.visible = false
  outline.render(renderer, camera, entries, 0x3fb950, 1)
  expect(renderer.render).not.toHaveBeenCalled()
  outline.dispose(); mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose()
})
