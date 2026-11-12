import { it, expect, vi, beforeEach } from 'vitest'
const fake = vi.hoisted(() => ({ add: vi.fn(), cancel: vi.fn(), finalize: vi.fn(), codec: 'vp9', outputs: [], hardware: false, configs: [], probes: [] }))
vi.mock('mediabunny', () => ({
  getFirstEncodableVideoCodec: async () => fake.codec,
  canEncodeVideo: async (codec, options) => { fake.probes.push({ codec, options }); return fake.hardware && codec === 'vp8' },
  BufferTarget: class { buffer = new ArrayBuffer(8) },
  WebMOutputFormat: class {},
  CanvasSource: class { constructor(_, config) { fake.configs.push(config) } add = fake.add },
  Output: class {
    constructor({ target }) { this.target = target; fake.outputs.push(this) }
    addVideoTrack() {}
    async start() { this.state = 'started' }
    async finalize() { await fake.finalize(); this.state = 'finalized' }
    cancel = fake.cancel
  },
}))
import { encodeWebM } from './encode_webm.js'
beforeEach(() => { vi.resetAllMocks(); fake.codec = 'vp9'; fake.outputs.length = 0; fake.hardware = false; fake.configs = []; fake.probes = [] })
const options = () => ({ canvas: { width: 640, height: 480 }, fps: 10, totalDur: 0.25, renderFrame: vi.fn(async () => {}) })
it('encodes all frames at explicit timeline timestamps, including a partial last frame', async () => {
  const opts = options(), completed = []
  opts.renderFrame = async time => { await Promise.resolve(); completed.push(time) }
  fake.add.mockImplementation(async timestamp => { expect(completed.at(-1)).toBe(timestamp) })
  const blob = await encodeWebM(opts)
  expect(completed).toEqual([0, 0.1, 0.2])
  expect(fake.add.mock.calls[2][1]).toBeCloseTo(0.05)
  expect(fake.add.mock.calls.map(c => c[1]).reduce((a, b) => a + b, 0)).toBeCloseTo(0.25)
  expect(blob.type).toBe('video/webm')
  expect(fake.finalize).toHaveBeenCalledOnce()
})
it('cancels resources on render failure and never writes a partial movie', async () => {
  const opts = options(); opts.renderFrame.mockRejectedValue(new Error('missing build state'))
  await expect(encodeWebM(opts)).rejects.toThrow('missing build state')
  expect(fake.cancel).toHaveBeenCalledOnce()
  expect(fake.finalize).not.toHaveBeenCalled()
})
it('cancels after a pending frame when the user aborts', async () => {
  const controller = new AbortController(), opts = options()
  opts.signal = controller.signal; opts.renderFrame = async () => controller.abort()
  await expect(encodeWebM(opts)).rejects.toMatchObject({ name: 'AbortError' })
  expect(fake.add).not.toHaveBeenCalled()
  expect(fake.cancel).toHaveBeenCalledOnce()
})
it('reports an unsupported encoder instead of silently recording wrong timing', async () => {
  fake.codec = null
  await expect(encodeWebM(options())).rejects.toThrow('WebCodecs')
  expect(fake.outputs).toHaveLength(0)
})

it('prefers a supported hardware codec and retains lossless timing/backpressure', async () => {
  fake.hardware = true
  await encodeWebM(options())
  expect(fake.configs[0]).toMatchObject({ codec: 'vp8', hardwareAcceleration: 'prefer-hardware', latencyMode: 'quality' })
  expect(fake.probes).toHaveLength(2)
})
it('falls back to the browser encoder when hardware configurations are unsupported', async () => {
  await encodeWebM(options())
  expect(fake.configs[0]).toMatchObject({ codec: 'vp9', hardwareAcceleration: 'no-preference' })
})
