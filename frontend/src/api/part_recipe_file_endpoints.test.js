import { afterEach, expect, it, vi } from 'vitest'
import { webcrypto } from 'node:crypto'
import { createRecipeFileRecoveryEndpoints, hashRecipeFile } from './part_recipe_file_endpoints.js'

vi.mock('../shared/doc_id.js', () => ({ docHeaders: () => ({ 'X-NADOC-Doc': 'recovery-tab' }) }))

const digest = bytes => webcrypto.subtle.digest('SHA-256', bytes)
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
const action = { action: 'upgrade_cluster_creation', feature_id: 'α', child_id: null,
  expected_version: 1, expected_cluster_id: 'group', expected_definition_sha256: 'b'.repeat(64) }
const request = { version: 1, expected_source_sha256: 'a'.repeat(64), actions: [action] }
const read = blob => new Promise((resolve, reject) => {
  const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(reader.error)
  reader.readAsArrayBuffer(blob)
})
afterEach(() => vi.useRealTimers())

it('frames UTF-8 metadata and the exact original File without interpreting its JSON', async () => {
  const file = new File([' {"large":9007199254740993}\n'], 'original.nadoc')
  file.text = vi.fn(() => { throw new Error('Do not read original JSON') })
  const rawRequest = vi.fn(async () => response({ status: 'review' }))
  const api = createRecipeFileRecoveryEndpoints({ rawRequest })
  await api.inspect(file)
  await api.recover(file, request)
  for (const [index, [path, options]] of rawRequest.mock.calls.entries()) {
    expect(path).toBe('/api/part-recipe/recovery')
    expect(options.method).toBe('POST')
    expect(options.headers).toEqual({ 'Content-Type': 'application/octet-stream', 'X-NADOC-Doc': 'recovery-tab' })
    const bytes = new Uint8Array(await read(options.body)), length = new DataView(bytes.buffer).getUint32(0)
    const header = JSON.parse(new TextDecoder().decode(bytes.subarray(4, 4 + length)))
    expect(header).toEqual(index ? { version: 1, operation: 'recover', request } : { version: 1, operation: 'inspect' })
    expect(new TextDecoder().decode(bytes.subarray(4 + length))).toBe(' {"large":9007199254740993}\n')
    expect(options.signal).toBeInstanceOf(AbortSignal)
  }
  expect(file.text).not.toHaveBeenCalled()
})

it('hashes only admitted file bytes, preserving the distinction between whitespace and numeric text', async () => {
  const a = new File(['{"a":1}'], 'a.nadoc'), b = new File(['{"a":1.0}'], 'b.nadoc')
  expect(await hashRecipeFile(a, { digest })).not.toBe(await hashRecipeFile(b, { digest }))
  await expect(hashRecipeFile(new File(['x'.repeat(1500001)], 'large.nadoc'), { digest })).rejects.toThrow(/1,500,000|1500000/)
})

it.each([0, 1500001])('refuses %i-byte input before HTTP work', async size => {
  const rawRequest = vi.fn(), api = createRecipeFileRecoveryEndpoints({ rawRequest })
  await expect(api.inspect(new File(['x'.repeat(size)], 'bad.nadoc'))).rejects.toThrow()
  expect(rawRequest).not.toHaveBeenCalled()
})

it('bounds request metadata and action count before sending the body', async () => {
  const rawRequest = vi.fn(), api = createRecipeFileRecoveryEndpoints({ rawRequest }), file = new File(['{}'], 'a.nadoc')
  for (const actions of [[], Array(65).fill(action)]) await expect(api.recover(file, { ...request, actions })).rejects.toThrow()
  await expect(api.recover(file, { ...request, actions: [{ ...action, expected_cluster_id: 'x'.repeat(256001) }] })).rejects.toThrow()
  expect(rawRequest).not.toHaveBeenCalled()
})

it('preserves typed HTTP errors and refuses a response exceeding the complete 16MB envelope', async () => {
  const detail = { code: 'recipe_file_limit', detail: 'File is too large' }, file = new File(['{}'], 'a.nadoc')
  const api = createRecipeFileRecoveryEndpoints({ rawRequest: vi.fn(async () => response({ detail }, 413)) })
  await expect(api.inspect(file)).rejects.toMatchObject({ status: 413, detail })
  const oversized = createRecipeFileRecoveryEndpoints({ rawRequest: async () => new Response('{}', {
    headers: { 'Content-Length': '16000001' },
  }) })
  await expect(oversized.inspect(file)).rejects.toThrow(/response|limit/i)
})

it('forwards cancel and enforces the 190-second client deadline without retained timers', async () => {
  vi.useFakeTimers()
  const rawRequest = vi.fn((_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true })
  }))
  const api = createRecipeFileRecoveryEndpoints({ rawRequest }), file = new File(['{}'], 'a.nadoc'), abort = new AbortController()
  const cancelled = api.inspect(file, { signal: abort.signal }), cancelledResult = expect(cancelled).rejects.toMatchObject({ name: 'AbortError' })
  abort.abort(); await cancelledResult
  const stalled = api.inspect(file), timeout = expect(stalled).rejects.toMatchObject({ name: 'TimeoutError' })
  await vi.advanceTimersByTimeAsync(190000); await timeout
  expect(vi.getTimerCount()).toBe(0)
})

it('refuses an already-cancelled request before HTTP and cancels a streaming response on abort', async () => {
  const aborted = new AbortController(); aborted.abort()
  const rawRequest = vi.fn(), file = new File(['{}'], 'a.nadoc')
  await expect(createRecipeFileRecoveryEndpoints({ rawRequest }).inspect(file, { signal: aborted.signal })).rejects.toMatchObject({ name: 'AbortError' })
  expect(rawRequest).not.toHaveBeenCalled()
  const cancel = vi.fn(), active = new AbortController()
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('{')) }, cancel })
  const api = createRecipeFileRecoveryEndpoints({ rawRequest: async () => new Response(stream) })
  const request = api.inspect(file, { signal: active.signal }), failed = expect(request).rejects.toMatchObject({ name: 'AbortError' })
  await Promise.resolve(); await Promise.resolve(); active.abort(); await failed
  expect(cancel).toHaveBeenCalledTimes(1)
})

it('bounds streamed bytes even without Content-Length and does not accept malformed UTF-8', async () => {
  const cancel = vi.fn(), stream = new ReadableStream({ start(controller) {
    controller.enqueue(new Uint8Array(8000001)); controller.enqueue(new Uint8Array(8000000))
  }, cancel })
  const file = new File(['{}'], 'a.nadoc')
  await expect(createRecipeFileRecoveryEndpoints({ rawRequest: async () => new Response(stream) }).inspect(file)).rejects.toThrow(/limit/)
  expect(cancel).toHaveBeenCalledTimes(1)
  await expect(createRecipeFileRecoveryEndpoints({ rawRequest: async () => new Response(new Uint8Array([0xff])) }).inspect(file)).rejects.toThrow()
})
