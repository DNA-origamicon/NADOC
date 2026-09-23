import { beforeEach, describe, expect, it, vi } from 'vitest'

import { saveDesignAs, saveDesignToWorkspace, currentRevisionWatermark, resetRevisionWatermark } from './client.js'
import { store } from '../state/store.js'

function response({ disposition, design, revision = 7, previous_revision = null }) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => ({
      ...(disposition === 'confirmed' ? { design_id:design.id, revision, previous_revision } : { design, revision }),
      validation: { results: [] },
      identity_disposition: disposition,
      path: '2hb_1xT.nadoc',
    }),
  }
}

describe('workspace save response synchronization', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    resetRevisionWatermark()
  })

  it('does not replace currentDesign after a confirmed same-path autosave', async () => {
    const current = {
      id: 'same-id', strands: [], helices: [],
      metadata: { identity_confirmed_at: 'before' },
    }
    const serverCopy = {
      ...current,
      metadata: { ...current.metadata, identity_confirmed_at: 'after' },
    }
    store.setState({ currentDesign: current, validationReport: { marker: 'before' } })
    fetch.mockResolvedValueOnce(response({ disposition: 'confirmed', design: serverCopy }))

    const result = await saveDesignToWorkspace('2hb_1xT.nadoc')

    expect(currentRevisionWatermark()).toBe(7)
    expect(result.identity_disposition).toBe('confirmed')
    expect(store.getState().currentDesign).toBe(current)
    expect(store.getState().validationReport).toEqual({ marker: 'before' })
  })

  it('also preserves object identity for an explicit save to the same path', async () => {
    const current = { id: 'same-id', strands: [], helices: [], metadata: {} }
    store.setState({ currentDesign: current })
    fetch.mockResolvedValueOnce(response({
      disposition: 'confirmed',
      design: { ...current, metadata: { identity_confirmed_at: 'after' } },
    }))

    await saveDesignAs('2hb_1xT.nadoc', true)
    expect(currentRevisionWatermark()).toBe(7)

    expect(store.getState().currentDesign).toBe(current)
  })

  it('does not regress the watermark or advance it for another design', async () => {
    const current = { id:'same', helices:[], strands:[] }
    store.setState({ currentDesign:current })
    for (const [design, revision] of [[current,9],[current,3],[{ ...current,id:'other' },20]]) {
      fetch.mockResolvedValueOnce(response({ disposition:'confirmed', design, revision }))
      await saveDesignToWorkspace('2hb_1xT.nadoc')
      expect(currentRevisionWatermark()).toBe(9)
      expect(store.getState().currentDesign).toBe(current)
    }
  })

  it('does not mark intervening unseen edits as applied', async () => {
    const current = { id:'same', helices:[], strands:[] }
    store.setState({ currentDesign:current })
    fetch.mockResolvedValueOnce(response({ disposition:'confirmed', design:current,
      previous_revision:6, revision:7 }))
    await saveDesignToWorkspace('2hb_1xT.nadoc')
    expect(currentRevisionWatermark()).toBeNull()
  })

  it('still synchronizes an initial path claim or Save As identity change', async () => {
    const current = { id: 'old-id', strands: [], helices: [], metadata: {} }
    const claimed = {
      id: 'new-id', strands: [], helices: [],
      metadata: { identity_last_known_path: 'copy.nadoc' },
    }
    store.setState({ currentDesign: current })
    fetch.mockResolvedValueOnce(response({ disposition: 'save_as', design: claimed }))

    await saveDesignAs('copy.nadoc', true)

    expect(store.getState().currentDesign).toEqual(claimed)
    expect(store.getState().currentDesign).not.toBe(current)
  })
})
