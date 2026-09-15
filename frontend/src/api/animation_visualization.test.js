import { afterEach, expect, it, vi } from 'vitest'
import {
  ensureDefaultAnimation, createAnimation, updateAnimation, deleteAnimation,
  createKeyframe, updateKeyframe, deleteKeyframe, reorderKeyframes,
} from './animation_endpoints.js'
import { store } from '../state/store.js'

afterEach(() => vi.unstubAllGlobals())

it.each([
  ['default animation', () => ensureDefaultAnimation()],
  ['create animation', () => createAnimation()],
  ['update animation', () => updateAnimation('a', { name: 'New' })],
  ['delete animation', () => deleteAnimation('a')],
  ['create keyframe', () => createKeyframe('a', { camera_pose_id: 'p' })],
  ['update keyframe', () => updateKeyframe('a', 'k', { hold_duration_s: 2 })],
  ['delete keyframe', () => deleteKeyframe('a', 'k')],
  ['reorder keyframes', () => reorderKeyframes('a', ['k'])],
])('%s preserves the simulation projection and renderer references', async (_name, mutate) => {
  const projected = {
    id: 'd1', helices: [{ id: 'simulation-helix' }], strands: [],
    camera_poses: [{ id: 'p' }], animations: [],
  }
  const geometry = [{ simulation: true }]
  const axes = { simulation: true }
  const colors = { s1: 0xff0000 }
  store.setState({
    currentDesign: projected, currentGeometry: geometry,
    currentHelixAxes: axes, strandColors: colors,
  })
  const animations = [{ id: 'a', keyframes: [{ id: 'k', camera_pose_id: 'p' }] }]
  const fetch = vi.fn(async () => ({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({
      design: { id: 'd1', helices: [{ id: 'authored-helix' }], strands: [], animations },
      validation: { loop_strand_ids: [] },
    }),
  }))
  vi.stubGlobal('fetch', fetch)
  await mutate()
  const state = store.getState()
  expect(state.currentDesign.animations).toEqual(animations)
  expect(state.currentDesign.helices).toBe(projected.helices)
  expect(state.currentDesign.strands).toBe(projected.strands)
  expect(state.currentDesign.camera_poses).toBe(projected.camera_poses)
  expect(state.currentGeometry).toBe(geometry)
  expect(state.currentHelixAxes).toBe(axes)
  expect(state.strandColors).toBe(colors)
  expect(fetch).toHaveBeenCalledTimes(1)
})
