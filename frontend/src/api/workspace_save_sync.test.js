import { beforeEach, describe, expect, it, vi } from 'vitest'

import { saveDesignAs, saveDesignToWorkspace } from './client.js'
import { store } from '../state/store.js'

function response({ disposition, design }) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => ({
      design,
      validation: { results: [] },
      identity_disposition: disposition,
      path: '2hb_1xT.nadoc',
    }),
  }
}

describe('workspace save response synchronization', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
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

    expect(store.getState().currentDesign).toBe(current)
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
