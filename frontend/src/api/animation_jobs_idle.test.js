import { afterEach, expect, it, vi } from 'vitest'
vi.mock('../state/store.js', () => ({ store: { getState: () => ({}), setState: vi.fn() } }))
import { listOxdnaJobs, listMdJobs } from './client.js'
import { beginOperationTiming, finishOperationAfterRender } from '../perf/operation_timing.js'

afterEach(() => vi.restoreAllMocks())
it('loads visible animation choices while render timing remains active, but still defers background polls', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })))
  const trace = beginOperationTiming('unfinished rendering')
  try {
    await Promise.all([listOxdnaJobs({ waitForIdle: false }), listMdJobs({ waitForIdle: false })])
    expect(fetch).toHaveBeenCalledTimes(2)
    const background = listMdJobs()
    await Promise.resolve()
    expect(fetch).toHaveBeenCalledTimes(2)
    finishOperationAfterRender(trace)
    await background
    expect(fetch).toHaveBeenCalledTimes(3)
  } finally { finishOperationAfterRender(trace); vi.unstubAllGlobals() }
})
