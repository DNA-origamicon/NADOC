import { afterEach, expect, it, vi } from 'vitest'
import { createOxdnaJobSettings, continuationElementsSettings, relaxationElementsSettings, relaxationElementsSignature } from './oxdna_job_settings.js'
afterEach(() => vi.useRealTimers())

it('autosaves anchors without Run or an explicit flush', async () => {
  vi.useFakeTimers()
  const saved = { job_id: 'queued', status: 'queued', run_config: { surface_anchors: ['added'] } }
  const save = vi.fn().mockResolvedValue(saved)
  const onSaved = vi.fn()
  const settings = createOxdnaJobSettings({ save, onSaved })
  settings.change({ job_id: 'queued' }, { surface_anchors: ['added'] })
  await vi.advanceTimersByTimeAsync(250)
  expect(save).toHaveBeenCalledWith('queued', { surface_anchors: ['added'] })
  expect(onSaved).toHaveBeenCalledWith(saved, true)
  expect(settings.hasPending('queued')).toBe(false)
})

it('coalesces typing, serializes writes, and keeps edits attached to their job', async () => {
  vi.useFakeTimers()
  let complete
  const save = vi.fn().mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    .mockImplementation(async (job_id, patch) => ({ job_id, run_config: patch }))
  const onSaved = vi.fn()
  const settings = createOxdnaJobSettings({ save, onSaved })
  const a = { job_id: 'a', run_config: {} }, b = { job_id: 'b', run_config: {} }
  settings.change(a, { anchors: ['old'] })
  settings.change(a, { anchors: ['first'] })
  await vi.advanceTimersByTimeAsync(250)
  expect(save).toHaveBeenCalledOnce()
  settings.change(a, { anchors: ['latest'] })
  settings.change(b, { surface: null })
  expect(settings.overlay(a).run_config.anchors).toEqual(['latest'])
  const flushed = settings.flush('a')
  complete({ job_id: 'a', run_config: { anchors: ['first'] } })
  await flushed
  expect(save.mock.calls.slice(0, 2)).toEqual([
    ['a', { anchors: ['first'] }], ['a', { anchors: ['latest'] }],
  ])
  expect(onSaved.mock.calls.map(call => call[1])).toEqual([false, true])
  await settings.flush('b')
  expect(save).toHaveBeenLastCalledWith('b', { surface: null })
})

it('retains a failed edit and makes a run flush fail until saving succeeds', async () => {
  const save = vi.fn().mockResolvedValueOnce(null).mockResolvedValue({ job_id: 'a' })
  const settings = createOxdnaJobSettings({ save })
  settings.change({ job_id: 'a' }, { anchors: ['chosen'] })
  await expect(settings.flush('a')).rejects.toThrow('Could not save')
  expect(settings.hasPending('a')).toBe(true)
  await settings.flush('a')
  expect(settings.hasPending('a')).toBe(false)
  expect(save).toHaveBeenCalledTimes(2)
})

it('explicitly clears disabled surface forces and removed anchors', () => {
  expect(relaxationElementsSettings({ surface: { enabled: false }, anchors: [], surfaceAnchors: [{}] }))
    .toEqual({ surface: null, anchors: [], surface_anchors: [], surface_strands: null })
})


it('saves continuation field changes and explicit removal, while relaxation remains field-free', () => {
  const field = { enabled: true, field_pN: 2, dir: [0, 0, 1] }
  const first = continuationElementsSettings({ field })
  expect(first.field).toEqual({ field_pN: 2, dir: [0, 0, 1] })
  for (const change of [{ ...field, field_pN: 3 }, { ...field, dir: [0, -1, 0] }, { ...field, enabled: false }]) {
    expect(relaxationElementsSignature(continuationElementsSettings({ field: change })))
      .not.toBe(relaxationElementsSignature(first))
  }
  expect(continuationElementsSettings({ field: { ...field, enabled: false } }).field).toBeNull()
  expect(relaxationElementsSettings({ field })).not.toHaveProperty('field')
})

it('recovers the latest direction after reload before the debounce or request finishes', async () => {
  vi.useFakeTimers()
  const values = new Map()
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const save = vi.fn().mockImplementation(async (job_id, patch) => ({ job_id, run_config: patch }))
  const options = { storage, storageKey: 'test-drafts', save }
  const first = createOxdnaJobSettings(options)
  const job = { job_id: 'a', run_config: {} }
  first.change(job, { field: { field_pN: 2, dir: [1, 0, 0] } })
  const final = { field: { field_pN: 2, dir: [0, 0, -1] } }
  first.change(job, final)
  expect(save).not.toHaveBeenCalled()
  vi.clearAllTimers() // the old page is gone before its debounce fires
  const reloaded = createOxdnaJobSettings(options)
  expect(reloaded.overlay(job).run_config).toEqual(final)
  reloaded.restore([job])
  await reloaded.flush(job.job_id)
  expect(save).toHaveBeenCalledExactlyOnceWith('a', final)
  expect(values.size).toBe(0)
})
