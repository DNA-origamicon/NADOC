// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest'
import { installTestApi } from './test_api.js'
import * as THREE from 'three'

describe('installTestApi', () => {
  it('observes visible lattice cells without exposing hidden or offscreen targets', () => {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100)
    camera.position.z = 10
    camera.updateMatrixWorld()
    const add = (row, x, visible = true) => {
      const mesh = new THREE.Mesh(new THREE.CircleGeometry(1), new THREE.MeshBasicMaterial())
      mesh.userData = { row, col: 0, state: 'free' }
      mesh.position.x = x
      mesh.visible = visible
      scene.add(mesh)
      return mesh
    }
    const cell = add(0, 0)
    add(0, 0) // fill + ring share one cell
    add(1, 100) // outside viewport
    add(2, 0, false)
    let visible = true
    installTestApi({ scene, camera,
      canvas: { getBoundingClientRect: () => ({left:10, top:20, width:200, height:200}) },
      slicePlane: { isVisible: () => visible }, forceCrossoverTool: {testApi:{}} })
    expect(window.__nadocTest.getSliceCellScreenPositions()).toEqual([
      { row:0, col:0, state:'free', x:110, y:120 },
    ])
    expect(cell.userData).toEqual({row:0,col:0,state:'free'})
    visible = false
    expect(window.__nadocTest.getSliceCellScreenPositions()).toEqual([])
  })
  afterEach(() => {
    delete window.__nadocTest
    delete window.__nadocForceXover
  })

  it('publishes the stable automation facade and force-crossover hook', () => {
    const forceApi = { state: () => 'idle' }
    const selected = []
    installTestApi({
      scene: {},
      store: { getState: () => ({}) },
      visibilityController: {},
      designRenderer: {},
      controls: {},
      camera: {},
      canvas: {},
      renderer: {},
      oxdnaAnchorsSetup: {},
      selectionManager: {},
      selectionController: { replace: refs => selected.push(refs) },
      bluntEnds: {},
      slicePlane: {},
      assemblyRenderer: {},
      _assemblyPendingPartJoints: new Map(),
      _assemblyPendingTransforms: new Map(),
      api: {
        createGoldNanosphere: () => 'created', patchNanoparticle: () => 'patched',
        deleteNanoparticle: () => 'deleted',
      },
      nanoparticleSubsystem: { select: id => selected.push([{ kind: 'nanoparticle', id }]), meshes: new Map() },
      forceCrossoverTool: { testApi: forceApi },
    })

    expect(window.__nadocTest.scene).toEqual({})
    expect(window.__nadocTest.visibility).toBeTypeOf('object')
    expect(window.__nadocTest.viewerDiagnostic).toBeTypeOf('function')
    expect(window.__nadocTest.pickAssemblyInstanceAt).toBeTypeOf('function')
    expect(window.__nadocForceXover).toBe(forceApi)
    window.__nadocTest.selectProteinForTest('protein-1')
    expect(selected).toEqual([[{ kind: 'protein', id: 'protein-1' }]])
    expect(window.__nadocTest.nanoparticles.create(10)).toBe('created')
    window.__nadocTest.nanoparticles.select('gold-1')
    expect(selected.at(-1)).toEqual([{ kind: 'nanoparticle', id: 'gold-1' }])
  })
})
