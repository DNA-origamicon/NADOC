import { describe, expect, it, vi } from 'vitest'
import { canEditAtCursor, restoreHistoryForEdit } from './feature_edit_cursor.js'

vi.mock('./toast.js', () => ({ showPersistentToast: vi.fn() }))

describe('feature editing at the scrubber', () => {
  it.each([
    [-2, null, 0, null, false], [0, null, 0, null, true],
    [1, null, 0, null, true], [0, null, 1, null, false],
    [-1, null, 2, null, true], [1, 2, 1, 2, true],
    [1, 2, 1, 3, false], [1, -2, 1, 0, false],
    [1, 0, 0, null, true], [1, 0, 1, null, false],
  ])('cursor %s/%s editing %s/%s: %s', (cursor, child, index, subIndex, expected) => {
    expect(canEditAtCursor({ feature_log_cursor: cursor, feature_log_sub_cursor: child }, index, subIndex)).toBe(expected)
  })

  function fixture() {
    const source = { id: 'part', feature_log_cursor: 0, feature_log: [{ id: 'extrude' }, { id: 'route' }] }
    const state = { currentDesign: source }
    const store = { getState: () => state }
    const api = { seekFeatures: vi.fn(async () => {
      state.currentDesign = { ...source, feature_log_cursor: -1 }
      return { design: state.currentDesign }
    }) }
    return { source, state, store, api }
  }
  it('restores the full suffix before admitting an editor', async () => {
    const f = fixture()
    expect(await restoreHistoryForEdit(f.api, f.store, 0, 'extrude')).toBe(true)
    expect(f.api.seekFeatures).toHaveBeenCalledWith(-1)
    expect(f.state.currentDesign.feature_log).toEqual(f.source.feature_log)
    expect(f.source.feature_log_cursor).toBe(0)
  })
  it('does not seek for a future feature', async () => {
    const f = fixture()
    expect(await restoreHistoryForEdit(f.api, f.store, 1, 'route')).toBe(false)
    expect(f.api.seekFeatures).not.toHaveBeenCalled()
  })
  it.each(['failed', 'switched'])('does not open against a %s seek', async mode => {
    const f = fixture()
    f.api.seekFeatures.mockImplementation(async () => {
      if (mode === 'switched') f.state.currentDesign = { ...f.source, id: 'other', feature_log_cursor: -1 }
      return mode === 'failed' ? null : {}
    })
    expect(await restoreHistoryForEdit(f.api, f.store, 0, 'extrude')).toBe(false)
  })
})
