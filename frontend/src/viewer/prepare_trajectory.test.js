import { it, expect, vi } from 'vitest'
import * as THREE from 'three'
import { prepareTrajectory } from './prepare_trajectory.js'
import { prepareScene } from './prepared_scene.js'
vi.mock('./trajectory_clip.js', async original => ({ ...await original(), gzipFrame: async b => b }))

function setup() {
  const scene = new THREE.Scene(), object = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()); scene.add(object)
  const currentDesign = {}, state = { currentDesign }, store = { getState: () => state }
  const controller = { trajectoryInfo: () => ({ total: 20, frame: 7 }), isActive: () => true, activeJobId: () => 'job', trajSpec: () => ({}), ensureTrajectoryFrame: vi.fn(async () => true), showFrame: vi.fn(i => { object.position.x = i }) }
  const companion = { plan: () => ({ water: false }), settleFrame: vi.fn(async () => true) }
  const prepared = { captureView: () => ({}), exportView: vi.fn(async () => ({ buffer: prepareScene({ scene, camera: { position: [0, 0, 10], up: [0, 1, 0], target: [0, 0, 0], fov: 55, orbitMode: 'orbit' } }) })) }
  return { source: { controller, companion, pause: vi.fn() }, prepared, store, from: 0, to: 2, state }
}
it('restores the inspected frame on cancellation and waits for each scientific companion', async () => {
  const v = setup(), abort = new AbortController()
  await expect(prepareTrajectory({ ...v, signal: abort.signal, onProgress: () => abort.abort() })).rejects.toThrow('cancelled')
  expect(v.source.controller.showFrame.mock.calls.at(-1)).toEqual([6])
  expect(v.source.companion.settleFrame.mock.calls.at(-1)).toEqual([6])
})
it('does not restore an old frame into a privately opened different design', async () => {
  const v = setup()
  await expect(prepareTrajectory({ ...v, onProgress: () => { v.state.currentDesign = {} } })).rejects.toThrow('cancelled')
  expect(v.source.controller.showFrame).toHaveBeenCalledTimes(1)
})
it('refuses water and invalid ranges before advancing the trajectory', async () => {
  const v = setup(); v.source.companion.plan = () => ({ water: true })
  await expect(prepareTrajectory(v)).rejects.toThrow('water')
  expect(v.source.controller.showFrame).not.toHaveBeenCalled()
  await expect(prepareTrajectory({ ...v, to: 150 })).rejects.toThrow('2–120')
})

it('reloads the original frame before restoring a progressively cached source', async () => {
  const v = setup()
  const result = await prepareTrajectory(v)
  expect(result.trajectory).toBe(true)
  expect(v.source.controller.ensureTrajectoryFrame.mock.calls.at(-1)).toEqual([6])
  expect(v.source.controller.showFrame.mock.calls.at(-1)).toEqual([6])
})
it('does not restore an old frame if the document switches while restoration loads', async () => {
  const v = setup()
  v.source.controller.ensureTrajectoryFrame.mockImplementation(async index => { if (index === 6) v.state.currentDesign = {}; return true })
  await prepareTrajectory(v)
  expect(v.source.controller.showFrame.mock.calls.map(c => c[0])).toEqual([0, 1, 2])
})

