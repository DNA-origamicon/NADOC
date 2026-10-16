import { expect, it, vi } from 'vitest'
import { commitPlacementTransforms } from './placement_commit.js'

const pose = n => ({ translation: [n, 0, 0], rotation: [0, 0, 0, 1], pivot: [0, 0, 0] })
const queued = () => new Map([['same', pose(1)], ['second', pose(2)]])

it('commits active explicit owners together without borrowing organization membership', async () => {
  const pending = queued(), command = vi.fn(async () => ({ revision: 2 }))
  const patch = vi.fn()
  const result = await commitPlacementTransforms(pending, { organized: true, command, patch })
  expect(command).toHaveBeenCalledExactlyOnceWith('placements-update', { placements: [
    { placement_id: 'same', fields: pose(1) }, { placement_id: 'second', fields: pose(2) },
  ] })
  expect(patch).not.toHaveBeenCalled()
  expect(result).toMatchObject({ clusterIds: ['same', 'second'], geometryApplied: true, error: null })
  expect(pending.size).toBe(0)
})

it.each(['null', 'throw'])('retains every pending owner on %s batch refusal', async mode => {
  const pending = queued()
  const command = vi.fn(async () => { if (mode === 'throw') throw Error('Stale source'); return null })
  const result = await commitPlacementTransforms(pending, { organized: true, command })
  expect(result.error).toBeInstanceOf(Error)
  expect(result.clusterIds).toEqual([])
  expect(pending.size).toBe(2)
})

it('does not clear a newer local edit while an accepted request is in flight', async () => {
  const pending = queued()
  const result = await commitPlacementTransforms(pending, { organized: true,
    command: async () => { pending.set('same', pose(8)); return {} },
  })
  expect(result.clusterIds).toEqual(['same', 'second'])
  expect([...pending]).toEqual([['same', pose(8)]])
})

it('reports legacy partial acceptance and retains the refused owner for retry', async () => {
  const pending = queued(), patch = vi.fn().mockResolvedValueOnce({}).mockResolvedValueOnce(null)
  const result = await commitPlacementTransforms(pending, { organized: false, patch, log: false })
  expect(result.clusterIds).toEqual(['same'])
  expect(result.geometryApplied).toBe(false)
  expect(result.error).toBeInstanceOf(Error)
  expect([...pending.keys()]).toEqual(['second'])
  expect(patch).toHaveBeenNthCalledWith(1, 'same', { ...pose(1), commit: true, log: false })
})

it('does not send or clear anything when source ownership has changed', async () => {
  const pending = queued(), command = vi.fn()
  const result = await commitPlacementTransforms(pending, { organized: true, command, isCurrent: () => false })
  expect(command).not.toHaveBeenCalled()
  expect(result.error.message).toMatch(/changed/i)
  expect(pending.size).toBe(2)
})
