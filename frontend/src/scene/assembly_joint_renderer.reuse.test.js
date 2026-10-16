import { afterEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { initAssemblyJointRenderer } from './assembly_joint_renderer.js'

// Hover-preview textures require Canvas2D; the retained indicators below use
// their real Three.js meshes and materials without a GPU or canvas shim.
vi.mock('./joint_renderer.js', async importOriginal => ({
  ...await importOriginal(), buildJointPreviewMesh: () => new THREE.Group(),
}))

const cleanups = []
afterEach(() => { cleanups.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); delete window.NADOC_SHARED_RENDERER })
const copy = value => JSON.parse(JSON.stringify(value))
const settle = async () => { await Promise.resolve(); await Promise.resolve() }

function fixture(shared = false) {
  window.NADOC_SHARED_RENDERER = shared
  let assembly = { id: 'assembly', instances: [{ id: 'part', name: 'Part', visible: true,
    source: { type: 'file', path: 'part.nadoc' }, geometrySourceKey: 'f:/part.nadoc:1:',
    representation: 'cylinders', transform: { values: new THREE.Matrix4().toArray() },
    interface_points: [{ label: 'end', position: { x: 1, y: 2, z: 3 }, normal: { x: 0, y: 0, z: 1 }, cluster_id: 'cluster' }],
  }], joints: [{ id: 'joint', instance_a_id: 'part', instance_b_id: 'part',
    connector_a_label: 'end', connector_b_label: 'end', axis_origin: [1, 2, 3], axis_direction: [0, 0, 1] }] }
  const pending = [], api = { getAllConnectorFrames: vi.fn(() => new Promise((resolve, reject) => pending.push({ resolve, reject }))) }
  const scene = new THREE.Scene(), controls = { addEventListener: vi.fn(), removeEventListener: vi.fn() }
  const renderer = initAssemblyJointRenderer(scene, new THREE.PerspectiveCamera(), document.createElement('canvas'),
    { getState: () => ({ currentAssembly: assembly }) }, api, controls)
  let disposed = false
  const dispose = () => { if (!disposed) { renderer.dispose(); disposed = true } }
  cleanups.push(dispose)
  const find = predicate => { let result; scene.traverse(object => { if (!result && predicate(object)) result = object }); return result }
  return { scene, renderer, api, pending, dispose,
    assembly: () => assembly,
    change(fn) { assembly = copy(assembly); fn(assembly); return assembly },
    replace(next) { assembly = next; return assembly },
    rebuild() { renderer.rebuild(assembly) },
    connector: () => find(o => o.userData.instanceId === 'part' && o.userData.label === 'end'),
    joint: () => find(o => o.userData.tag === (shared ? 'assembly-mate-indicator-shared' : 'assembly-mate-indicator')),
    frames(x) { return { part: { end: { pos: [x, 2, 3], normal: [0, 0, 1] } } } },
  }
}

describe.each([false, true])('joint and connector reuse (shared=%s)', shared => {
  it('keeps meshes and one in-flight request across representation changes', async () => {
    const f = fixture(shared)
    f.rebuild()
    const joint = f.joint(), initialConnector = f.connector()
    const disposeGeometry = vi.spyOn(initialConnector.geometry, 'dispose')
    f.change(a => { a.instances[0].representation = 'full' }); f.rebuild()
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledOnce()
    expect(f.joint()).toBe(joint)
    expect(f.connector()).toBe(initialConnector)
    expect(disposeGeometry).not.toHaveBeenCalled()
    f.pending[0].resolve(f.frames(9)); await settle()
    expect(f.renderer.getConnectorDataMap().get('part::end').worldPos).toEqual([9, 2, 3])
    const authoritativeConnector = f.connector()
    f.change(a => { a.instances[0].representation = 'beads' }); f.rebuild()
    expect(f.connector()).toBe(authoritativeConnector)
    expect(f.joint()).toBe(joint)
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledOnce()
    f.renderer.setActiveInstance('part')
    expect(f.connector().parent.visible).toBe(true)
    f.renderer.setActiveInstance(null)
    expect(f.connector().parent.visible).toBe(false)
  })
})

