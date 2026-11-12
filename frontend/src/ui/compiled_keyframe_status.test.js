import { expect, it, vi } from 'vitest'
import { initCompiledKeyframeStatus } from './compiled_keyframe_status.js'
it('tracks individual clips, prefix edits, source changes and matching loaded packages', async () => {
  let source = { id: 'd', version: 1 }
  const animation = { id: 'a', fps: 30, keyframes: [{ id: 'x' }, { id: 'y', trajectory_job_id: 'md', trajectory_smooth_playback: true }] }
  const changed = vi.fn()
  const status = initCompiledKeyframeStatus({ getAnimation: () => animation, getSource: () => source,
    hashSource: async s => String(s.version), onChange: changed })
  await status.refresh()
  expect(changed.mock.lastCall[0].get('y')).toBe('none')
  status.record({ sourceId: 'd', sourceHash: '1', animation: structuredClone(animation), clipKeyframeIds: ['y'] })
  await status.refresh(); expect(changed.mock.lastCall[0].get('y')).toBe('ready')
  animation.keyframes[1].trajectory_smooth_playback = false
  await status.refresh(); expect(changed.mock.lastCall[0].get('y')).toBe('stale')
  animation.keyframes[1].trajectory_smooth_playback = true
  animation.keyframes[0].camera_pose_id = 'changed'
  await status.refresh(); expect(changed.mock.lastCall[0].get('y')).toBe('stale')
  delete animation.keyframes[0].camera_pose_id
  source = { id: 'd', version: 2 }
  await status.refresh(); expect(changed.mock.lastCall[0].get('y')).toBe('stale')
  source = { id: 'other', version: 1 }
  await status.refresh(); expect(changed.mock.lastCall[0].get('y')).toBe('none')
  status.dispose()
})
it('ignores obsolete async checks when switching documents', async () => {
  let release, source = { id: 'a' }
  const animation = { id: 'a', keyframes: [{ id: 'k', trajectory_job_id: 'md' }] }
  const changed = vi.fn()
  const status = initCompiledKeyframeStatus({ getAnimation: () => animation, getSource: () => source, onChange: changed,
    hashSource: s => s.id === 'a' ? new Promise(r => { release = r }) : Promise.resolve('b') })
  const old = status.refresh(); await Promise.resolve()
  source = { id: 'b' }; await status.refresh()
  const calls = changed.mock.calls.length
  release('a'); await old
  expect(changed).toHaveBeenCalledTimes(calls)
})
