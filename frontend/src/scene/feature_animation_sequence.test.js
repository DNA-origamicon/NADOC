import { describe, it, expect } from 'vitest'
import { featurePath, featurePair, featureBakePositions } from './feature_animation_sequence.js'
describe('construction state sequences', () => {
  it('walks forward, backward, initial and final aliases without extra final steps', () => {
    expect(featurePath(-2, -1, 4)).toEqual([-2, 0, 1, 2, -1])
    expect(featurePath(-1, -2, 4)).toEqual([-1, 2, 1, 0, -2])
    expect(featurePath(1, 3, 5)).toEqual([1, 2, 3])
    expect(featurePath(3, -1, 4)).toEqual([3, -1])
  })
  it('holds and resolves exact boundaries and adjacent blends', () => {
    expect(featurePair([0, 1, 2, 3], 0.5)).toEqual({ from: 1, to: 2, t: 0.5 })
    expect(featurePair([3, 2, 1, 0], 1)).toEqual({ from: 1, to: 0, t: 1 })
    expect(featurePair([1, 1], 0.7)).toEqual({ from: 1, to: 1, t: 0.7 })
  })
  it('prepares every traversed state once and honors inherited pins and instant cuts', () => {
    expect(featureBakePositions({ keyframes: [
      { feature_log_index: 0, transition_duration_s: 0 },
      { feature_log_index: null, transition_duration_s: 2 },
      { feature_log_index: 3, transition_duration_s: 3 },
      { feature_log_index: 1, transition_duration_s: 2 },
    ] }, -1, 5)).toEqual([-1, 0, 1, 2, 3])
  })
})

import { assertFeatureSampling } from './feature_animation_sequence.js'
it('refuses exports that would silently skip build operations at the selected FPS', () => {
  const segment = { featurePath: [-2, 0, 1, 2, 3], startT: 0, transEnd: 1, easing: 'linear' }
  expect(() => assertFeatureSampling([segment], 3)).toThrow('at least 4 fps')
  expect(() => assertFeatureSampling([segment], 4)).not.toThrow()
  expect(() => assertFeatureSampling([{ ...segment, easing: 'ease-in-out' }], 4)).toThrow('at least 8 fps')
  expect(() => assertFeatureSampling([{ ...segment, transEnd: 0 }], 1)).not.toThrow()
})

import { sameFeatureSource } from './feature_animation_sequence.js'
it('permits authoring metadata refreshes but rejects changed feature history during preparation', () => {
  const source = { id: 'design', feature_log: [{ id: 'tick', post_state_gz_b64: 'state' }], helices: [{ id: 'h' }] }
  expect(sameFeatureSource(source, { ...structuredClone(source), metadata: { name: 'Saved' }, camera_poses: [] })).toBe(true)
  const changed = structuredClone(source); changed.feature_log[0].post_state_gz_b64 = 'edited'
  expect(sameFeatureSource(source, changed)).toBe(false)
})

it('accepts downloaded history bodies, including child presence sentinels, but rejects real edits', () => {
  const source = { id: 'd', feature_log: [{ id: 's', design_snapshot_gz_b64: '', children: [{ id: 'c', post_state_gz_b64: '1' }] }] }
  const hydrated = structuredClone(source)
  hydrated.feature_log[0].design_snapshot_gz_b64 = 'snapshot'
  hydrated.feature_log[0].children[0].post_state_gz_b64 = 'child-state'
  expect(sameFeatureSource(source, hydrated)).toBe(true)
  expect(sameFeatureSource(hydrated, source)).toBe(false)
  hydrated.feature_log[0].children[0].id = 'different-operation'
  expect(sameFeatureSource(source, hydrated)).toBe(false)
})
