import { expect, it, vi } from 'vitest'
const encoded = vi.hoisted(() => ({ times: [], fail: false }))
vi.mock('./encode_webm.js', () => ({ encodeWebM: async opts => {
  if (encoded.fail) throw new Error('encoder failed')
  await opts.renderFrame(0); await opts.renderFrame(opts.totalDur / 2)
  return new Blob(['video'], { type: 'video/webm' })
} }))
vi.mock('./export_video.js', () => ({ editorVideoFrame: () => async t => { encoded.times.push(t) } }))
vi.mock('../viewer/placement_scene_guard.js', () => ({ assertPlacementExportSafe: () => {} }))
import { compilePresentation } from './compile_presentation.js'
function setup() {
  encoded.times = []; encoded.fail = false
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({})
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/jpeg;base64,AA==')
  const player = { play: vi.fn(async () => {}), pause: vi.fn(), stop: vi.fn(),
    getBounce: () => true, getLoopMode: () => true, getDisablePoses: () => true,
    setBounce: vi.fn(), setLoopMode: vi.fn(), setDisablePoses: vi.fn(),
    getKeyframeRange: id => id === 'a' ? { start: 0, end: 2 } : { start: 2, end: 5 } }
  const renderer = { domElement: { width: 800, height: 600 }, getPixelRatio: () => 2, setPixelRatio: vi.fn(), setSize: vi.fn() }
  return { player, renderer, camera: { aspect: 4 / 3, updateProjectionMatrix: vi.fn() }, scene: {},
    animation: { name: 'Talk', fps: 30, keyframes: [{ id: 'a' }, { id: 'b', trajectory_job_id: 'md', trajectory_smooth_playback: true, trajectory_frame_start: 20, trajectory_frame_end: 25 }] } }
}
it('prepares once, captures independent clips in the full schedule, and restores settings', async () => {
  const options = setup()
  const blob = await compilePresentation(options)
  expect(blob.type).toBe('text/html')
  expect(options.player.play).toHaveBeenCalledOnce()
  expect(options.player.play.mock.calls[0][0].keyframes[1].trajectory_frame_start).toBe(20)
  expect(options.player.play.mock.calls[0][0].keyframes[1].trajectory_smooth_playback).toBe(true)
  expect(encoded.times).toEqual([0, 1, 2, 2, 3.5, 5])
  expect(options.renderer.setSize).toHaveBeenLastCalledWith(400, 300, false)
  expect(options.player.setDisablePoses).toHaveBeenLastCalledWith(true)
  vi.restoreAllMocks()
})
it('restores the scene and does not return a package on encoder failure', async () => {
  const options = setup(); encoded.fail = true
  await expect(compilePresentation(options)).rejects.toThrow('encoder failed')
  expect(options.player.stop).toHaveBeenCalled()
  expect(options.renderer.setPixelRatio).toHaveBeenLastCalledWith(2)
  vi.restoreAllMocks()
})

it('renders only the selected clip, retaining preceding scene context but excluding later keyframes', async () => {
  const options = setup(), onPrepared = vi.fn()
  options.animation.keyframes.push({ id: 'later', trajectory_job_id: 'unneeded' })
  await compilePresentation({ ...options, keyframeId: 'b', onPrepared })
  expect(options.player.play.mock.calls[0][0].keyframes.map(kf => kf.id)).toEqual(['a', 'b'])
  expect(encoded.times).toEqual([2, 3.5, 5])
  expect(onPrepared.mock.calls[0][0]).toMatchObject({ clipKeyframeIds: ['b'], ranges: [{ start: 2, end: 5 }] })
  vi.restoreAllMocks()
})
