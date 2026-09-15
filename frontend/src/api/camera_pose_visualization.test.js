import { afterEach, expect, it, vi } from 'vitest'
import { createCameraPose } from './client.js'
import { store } from '../state/store.js'

afterEach(() => vi.unstubAllGlobals())

it('collects a pose without replacing the live simulation projection or render state', async () => {
  const projected = { id: 'd1', helices: [{ id: 'simulation-helix' }], strands: [], camera_poses: [] }
  const geometry = [{ simulation: true }]
  const colors = { s1: 0xff0000 }
  store.setState({ currentDesign: projected, currentGeometry: geometry, strandColors: colors })
  const pose = { id: 'pose1', position: [1, 2, 3], target: [0, 0, 0], up: [0, 1, 0], fov: 50 }
  const fetch = vi.fn(async () => ({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({
      design: { id: 'd1', helices: [{ id: 'authored-helix' }], strands: [], camera_poses: [pose] },
      validation: { loop_strand_ids: [] },
    }),
  }))
  vi.stubGlobal('fetch', fetch)
  await createCameraPose('Pose 1', pose)
  const state = store.getState()
  expect(state.currentDesign.camera_poses).toEqual([pose])
  expect(state.currentDesign.helices).toBe(projected.helices)
  expect(state.currentGeometry).toBe(geometry)
  expect(state.strandColors).toBe(colors)
  expect(fetch).toHaveBeenCalledTimes(1)
})
