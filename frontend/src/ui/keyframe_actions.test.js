import { expect, it, vi } from 'vitest'
import { createKeyframeActions } from './keyframe_actions.js'
import { captureNamedPose } from './saved_pose_capture.js'

it.each([false, true])('creates a normal saved pose and selects only its ID (assembly=%s)', async assembly => {
  const document = { id: 'd', camera_poses: [{ id: 'old' }] }
  const captureCurrentCamera = () => ({ position: [1, 2, 3], orbitMode: 'turntable' })
  const captureThumbnail = () => 'data:image/png;base64,YQ=='
  const create = vi.fn(async () => ({ [assembly ? 'assembly' : 'design']: { ...document, camera_poses: [...document.camera_poses, { id: 'concurrent' }, { id: 'new' }] } }))
  const update = vi.fn(async () => ({}))
  const api = { [assembly ? 'createAssemblyCameraPose' : 'createCameraPose']: create,
    [assembly ? 'updateAssemblyKeyframe' : 'updateKeyframe']: update }
  const actions = createKeyframeActions({ getContext: () => ({ document, animationId: 'a', assembly }), api,
    player: {}, captureCurrentCamera, captureThumbnail })
  await actions.capture({ id: 'k', text: 'keep', hold_duration_s: 3 })
  const expected = captureNamedPose(document, captureCurrentCamera, captureThumbnail)
  expect(expected.name).toBe('Pose 2')
  expect(create).toHaveBeenCalledWith(expected.name, expected.state)
  expect(update).toHaveBeenCalledWith('a', 'k', { camera_pose_id: 'new' })
})
it('does not assign a captured pose after switching documents', async () => {
  let document = { id: 'original' }
  const api = { createCameraPose: vi.fn(async () => { document = { id: 'other' }; return { design: { id: 'original', camera_poses: [{ id: 'new' }] } } }), updateKeyframe: vi.fn() }
  const actions = createKeyframeActions({ getContext: () => ({ document, animationId: 'a', assembly: false }), api, player: {}, captureCurrentCamera: () => ({}) })
  await expect(actions.capture({ id: 'k' })).rejects.toThrow('changed')
  expect(api.updateKeyframe).not.toHaveBeenCalled()
})
it('captures a selected assembly-part pose while preserving all other keyframe settings', async () => {
  const frame = { id: 'k', camera_pose_id: 'old', annotation_ids: ['note'], zoom_volume_ids: [], feature_log_index: 4, configuration_id: 'config', joint_values: { j: 3 } }
  const document = { camera_poses: [{ id: 'old' }], animations: [{ id: 'a', keyframes: [structuredClone(frame)] }] }
  const actions = createKeyframeActions({ getContext: () => ({ document, animationId: 'a', patchPart: async change => change(document) }), player: {}, captureCurrentCamera: () => ({ position: [1, 2, 3] }) })
  await actions.capture(frame)
  const pose = document.camera_poses[1]
  expect(pose.name).toBe('Pose 2')
  expect(document.animations[0].keyframes[0]).toEqual({ ...frame, camera_pose_id: pose.id })
})
it('duplicates selected assembly-part frames deeply and inserts immediately below the source', async () => {
  const document = { animations: [{ id: 'a', keyframes: [{ id: 'one', trajectory_scope: 'lineage', binding_states: { b: .5 } }, { id: 'two' }] }] }
  const actions = createKeyframeActions({ getContext: () => ({ document, animationId: 'a', patchPart: async change => change(document) }) })
  await actions.duplicate({ id: 'one' })
  const [source, copy, next] = document.animations[0].keyframes
  expect(copy.id).not.toBe(source.id); expect(next.id).toBe('two')
  expect(copy.trajectory_scope).toBe('lineage'); copy.binding_states.b = 0; expect(source.binding_states.b).toBe(.5)
})
