// @vitest-environment node
import {it, expect, vi} from 'vitest'
import {nativeJSONBlob, nativeJSONSize, NATIVE_UPLOAD_CHUNK} from './path_trace_native_upload.js'
import {requestOptix} from './path_trace_errors.js'

it.each([0, 1, 2, 3, 49151, 49152, 49153, 98306])('round-trips %i binary bytes, respecting subarray boundaries and base64 padding', async length => {
  const backing = Uint8Array.from({length: length + 11}, (_, i) => i % 251)
  const view = backing.subarray(7, 7 + length)
  const blob = await nativeJSONBlob({mesh: {position: view}, name: 'DNA é', optional: undefined, array: [undefined, NaN]})
  const value = JSON.parse(await blob.text())
  expect(value).toMatchObject({name: 'DNA é', array: [null, null]})
  expect(value).not.toHaveProperty('optional')
  expect(Buffer.from(value.mesh.position, 'base64')).toEqual(Buffer.from(view))
  expect(blob.size).toBe(Buffer.byteLength(await blob.text()))
  expect(nativeJSONSize({mesh: {position: view}, name: 'DNA é', optional: undefined, array: [undefined, NaN]})).toBe(blob.size)
})

it('uploads large scenes in ordered bounded pieces before requesting a render', async () => {
  const position = new Uint8Array(7000001).fill(41), pieces = []
  const data = {position, width: 1, height: 1, samples: 1}
  let received = 0
  const fetcher = vi.fn(async (url, {body, headers}) => {
    expect(headers['X-NADOC-Render-Id']).toBe('test-frame')
    expect(Number(headers['X-NADOC-Upload-Bytes'])).toBe(nativeJSONSize(data))
    if (url.endsWith('/upload')) {
      expect(Number(headers['X-NADOC-Upload-Offset'])).toBe(received)
      expect(body.byteLength).toBeLessThan(NATIVE_UPLOAD_CHUNK + 1048576)
      pieces.push(Buffer.from(body)); received += body.byteLength
    } else {
      expect(body).toBeUndefined()
      expect(received).toBe(nativeJSONSize(data))
      const decoded = JSON.parse(Buffer.concat(pieces).toString())
      expect(Buffer.from(decoded.position, 'base64').equals(Buffer.from(position))).toBe(true)
    }
    return {ok: true}
  })
  await requestOptix('/id/frame', data, null, {fetcher, requestId: 'test-frame'})
  expect(fetcher).toHaveBeenCalledTimes(3)
})

it('stops at a rejected upload chunk and never renders partial geometry', async () => {
  const fetcher = vi.fn(async () => ({ok: false, status: 413, text: async () => '{"detail":"Capacity changed"}'}))
  await expect(requestOptix('/id/frame', {position: new Uint8Array(7000000)}, null, {fetcher})).rejects.toThrow('OptiX HTTP 413 while uploading the scene: Capacity changed')
  expect(fetcher).toHaveBeenCalledOnce()
})

it('never stringifies a scene or encodes a large binary string, and yields while packing', async () => {
  const source = new Uint8Array(2200001).fill(123)
  const stringify = JSON.stringify.bind(JSON), encode = globalThis.btoa.bind(globalThis)
  const jsonSpy = vi.spyOn(JSON, 'stringify').mockImplementation(value => {
    if (value && typeof value === 'object') throw new RangeError('Invalid string length')
    return stringify(value)
  })
  const base64Spy = vi.spyOn(globalThis, 'btoa').mockImplementation(value => {
    if (value.length > 49152) throw new RangeError('Invalid string length')
    return encode(value)
  })
  let yielded = false
  setTimeout(() => { yielded = true }, 0)
  let blob
  try {
    blob = await nativeJSONBlob({meshes: [{position: source}, {index: new Uint32Array([1, 2, 3])}]})
    expect(yielded).toBe(true)
  } finally { jsonSpy.mockRestore(); base64Spy.mockRestore() }
  const value = JSON.parse(await blob.text())
  expect(Buffer.from(value.meshes[0].position, 'base64').equals(Buffer.from(source))).toBe(true)
  expect(Buffer.from(value.meshes[1].index, 'base64')).toEqual(Buffer.from(new Uint32Array([1, 2, 3]).buffer))
})

it('cancels during packing without uploading a partial body', async () => {
  const controller = new AbortController(), fetcher = vi.fn()
  setTimeout(() => controller.abort(), 0)
  await expect(requestOptix('/id/frame', {position: new Uint8Array(3000000)}, controller.signal, {fetcher})).rejects.toMatchObject({name: 'AbortError'})
  expect(fetcher).not.toHaveBeenCalled()
})

it('checks encoded capacity and sends the existing JSON wire format to the worker', async () => {
  const fetcher = vi.fn(async (_url, {body}) => {
    expect(JSON.parse(await body.text())).toEqual({position: 'AQIDBA=='})
    return {ok: true}
  })
  const data = {position: new Uint8Array([1, 2, 3, 4])}
  await expect(requestOptix('/id/frame', data, null, {fetcher, maxBytes: 22})).rejects.toThrow(/available RAM\/scratch/)
  expect(fetcher).not.toHaveBeenCalled()
  await requestOptix('/id/frame', data, null, {fetcher, maxBytes: 23})
  expect(fetcher).toHaveBeenCalledOnce()
})
