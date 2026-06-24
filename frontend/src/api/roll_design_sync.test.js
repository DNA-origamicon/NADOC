// Regression: the job "roll-design" client calls must APPLY the seeked design to the
// store (scene + feature-log cursor), not just return it. The bug was that
// rollOxdnaJobDesign/rollMdJobDesign used _request directly (which doesn't auto-sync),
// so the server seeked the design but the client never re-rendered it.
import { describe, it, expect, beforeEach, vi } from 'vitest'

import { rollOxdnaJobDesign, rollMdJobDesign, seekFeatures } from './client.js'
import { store } from '../state/store.js'

function rollResponse() {
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => ({
      design: { feature_log_cursor: 6, feature_log: [], strands: [], helices: [], loadouts: [] },
      validation: { results: [] },
      nucleotides: [],
      return_loadout_id: 'L1',
    }),
  }
}

describe('roll-design client calls apply the seeked design', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    store.setState({ currentDesign: { feature_log_cursor: -1, strands: [], helices: [] }, currentGeometry: [{ x: 1 }] })
  })

  it('rollOxdnaJobDesign syncs the seeked design (cursor moves) + returns the loadout id', async () => {
    fetch.mockResolvedValueOnce(rollResponse())
    const r = await rollOxdnaJobDesign('job1')
    expect(r.return_loadout_id).toBe('L1')                              // caller still gets it
    expect(store.getState().currentDesign.feature_log_cursor).toBe(6)   // design APPLIED (cursor moved)
  })

  it('rollMdJobDesign syncs the seeked design too', async () => {
    fetch.mockResolvedValueOnce(rollResponse())
    await rollMdJobDesign('md1')
    expect(store.getState().currentDesign.feature_log_cursor).toBe(6)
  })
})

describe('design syncs fire the in-page nadoc:design-changed event', () => {
  // The oxDNA + MD job panels listen to this to re-evaluate their out-of-date markers
  // — incl. when the user manually SEEKS the Feature Log back to a job's run position
  // (the panels' 1.5 s poll is paused off the Dynamics tab, so the event is the only
  // signal). Regression for "manual seek doesn't clear the ⚠".
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })

  it('seekFeatures dispatches nadoc:design-changed', async () => {
    fetch.mockResolvedValueOnce({
      ok: true, status: 200, headers: { get: () => null },
      json: async () => ({
        design: { feature_log_cursor: 6, feature_log: [], strands: [], helices: [] },
        validation: { results: [] },
        nucleotides: [],
      }),
    })
    const fired = vi.fn()
    window.addEventListener('nadoc:design-changed', fired)
    await seekFeatures(6)
    window.removeEventListener('nadoc:design-changed', fired)
    expect(fired).toHaveBeenCalled()
  })
})
