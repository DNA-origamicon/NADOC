import { expect, it, vi } from 'vitest'
import { initTrajectoryPreparationQueue } from './trajectory_preparation_queue.js'
it('prioritizes authored order across engines and reorders only pending work', async () => {
  const queue = initTrajectoryPreparationQueue(), starts = []
  let finish
  queue.prioritize(['md:first', 'ox:second', 'md:third'])
  const second = queue.enqueue('ox:second', async () => { starts.push('second') })
  const first = queue.enqueue('md:first', async () => { starts.push('first'); await new Promise(r => { finish = r }) })
  const third = queue.enqueue('md:third', async () => { starts.push('third') })
  await vi.waitFor(() => expect(starts).toEqual(['first']))
  queue.prioritize(['md:third', 'ox:second', 'md:first'])
  expect(starts).toEqual(['first'])
  finish(); await Promise.all([first, second, third])
  expect(starts).toEqual(['first', 'third', 'second'])
})
it('continues later keyframes after a failed preparation', async () => {
  const queue = initTrajectoryPreparationQueue()
  const failed = queue.enqueue('a', async () => { throw new Error('missing frames') })
  const next = queue.enqueue('b', async () => 42)
  await expect(failed).rejects.toThrow('missing frames')
  await expect(next).resolves.toBe(42)
})
