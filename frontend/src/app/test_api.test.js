// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest'
import { installTestApi } from './test_api.js'

describe('installTestApi', () => {
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
