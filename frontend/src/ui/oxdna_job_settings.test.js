import { afterEach, expect, it, vi } from 'vitest'
import { createOxdnaJobSettings, relaxationElementsSettings } from './oxdna_job_settings.js'
afterEach(() => vi.useRealTimers())

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
