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
