import { expect, it, vi } from 'vitest'
import { createFileOpenTasks } from './file_open_task.js'

it('keeps the current command owned until cancellation settles, then releases the document', async () => {
  let cancel
  const discarded = vi.fn(async () => {})
  const reset = vi.fn(), hide = vi.fn(), welcome = vi.fn()
  const tasks = createFileOpenTasks({ setCancel: fn => { cancel = fn }, progress: vi.fn(), log: vi.fn(), discard: discarded, reset, hide, welcome })
  const task = tasks.begin()
  cancel()
  expect(task.cancelled).toBe(true)
  expect(tasks.begin()).toBeNull()
  expect(discarded).not.toHaveBeenCalled()
  expect(await tasks.cancelled(task)).toBe(true)
  expect(discarded).toHaveBeenCalledOnce()
  expect(reset).toHaveBeenCalledOnce()
  expect(hide).toHaveBeenCalledOnce()
  expect(welcome).toHaveBeenCalledOnce()
  tasks.finish(task)
  expect(cancel).toBeNull()
  expect(tasks.begin()).not.toBeNull()
})

it('a normal open is never discarded and a failed discard is surfaced', async () => {
  const discard = vi.fn(async () => { throw new Error('offline') })
  let cancel
  const tasks = createFileOpenTasks({ setCancel: fn => { cancel = fn }, progress: vi.fn(), log: vi.fn(), discard, reset: vi.fn(), hide: vi.fn(), welcome: vi.fn() })
  const task = tasks.begin()
  expect(await tasks.cancelled(task)).toBe(false)
  expect(discard).not.toHaveBeenCalled()
  cancel()
  await expect(tasks.cancelled(task)).rejects.toThrow('offline')
})