describe('connector refresh validity', () => {
  it.each([
    ['pose', a => { a.instances[0].transform.values[3] = 4 }],
    ['source version', a => { a.instances[0].geometrySourceKey = 'f:/part.nadoc:2:' }],
    ['source path', a => { a.instances[0].source.path = 'other.nadoc' }],
    ['cluster override', a => { a.instances[0].cluster_transform_overrides = [{ cluster_id: 'cluster', translation: [2, 0, 0] }] }],
    ['interface point', a => { a.instances[0].interface_points[0].position.x = 7 }],
    ['joint', a => { a.joints[0].axis_origin[0] = 8 }],
    ['instance name', a => { a.instances[0].name = 'Renamed' }],
    ['visibility', a => { a.instances[0].visible = false }],
    ['assembly identity', a => { a.id = 'other' }],
  ])('rebuilds and rejects old frames when %s changes', async (_label, change) => {
    const f = fixture(); f.rebuild()
    const oldJoint = f.joint(), oldConnector = f.connector()
    f.change(change); f.rebuild()
    const currentConnector = f.connector()
    expect(currentConnector).not.toBe(oldConnector)
    expect(f.joint()).not.toBe(oldJoint)
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(2)
    f.pending[0].resolve(f.frames(100)); await settle()
    expect(f.connector()).toBe(currentConnector)
    f.pending[1].resolve(f.frames(20)); await settle()
    expect(f.renderer.getConnectorDataMap().get('part::end').worldPos).toEqual([20, 2, 3])
  })

  it('drops frames when the store changes before the next renderer rebuild', async () => {
    const f = fixture(); f.rebuild()
    const connector = f.connector()
    f.change(a => { a.instances[0].transform.values[3] = 4 })
    f.pending[0].resolve(f.frames(100)); await settle()
    expect(f.connector()).toBe(connector)
    f.rebuild()
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(2)
  })

  it('drops pre-reset frames even when the replacement document has identical input', async () => {
    const f = fixture(); f.rebuild()
    const connector = f.connector()
    window.dispatchEvent(new Event('nadoc:document-reset'))
    f.pending[0].resolve(f.frames(100)); await settle()
    expect(f.connector()).toBe(connector)
    f.rebuild()
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(2)
  })

  it.each([null, { id: 'empty', instances: [], joints: [] }])('cannot repopulate an emptied renderer', async empty => {
    const f = fixture(); f.rebuild()
    f.replace(empty); f.rebuild()
    expect(f.connector()).toBeUndefined()
    f.pending[0].resolve(f.frames(100)); await settle()
    expect(f.renderer.getConnectorDataMap().size).toBe(0)
    expect(f.connector()).toBeUndefined()
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledOnce()
  })

  it('does not request frames for an assembly without interface points', () => {
    const f = fixture()
    f.change(a => { a.instances[0].interface_points = []; a.joints = [] }); f.rebuild()
    expect(f.api.getAllConnectorFrames).not.toHaveBeenCalled()
  })

  it('retires pending responses and prevents rebuilding after disposal', async () => {
    const f = fixture(); f.rebuild(); f.dispose()
    const sceneChildren = f.scene.children.length
    f.pending[0].resolve(f.frames(100)); await settle(); f.rebuild()
    expect(f.renderer.getConnectorDataMap().size).toBe(0)
    expect(f.scene.children.length).toBe(sceneChildren)
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledOnce()
  })

  it.each(['null', 'reject'])('allows retry after a %s frame response', async failure => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const f = fixture(); f.rebuild()
    if (failure === 'null') f.pending[0].resolve(null)
    else f.pending[0].reject(new Error('offline'))
    await settle(); f.rebuild()
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(2)
  })

  it('supports forced refresh and restores canonical indicators after a live drag', () => {
    const f = fixture(); f.rebuild()
    const before = f.joint().position.clone()
    f.renderer.setLiveJointTransform('part', new THREE.Matrix4().makeTranslation(10, 0, 0), f.assembly())
    expect(f.joint().position.x).toBe(before.x + 10)
    f.rebuild()
    expect(f.joint().position.toArray()).toEqual(before.toArray())
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(2)
    f.renderer.rebuild(f.assembly(), { force: true })
    expect(f.api.getAllConnectorFrames).toHaveBeenCalledTimes(3)
  })
})
