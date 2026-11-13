import { it, expect } from 'vitest'
import { createSequenceEditQueue } from './sequence_edit_queue.js'
it('keeps writes ordered, replaces unsent drafts and lets the newest sequence win', async () => {
  const enqueue = createSequenceEditQueue(), committed = []
  let release
  const first = enqueue('a', async () => { await new Promise(r => { release = r }); committed.push('first') })
  const replaced = enqueue('a', async () => { committed.push('obsolete') })
  const latest = enqueue('a', async () => { committed.push('latest') })
  expect(await replaced).toBeNull()
  expect(committed).toEqual([])
  release(); await Promise.all([first, latest])
  expect(committed).toEqual(['first', 'latest'])
})
it('recovers from failures and discards queued work from a closed document', async () => {
  const enqueue = createSequenceEditQueue()
  let release, current = true
  const first = enqueue('a', () => new Promise(r => { release = r }))
  const stale = enqueue('b', () => { throw new Error('must not execute') }, () => current)
  current = false; release(); await first
  expect(await stale).toBeNull()
  await expect(enqueue('a', () => { throw new Error('failure') })).rejects.toThrow('failure')
  expect(await enqueue('a', () => 'next')).toBe('next')
})
