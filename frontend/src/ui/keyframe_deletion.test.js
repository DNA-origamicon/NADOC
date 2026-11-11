import { expect, it, vi } from 'vitest'
import { createKeyframeDeletion } from './keyframe_deletion.js'

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function setup() {
  let scope = 'part-a'
  const paint = deferred(), response = deferred()
  const refresh = vi.fn(), stopPlayback = vi.fn(), onError = vi.fn()
  const deletion = createKeyframeDeletion({ getScope: () => scope, refresh, stopPlayback, onError, afterPaint: () => paint.promise })
  const animation = { id: 'a', keyframes: [{ id: 'k', is_trajectory: true }, { id: 'keep' }] }
  const row = document.createElement('div'); document.body.append(row)
  const commit = vi.fn(() => response.promise)
  const remove = () => deletion.remove({ animationId: 'a', keyframeId: 'k', row, commit })
  return { deletion, animation, row, commit, remove, paint, response, refresh, stopPlayback, onError, scope: value => { scope = value } }
}
it('removes the row and excludes pending trajectory frames before cleanup or a server response', async () => {
  const f = setup(), pending = f.remove()
  expect(f.row.isConnected).toBe(false)
  expect(f.deletion.filter(f.animation).keyframes.map(k => k.id)).toEqual(['keep'])
  expect(f.animation.keyframes).toHaveLength(2)
  expect(f.stopPlayback).not.toHaveBeenCalled()
  expect(f.commit).not.toHaveBeenCalled()
  f.paint.resolve(); await vi.waitFor(() => expect(f.commit).toHaveBeenCalledOnce())
  expect(f.stopPlayback).toHaveBeenCalledWith('a')
  expect(f.deletion.filter(f.animation).keyframes).toHaveLength(1)
  f.response.resolve({}); await pending
  expect(f.onError).not.toHaveBeenCalled()
})
it.each([null, false])('restores current document state on a non-throwing API failure (%s)', async result => {
  const f = setup(), pending = f.remove()
  f.animation.keyframes.push({ id: 'new-edit' })
  f.paint.resolve(); f.response.resolve(result); await pending
  expect(f.deletion.filter(f.animation).keyframes.map(k => k.id)).toEqual(['k', 'keep', 'new-edit'])
  expect(f.onError).toHaveBeenCalledOnce()
  expect(f.refresh).toHaveBeenCalledTimes(2)
})
it('restores the row after thrown network errors', async () => {
  const f = setup(); f.commit.mockRejectedValue(new Error('offline'))
  const pending = f.remove(); f.paint.resolve(); await pending
  expect(f.deletion.filter(f.animation)).toBe(f.animation)
  expect(f.onError.mock.calls[0][0].message).toBe('offline')
})
it('ignores duplicate clicks and serializes deletions so responses cannot undo each other', async () => {
  const f = setup(), first = f.remove()
  await f.remove()
  const otherResponse = deferred(), otherCommit = vi.fn(() => otherResponse.promise)
  const second = f.deletion.remove({ animationId: 'a', keyframeId: 'keep', row: document.createElement('div'), commit: otherCommit })
  f.paint.resolve(); await vi.waitFor(() => expect(f.commit).toHaveBeenCalledOnce())
  expect(otherCommit).not.toHaveBeenCalled()
  expect(f.deletion.filter(f.animation).keyframes).toEqual([])
  f.response.resolve({}); await first
  await vi.waitFor(() => expect(otherCommit).toHaveBeenCalledOnce())
  otherResponse.resolve({}); await second
})
it('does not issue a deferred delete against a newly opened document', async () => {
  const f = setup(), pending = f.remove()
  f.scope('part-b'); f.paint.resolve(); await pending
  expect(f.commit).not.toHaveBeenCalled()
  expect(f.refresh).not.toHaveBeenCalled()
  expect(f.stopPlayback).not.toHaveBeenCalled()
})
it('does not rebuild a different document when an old response finishes', async () => {
  const f = setup(), pending = f.remove()
  f.paint.resolve(); await vi.waitFor(() => expect(f.commit).toHaveBeenCalledOnce())
  f.scope('assembly-b'); f.refresh.mockClear(); f.response.resolve({}); await pending
  expect(f.refresh).not.toHaveBeenCalled()
})
