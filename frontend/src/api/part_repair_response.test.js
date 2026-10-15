import { expect, it, vi } from 'vitest'
import { createPartRepairResponse } from './part_repair_response.js'
import { createDesignRevisionTracker } from './design_revisions.js'
import { createMockStore } from '../test-helpers/mock_store.js'

function setup() {
  const design = { id: 'part', active_loadout_id: 'main' }, geometry = [{ identity: 'retained' }]
  const store = createMockStore({ currentDesign: design, currentGeometry: geometry, repairMetadata: null })
  const revisions = createDesignRevisionTracker(), syncDesign = vi.fn()
  revisions.acceptDesign({ design, revision: 4 })
  const adapter = createPartRepairResponse({ store, revisions, getDocId: () => 'doc', syncDesign })
  return { adapter, store, revisions, syncDesign, design, geometry,
    context: { docId: 'doc', designId: 'part', loadoutId: 'main', revision: 4 } }
}

it('acknowledges only repair metadata without changing geometry/design or caching actions', () => {
  const { adapter, store, revisions, context, design, geometry, syncDesign } = setup()
  const summary = { draft_id: 'proposal', generation: 0, status: 'pending' }
  expect(adapter.acknowledge({ design_id: 'part', revision: 5, repair_draft: summary, draft: { actions: ['private'] } }, context)).toBe(true)
  expect(revisions.current()).toBe(5)
  expect(store.getState()).toEqual({ currentDesign: design, currentGeometry: geometry,
    repairMetadata: { designId: 'part', revision: 5, summary } })
  expect(store.getState().currentDesign).toBe(design)
  expect(syncDesign).not.toHaveBeenCalled()
})

it('keeps newer summaries when delayed full geometry arrives', () => {
  const { adapter, store, context, design } = setup()
  adapter.acknowledge({ design_id: 'part', revision: 6, repair_draft: { generation: 2 } }, context)
  expect(adapter.summaryPatch({ design, revision: 5, repair_draft: { generation: 1 } })).toEqual({})
  expect(adapter.summaryPatch({ design: { id: 'different' }, revision: 0 })).toEqual({ repairMetadata: null })
  expect(store.getState().repairMetadata.summary.generation).toBe(2)
})

it('ignores legacy design fragments without an identity when no repair metadata exists', () => {
  const { adapter, store } = setup()
  expect(store.getState().repairMetadata).toBeNull()
  expect(adapter.summaryPatch({ design: {}, revision: 5 })).toEqual({})
  expect(adapter.summaryPatch({ design: { id: null }, revision: 5 })).toEqual({})
})

it.each([{ docId: 'other' }, { designId: 'other' }, { loadoutId: 'other' }, { revision: 3 }])('rejects mismatched metadata context %s', change => {
  const { adapter, store, context } = setup()
  expect(adapter.acknowledge({ design_id: 'part', revision: 5 }, { ...context, ...change })).toBe(false)
  expect(store.getState().repairMetadata).toBeNull()
})

it('uses normal design synchronization only for an explicit current commit', () => {
  const { adapter, context, syncDesign, design } = setup()
  const response = { design, revision: 5 }
  adapter.apply(response, context)
  expect(syncDesign).toHaveBeenCalledExactlyOnceWith(response)
  expect(() => adapter.apply(response, { ...context, revision: 3 })).toThrow(/older document/)
})
