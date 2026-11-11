import { expect, it, vi } from 'vitest'
vi.mock('../scene/annotation_overlay.js', () => ({ captureSceneAnnotations: () => [{ id: 'shown' }] }))
import { capturedFeatureIndex, createKeyframeActions } from './keyframe_actions.js'

it('pins the current end to a stable feature index, including empty and previewed stages', () => {
  expect(capturedFeatureIndex({ feature_log: [{}, {}], feature_log_cursor: -1 })).toBe(1)
  expect(capturedFeatureIndex({ feature_log: [] })).toBe(-2)
  expect(capturedFeatureIndex({ feature_log: [{}, {}] }, 0)).toBe(0)
})
it.each([false, true])('captures visible subsets and the current camera without changing timing (assembly=%s)', async assembly => {
  const api = { keyframeAction: vi.fn(async () => ({})) }
  const actions = createKeyframeActions({ getContext: () => ({ document: { id: 'd', feature_log: [{}, {}] }, animationId: 'a', assembly }), api,
    player: { getCapturedFeatureIndex: () => 0 }, captureCurrentCamera: () => ({ position: [1, 2, 3], orbitMode: 'turntable' }),
    viewVolumes: { visibleIds: () => ['visible-volume'] }, zoomVolume: { visibleIds: () => ['visible-inset'] } })
  await actions.capture({ id: 'k', text: 'keep', hold_duration_s: 3 })
  expect(api.keyframeAction).toHaveBeenCalledWith(assembly, 'capture', 'a', 'k', expect.objectContaining({
    annotation_ids: ['shown'], view_volume_ids: ['visible-volume'], zoom_volume_ids: ['visible-inset'], feature_log_index: 0,
    pose: expect.objectContaining({ position: [1, 2, 3], orbit_mode: 'turntable' }),
  }))
})
it('duplicates selected assembly-part frames deeply and inserts immediately below the source', async () => {
  const document = { animations: [{ id: 'a', keyframes: [{ id: 'one', trajectory_scope: 'lineage', binding_states: { b: .5 } }, { id: 'two' }] }] }
  const actions = createKeyframeActions({ getContext: () => ({ document, animationId: 'a', patchPart: async change => change(document) }) })
  await actions.duplicate({ id: 'one' })
  const [source, copy, next] = document.animations[0].keyframes
  expect(copy.id).not.toBe(source.id); expect(next.id).toBe('two')
  expect(copy.trajectory_scope).toBe('lineage'); copy.binding_states.b = 0; expect(source.binding_states.b).toBe(.5)
})
