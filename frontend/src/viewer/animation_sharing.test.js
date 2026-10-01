import { it, expect, vi } from 'vitest'
import { initAnimationSharing } from './animation_sharing.js'
vi.mock('./live_frame_capture.js', () => ({ LIVE_FRAME_LIMITS: {}, liveSceneSignature: () => 'stable', createLiveFrameCapture: () => ({ signature: 'stable', frame: () => new ArrayBuffer(8) }) }))
vi.mock('./package_container.js', () => ({ decodeContainer: () => ({}) }))
vi.mock('./trajectory_clip.js', () => ({ gzipFrame: async b => b }))
function setup() {
  const commands = [], active = [], prepared = { captureView: () => ({ pose: {}, camera: { near: .1, far: 100 } }), exportView: vi.fn(async () => ({ buffer: new ArrayBuffer(8) })) }
  const request = vi.fn(async (url, options) => { commands.push(url.split('/').at(-1)); return { ok: true, json: async () => ({ lease: 'secret', revision: 'a'.repeat(64) }) } })
  const afterStop = vi.fn(), beforeStart = vi.fn()
  const api = initAnimationSharing({ prepared, getRoom: () => ({ id: 'room', capabilities: ['animation-stream-v1'] }), beforeStart, afterStop,
    onActive: value => active.push(value), onError: vi.fn(), fetch: request, setInterval: () => 1, clearInterval: vi.fn() })
  return { api, commands, active, request, prepared, afterStop }
}
it('publishes endpoints and multiple keyframes under one lease, then restores previous presentation state', async () => {
  const v = setup()
  for (const time of [0, 1, 2]) await v.api.frame({ time, duration: 2, text: null })
  expect(v.commands).toEqual(['start', 'scene', 'frame', 'frame', 'frame'])
  expect(v.prepared.exportView).toHaveBeenCalledOnce()
  const packet = v.request.mock.calls.at(-1)[1].body
  const length = new DataView(packet.buffer).getUint32(64)
  expect(JSON.parse(new TextDecoder().decode(packet.slice(68, 68 + length))).animation.time).toBe(2)
  await v.api.stop()
  expect(v.commands.at(-1)).toBe('pause'); expect(v.active).toEqual([true, false]); expect(v.afterStop).toHaveBeenCalledOnce()
  v.api.dispose()
})
it('a stop during export prevents the stale frame from being uploaded', async () => {
  const v = setup(); let finish
  v.prepared.exportView.mockImplementation(() => new Promise(resolve => { finish = () => resolve({ buffer: new ArrayBuffer(8) }) }))
  const frame = v.api.frame({ time: 0, duration: 2 })
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  const stopped = v.api.stop(); finish(); await frame; await stopped
  expect(v.commands).toEqual(['start', 'pause']); expect(v.active.at(-1)).toBe(false)
  v.api.dispose()
})
