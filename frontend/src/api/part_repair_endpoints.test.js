import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPartRepairEndpoints, RepairRequestError } from './part_repair_endpoints.js'

const context = { docId: 'origin', designId: 'part', revision: 7 }
const receipt = { source: { size_bytes: 3, sha256: 'a'.repeat(64) }, feature_id: 'feature', expected_blob: { state: 'missing' } }
const response = (json, status = 200) => ({ ok: status < 400, status, json: async () => json })
afterEach(() => vi.useRealTimers())

describe('repair endpoint adapter', () => {
  it('pins every JSON request to its origin and forbids protected-loadout retry', async () => {
    const request = vi.fn(async () => ({})), apply = vi.fn(), acknowledge = vi.fn()
    const api = createPartRepairEndpoints({ request, apply, acknowledge })
    await api.inspect({ context })
    await api.mutate({ operation: 'rebase' }, { context })
    await api.evaluate({}, { context })
    await api.start({ operation: 'selection' }, { context })
    await api.poll('job/id', { context })
    await api.cancel('job/id', { context })
    await api.commit('job/id', { context })
    for (const [, , , options] of request.mock.calls) {
      expect(options).toMatchObject({ docId: 'origin', protectedRetry: false, suppressBusy: true, skipSimulationPrepare: true })
    }
    expect(request.mock.calls[4][1]).toMatch(/\/job%2Fid$/)
    expect(apply).not.toHaveBeenCalled()
    expect(acknowledge).not.toHaveBeenCalled()
  })

  it('preserves typed errors instead of reading the mutable global lastError', async () => {
    const detail = { code: 'repair_conflict', feature_id: 'feature', parameter_path: ['ids', 0] }
    const api = createPartRepairEndpoints({ request: async (_m, _p, _b, options) => { options.onError(409, detail); return null } })
    await expect(api.mutate({}, { context })).rejects.toMatchObject({ status: 409, detail })
  })

  it('uploads the original File without reading/base64-encoding it and escapes header Unicode', async () => {
    const file = new File(['PDB'], 'input.pdb'), rawRequest = vi.fn(async () => response({ revision: 8 }))
    file.arrayBuffer = vi.fn(() => { throw new Error('No full-buffer read') })
    const api = createPartRepairEndpoints({ rawRequest, headersFor: id => ({ 'X-NADOC-Doc': id }) })
    const selected = { ...receipt, feature_id: 'α' }
    expect(await api.uploadSource(selected, file, { context })).toEqual({ revision: 8 })
    const [path, options] = rawRequest.mock.calls[0]
    expect(path).toBe('/api/design/features/repair-draft/source')
    expect(options.body).toBe(file)
    expect(options.headers['X-NADOC-Doc']).toBe('origin')
    expect(JSON.parse(options.headers['X-NADOC-Repair-Source'])).toEqual(selected)
    expect(options.headers['X-NADOC-Repair-Source']).toMatch(/^[\x20-\x7e]*$/)
    expect(file.arrayBuffer).not.toHaveBeenCalled()
  })

  it('rejects byte count, global ceiling and header overflow before raw fetch', async () => {
    const rawRequest = vi.fn(), api = createPartRepairEndpoints({ rawRequest, headersFor: () => ({}) })
    await expect(api.uploadSource(receipt, new Blob(['wrong']), { context })).rejects.toBeInstanceOf(RepairRequestError)
    await expect(api.uploadSource({ source: { size_bytes: 350001 } }, { size: 350001 }, { context })).rejects.toMatchObject({ status: 413 })
    await expect(api.uploadSource({ ...receipt, feature_id: 'x'.repeat(8192) }, new Blob(['PDB']), { context })).rejects.toMatchObject({ status: 413 })
    expect(rawRequest).not.toHaveBeenCalled()
  })

  it('aborts a stalled upload and clears its deadline after completion', async () => {
    vi.useFakeTimers()
    const rawRequest = vi.fn((_p, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason))))
    const api = createPartRepairEndpoints({ rawRequest, headersFor: () => ({}), uploadTimeoutMs: 50 })
    const upload = api.uploadSource(receipt, new Blob(['PDB']), { context })
    const failure = expect(upload).rejects.toMatchObject({ name: 'TimeoutError' })
    await vi.advanceTimersByTimeAsync(50); await failure
    expect(vi.getTimerCount()).toBe(0)
  })
})
