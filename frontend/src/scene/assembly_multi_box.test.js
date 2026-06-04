/**
 * Factory tests for the assembly multi-select union BoxHelper.
 *
 *   initAssemblyMultiBox — scene mutation + store/group read. Mock scene
 *   (add/remove trackers), createMockStore, mock assemblyRenderer.
 *
 * The pure union math (instanceUnionBox) is covered in selection_bbox.test.js;
 * here we assert the *wiring*: when a box is drawn vs suppressed, that it sits
 * in the scene, and that update() disposes the prior box before drawing.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { initAssemblyMultiBox } from './assembly_multi_box.js'

const center = (id, c, size = { x: 2, y: 2, z: 2 }) => ({
  id, center: new THREE.Vector3(...c), size,
})

function makeScene() {
  const objs = []
  return {
    objs,
    add: vi.fn((o) => objs.push(o)),
    remove: vi.fn((o) => { const i = objs.indexOf(o); if (i >= 0) objs.splice(i, 1) }),
  }
}

function setup(state = {}, centers = []) {
  const scene = makeScene()
  const store = createMockStore(state)
  const assemblyRenderer = { getInstanceCenters: vi.fn(() => centers) }
  const box = initAssemblyMultiBox({ scene, store, assemblyRenderer })
  return { scene, store, assemblyRenderer, box }
}

describe('initAssemblyMultiBox', () => {
  let warn
  beforeEach(() => { warn = vi.spyOn(console, 'warn').mockImplementation(() => {}) })

  it('draws nothing for an empty selection', () => {
    const { scene, box } = setup({ multiSelectedInstanceIds: [] })
    box.update()
    expect(scene.objs).toHaveLength(0)
  })

  it('suppresses the box for a single-part multi-select (no active group)', () => {
    const { scene, box } = setup(
      { multiSelectedInstanceIds: ['a'] },
      [center('a', [0, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(0)
  })

  it('draws one purple Box3Helper for a ≥2-part multi-select', () => {
    const { scene, box } = setup(
      { multiSelectedInstanceIds: ['a', 'b'] },
      [center('a', [0, 0, 0]), center('b', [10, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(1)
    const helper = scene.objs[0]
    expect(helper).toBeInstanceOf(THREE.Box3Helper)
    expect(helper.material.depthTest).toBe(false)
    expect(helper.renderOrder).toBe(1001)
  })

  it('draws for a single-member ACTIVE GROUP (group box is the only signal)', () => {
    const assembly = {
      groups: [{ id: 'g1', instance_ids: ['a'], subgroup_ids: [] }],
    }
    const { scene, box } = setup(
      { multiSelectedInstanceIds: [], activeGroupId: 'g1', currentAssembly: assembly },
      [center('a', [0, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(1)
  })

  it('folds transitive group members into the union', () => {
    const assembly = {
      groups: [
        { id: 'g1', instance_ids: ['a'], subgroup_ids: ['g2'] },
        { id: 'g2', instance_ids: ['b'], subgroup_ids: [] },
      ],
    }
    const { scene, assemblyRenderer, box } = setup(
      { multiSelectedInstanceIds: [], activeGroupId: 'g1', currentAssembly: assembly },
      [center('a', [0, 0, 0]), center('b', [10, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(1)
    expect(assemblyRenderer.getInstanceCenters).toHaveBeenCalled()
  })

  it('disposes the prior box before drawing a fresh one (no leak/dupe)', () => {
    const { scene, store, box } = setup(
      { multiSelectedInstanceIds: ['a', 'b'] },
      [center('a', [0, 0, 0]), center('b', [10, 0, 0])],
    )
    box.update()
    const first = scene.objs[0]
    const disposeSpy = vi.spyOn(first.geometry, 'dispose')
    box.update()
    expect(scene.objs).toHaveLength(1)        // still exactly one box
    expect(scene.objs[0]).not.toBe(first)     // a fresh helper
    expect(disposeSpy).toHaveBeenCalled()     // old one's geometry freed
  })

  it('clears the box when the selection drops below 2 (e.g. deselect)', () => {
    const { scene, store, box } = setup(
      { multiSelectedInstanceIds: ['a', 'b'] },
      [center('a', [0, 0, 0]), center('b', [10, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(1)
    store.setState({ multiSelectedInstanceIds: ['a'] })
    box.update()
    expect(scene.objs).toHaveLength(0)
  })

  it('dispose() removes any live box', () => {
    const { scene, box } = setup(
      { multiSelectedInstanceIds: ['a', 'b'] },
      [center('a', [0, 0, 0]), center('b', [10, 0, 0])],
    )
    box.update()
    expect(scene.objs).toHaveLength(1)
    box.dispose()
    expect(scene.objs).toHaveLength(0)
  })
})
