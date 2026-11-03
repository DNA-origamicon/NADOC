import { expect, it, vi } from 'vitest'
import { createAssetSaveCoordination } from './asset_save_coordination.js'

it('waits for an in-flight acknowledgement, then defers autosave until publication finishes', async () => {
  const saves = createAssetSaveCoordination()
  let acknowledge
  const first = saves.save(() => new Promise(resolve => { acknowledge = resolve }), () => true)
  await Promise.resolve()
  const hold = saves.hold(), ready = vi.fn()
  hold.ready.then(ready)
  const action = vi.fn(), queued = saves.save(action, () => true)
  await Promise.resolve()
  expect(ready).not.toHaveBeenCalled()
  expect(action).not.toHaveBeenCalled()
  acknowledge(); await first; await hold.ready
  expect(action).not.toHaveBeenCalled()
  hold.release(); await queued
  expect(action).toHaveBeenCalledTimes(1)
})

it('drops a deferred save when the document changes and releases a hold only once', async () => {
  const saves = createAssetSaveCoordination(), hold = saves.hold(), action = vi.fn()
  let current = true
  const queued = saves.save(action, () => current)
  current = false; hold.release(); hold.release()
  expect(await queued).toBeNull()
  expect(action).not.toHaveBeenCalled()
  const next = saves.hold()
  hold.release()
  expect(() => saves.hold()).toThrow('Finish or refresh')
  next.release()
})
