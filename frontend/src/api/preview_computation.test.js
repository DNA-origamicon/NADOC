import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDeformationPreviewEndpoints } from './deformation_preview_endpoints.js'

const origin = { preview_id: '11111111-1111-4111-8111-111111111111', expected_design_id: 'part',
  expected_revision: 7, feature_id: 'move' }
const lease = '22222222-2222-4222-8222-222222222222'
const context = { docId: 'doc', designId: 'part', revision: 7 }
const envelope = { ...origin, lease_id: lease, doc_id: 'doc', family: 'transform', command_kind: 'cluster_op' }
const pending = (operation = 'prepare', sequence = 0, extra = {}) => ({ ...envelope,
  request_sequence: sequence, status: operation === 'prepare' ? 'preparing' : 'applying',
  computation: { version: 1, operation, request_sequence: sequence, elapsed_seconds: 0, remaining_seconds: 180 }, ...extra })
const ready = () => ({ ...pending(), status: 'ready', remaining_seconds: 60,
  result: { ...envelope, request_sequence: 0, remaining_seconds: 60, projection_version: 1,
    evaluated_command_kind: 'cluster_op', before: {}, candidate: {}, control_context: {} } })
const applied = sequence => ({ ...envelope, request_sequence: sequence, status: 'applied', design_id: 'part', revision: 8 })
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
const make = request => createDeformationPreviewEndpoints({ request, family: 'transform' })
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000) })
afterEach(() => { vi.useRealTimers() })

describe('bounded numerical preview polling', () => {
  it('polls the original source/lease and returns only the final prepare display', async () => {
    const final = ready(), onComputation = vi.fn()
    const request = vi.fn().mockResolvedValueOnce(pending()).mockResolvedValueOnce(final)
    const task = make(request).prepare(origin, { context, onComputation })
    await vi.advanceTimersByTimeAsync(1000)
    expect(await task).toBe(final.result)
    expect(onComputation).toHaveBeenCalledWith(expect.objectContaining({ ...envelope, status: 'preparing' }))
    expect(request.mock.calls.map(([, path]) => path)).toEqual([
      '/design/features/transform-preview', '/design/features/transform-preview/status'])
    expect(request.mock.calls[1][2]).toEqual({ ...origin, lease_id: lease })
    expect(request.mock.calls[1][3]).toMatchObject({ docId: 'doc', protectedRetry: false, suppressBusy: true })
  })

  it('polls Apply to its exact receipt without submitting the edit twice', async () => {
    const body = { ...origin, lease_id: lease, request_sequence: 3, params: {} }
    const receipt = applied(3), request = vi.fn().mockResolvedValueOnce(pending('apply', 3)).mockResolvedValueOnce(receipt)
    const task = make(request).apply(body, { context })
    await vi.advanceTimersByTimeAsync(1000)
    expect(await task).toBe(receipt)
    expect(request.mock.calls.filter(([, path]) => path.endsWith('/apply'))).toHaveLength(1)
  })

  it.each([
    ['wrong source', value => { value.expected_revision++ }],
    ['wrong document', value => { value.doc_id = 'other' }],
    ['wrong operation', value => { value.computation.operation = 'apply' }],
    ['wrong sequence', value => { value.computation.request_sequence = 1 }],
    ['unbounded time', value => { value.computation.remaining_seconds = 181 }],
    ['nonfinite time', value => { value.computation.elapsed_seconds = Infinity }],
    ['unknown computation field', value => { value.computation.deadline = 999 }],
  ])('refuses %s before progress notification or polling', async (_label, mutate) => {
    const value = pending(); mutate(value)
    const request = vi.fn().mockResolvedValue(value), onComputation = vi.fn()
    await expect(make(request).prepare(origin, { context, onComputation })).rejects.toBeInstanceOf(Error)
    expect(request).toHaveBeenCalledOnce(); expect(onComputation).not.toHaveBeenCalled()
  })

  it.each(['lease_id', 'command_kind', 'request_sequence'])('rejects changed %s on subsequent status', async field => {
    const value = ready(); value[field] = field === 'request_sequence' ? 1 : 'foreign'
    const request = vi.fn().mockResolvedValueOnce(pending()).mockResolvedValueOnce(value)
    const task = make(request).prepare(origin, { context }); const failure = expect(task).rejects.toBeInstanceOf(Error)
    await vi.advanceTimersByTimeAsync(1000); await failure
  })

  it('rejects a final display whose identity differs from its status envelope', async () => {
    const final = ready(); final.result.feature_id = 'other'
    const request = vi.fn().mockResolvedValueOnce(pending()).mockResolvedValueOnce(final)
    const task = make(request).prepare(origin, { context }); const failure = expect(task).rejects.toBeInstanceOf(Error)
    await vi.advanceTimersByTimeAsync(1000); await failure
  })

  it('aborts a held status read and never adopts its late result', async () => {
    let finish
    const request = vi.fn().mockResolvedValueOnce(pending()).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const abort = new AbortController(), task = make(request).prepare(origin, { context, signal: abort.signal })
    const failure = expect(task).rejects.toBeInstanceOf(Error)
    await vi.advanceTimersByTimeAsync(1000); abort.abort(); await tick(); await failure
    finish(ready()); await tick()
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('bounds a stalled status read by180 seconds without retrying Apply', async () => {
    const request = vi.fn().mockResolvedValueOnce(pending('apply', 1)).mockImplementationOnce(() => new Promise(() => {}))
    const task = make(request).apply({ ...origin, lease_id: lease, request_sequence: 1, params: {} }, { context })
    const failure = expect(task).rejects.toBeInstanceOf(Error)
    await vi.advanceTimersByTimeAsync(180001); await failure
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('preserves a typed bound worker failure instead of returning it as a preview', async () => {
    const final = { ...pending('apply', 1), status: 'ready', remaining_seconds: 60,
      failure: { status: 422, detail: { code: 'missing_reference', detail: 'Later feature lost its input' } } }
    const request = vi.fn().mockResolvedValueOnce(pending('apply', 1)).mockResolvedValueOnce(final)
    const task = make(request).apply({ ...origin, lease_id: lease, request_sequence: 1, params: {} }, { context })
    const failure = expect(task).rejects.toMatchObject({ status: 422, code: 'missing_reference' })
    await vi.advanceTimersByTimeAsync(1000); await failure
  })

  it('does not treat a polling HTTP refusal as proof that Apply never published', async () => {
    const request = vi.fn().mockResolvedValueOnce(pending('apply', 1)).mockImplementationOnce(async (_m, _p, _b, options) => {
      options.onError(404, { code: 'missing_lease' }); return null
    })
    const task = make(request).apply({ ...origin, lease_id: lease, request_sequence: 1, params: {} }, { context })
    const failure = expect(task).rejects.toMatchObject({ publicationUnknown: true })
    await vi.advanceTimersByTimeAsync(1000); await failure
    expect(request).toHaveBeenCalledTimes(2)
  })
})

it('preserves bounded plain deadline failure text after worker cleanup exceeds its compute budget', async () => {
  const failure = { ...pending('apply', 1), status: 'ready', remaining_seconds: 60,
    computation: { version: 1, operation: 'apply', request_sequence: 1, elapsed_seconds: 181, remaining_seconds: 0 },
    failure: { status: 408, detail: 'Recipe regeneration time limit' } }
  const request = vi.fn().mockResolvedValueOnce(failure)
  await expect(make(request).apply({ ...origin, lease_id: lease, request_sequence: 1, params: {} }, { context }))
    .rejects.toMatchObject({ status: 408, message: 'Recipe regeneration time limit', computationFailure: true })
})