it.each(['vdw', 'ballstick', 'stick'])('waits for %s coordinates, round-trips their frames, and restores the inspected pose', async mode => {
  const v = setup(); v.state.atomisticMode = mode
  const move = v.source.controller.showFrame
  v.source.controller.showFrameForExport = vi.fn(async index => { await Promise.resolve(); move(index) })
  const { decodeContainer } = await import('./package_container.js')
  const { loadPreparedScene } = await import('./prepared_scene.js')
  const { createClipApplier } = await import('./trajectory_clip.js')
  const result = await prepareTrajectory(v), data = decodeContainer(result.buffer)
  // gzip is stubbed in this test file, so apply each exact raw patch directly.
  const frames = data.trajectory.frames
  delete data.trajectory
  const { encodeContainer } = await import('./package_container.js')
  const guest = await loadPreparedScene(encodeContainer(data)), apply = createClipApplier(guest)
  for (let index = 0; index < frames.length; index++) {
    apply.apply(frames[index].buffer.slice(frames[index].byteOffset, frames[index].byteOffset + frames[index].byteLength))
    expect(guest.scene.children[0].matrix.elements[12]).toBe(index)
  }
  expect(v.source.controller.showFrameForExport.mock.calls.map(c => c[0])).toEqual([0, 1, 2, 6])
  guest.dispose()
})
it('cancels when representation changes and does not restore into that new representation', async () => {
  const v = setup(); v.state.atomisticMode = 'vdw'
  v.source.controller.showFrameForExport = vi.fn(async () => {})
  await expect(prepareTrajectory({ ...v, onProgress: () => { v.state.atomisticMode = 'stick' } })).rejects.toThrow('cancelled')
  expect(v.source.controller.showFrameForExport).toHaveBeenCalledTimes(1)
})

it.each(['vdw', 'ballstick', 'stick'])('round-trips real %s atom/bond render buffers through the exact trajectory controller', async mode => {
  const { initAtomisticRenderer } = await import('../scene/atomistic_renderer.js')
  const { initOxdnaDisplay } = await import('../ui/oxdna_display.js')
  const { decodeContainer, encodeContainer } = await import('./package_container.js')
  const { loadPreparedScene } = await import('./prepared_scene.js')
  const { createClipApplier } = await import('./trajectory_clip.js')
  const scene = new THREE.Scene(), atom = initAtomisticRenderer(scene)
  atom.setMode(mode)
  const api = {
    trajectoryImpostors: true,
    getOxdnaTrajectory: async () => ({ ready: true, n_frames: 3, keys: [['h', 0, 'FORWARD']], frames: [0, 1, 2].map(i => [i, 0, 0, 1, 0, 0]) }),
    getOxdnaAtomisticModel: async () => ({ n_serials: 2, atoms: [
      { serial: 0, element: 'P', helix_id: 'h', strand_id: 's', x: 0, y: 0, z: 0 },
      { serial: 1, element: 'O', helix_id: 'h', strand_id: 's', x: .15, y: 0, z: 0 },
    ], bonds: [[0, 1]] }),
    getOxdnaFramesAtomistic: async (_job, indices) => Object.fromEntries(indices.map(i => [String(i), [i, 0, 0, i + .15, 0, 0]])),
  }
  const controller = initOxdnaDisplay({ designRenderer: { applyFemPositions() {}, clearScalarColors() {} }, api,
    getCurrentRepr: () => mode, getAtomisticRenderer: () => atom })
  await controller.loadTrajectory('job', true, 'job'); await controller.showFrameForExport(0)
  const state = { currentDesign: {}, atomisticMode: mode }
  const prepared = { captureView: () => ({}), exportView: async () => ({ buffer: prepareScene({ scene, camera: { position: [0,0,10], target: [0,0,0], up: [0,1,0], fov: 55, orbitMode: 'orbit' } }) }) }
  const result = await prepareTrajectory({ prepared, store: { getState: () => state }, source: { controller, pause: () => controller.setPlaying(false) }, from: 0, to: 2 })
  const data = decodeContainer(result.buffer), frames = data.trajectory.frames; delete data.trajectory
  const guest = await loadPreparedScene(encodeContainer(data)), apply = createClipApplier(guest)
  for (const index of [2, 0, 1]) {
    await controller.showFrameForExport(index)
    const bytes = frames[index]
    apply.apply(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))
    let checked = 0
    scene.traverseVisible(object => {
      if (!object.isInstancedMesh) return
      const loaded = guest.scene.getObjectByProperty('uuid', object.uuid)
      expect(loaded.instanceMatrix.array).toEqual(object.instanceMatrix.array); checked++
    })
    expect(checked).toBeGreaterThan(0)
  }
  guest.dispose(); controller.stopAndRestore(); atom.dispose()
})
