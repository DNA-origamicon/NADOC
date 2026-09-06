// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initCrossTabSync } from './cross_tab_sync.js'

function harness(overrides = {}) {
  let messageHandler
  let storeHandler
  const state = {
    currentDesign: { id: 'design-1', metadata: { name: 'Alpha' } },
    assemblyActive: false,
    selection: { items: [] },
  }
  const deps = {
    api: { getDesign: vi.fn(), getGeometry: vi.fn(), importDesign: vi.fn() },
    assemblyRefresh: { requestRefresh: vi.fn() },
    broadcast: {
      emit: vi.fn(),
      isSameDoc: vi.fn(() => true),
      onMessage: vi.fn(handler => { messageHandler = handler; return vi.fn() }),
    },
    getPartEditContext: () => null,
    getWorkspacePath: () => 'parts/alpha.nadoc',
    lifecycleSync: {
      registerSiblingSave: vi.fn(),
      markSameDocActivity: vi.fn(),
      setReloadingFromSSE: vi.fn(),
    },
    selectionManager: { setMultiHighlight: vi.fn() },
    showToast: vi.fn(),
    store: {
      getState: () => state,
      subscribe: vi.fn(handler => { storeHandler = handler; return vi.fn() }),
    },
    syncBadge: { setSiblingCoediting: vi.fn(), syncLog: vi.fn() },
    ...overrides,
  }
  const controller = initCrossTabSync(deps)
  return { controller, deps, message: data => messageHandler(data), state, storeHandler }
}

describe('initCrossTabSync', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="editor-tab-dropdown"></div>'
  })

  it('requests peers and announces the current document', () => {
    const { deps } = harness()
    expect(deps.broadcast.emit).toHaveBeenCalledWith('editor-list-request')
    expect(deps.broadcast.emit).toHaveBeenCalledWith('doc-presence-request')
    expect(deps.broadcast.emit).toHaveBeenCalledWith('doc-presence', {
      designId: 'design-1',
      docName: 'Alpha',
      docAssembly: false,
      workspacePath: 'parts/alpha.nadoc',
    })
  })

  it('serializes same-document design refreshes through lifecycle suppression', async () => {
    const { deps, message } = harness()
    await message({ type: 'design-changed' })
    expect(deps.lifecycleSync.markSameDocActivity).toHaveBeenCalledOnce()
    expect(deps.lifecycleSync.setReloadingFromSSE.mock.calls).toEqual([[true], [false]])
    expect(deps.api.getDesign).toHaveBeenCalledOnce()
    expect(deps.api.getGeometry).toHaveBeenCalledOnce()
    expect(deps.api.getDesign.mock.invocationCallOrder[0])
      .toBeLessThan(deps.api.getGeometry.mock.invocationCallOrder[0])
  })

  it('skips geometry refresh when the sibling mutation is metadata-only', async () => {
    const { deps, message } = harness()
    await message({ type: 'design-changed', geometry_unchanged: true, source: 'editor-2' })
    expect(deps.api.getDesign).toHaveBeenCalledWith({ metadataOnly: true })
    expect(deps.api.getGeometry).not.toHaveBeenCalled()
    expect(deps.syncBadge.syncLog.mock.calls[0][1]).toBe('BC-SYNC-START')
    expect(deps.syncBadge.syncLog.mock.calls.at(-1)[1]).toBe('BC-SYNC-END')
  })

  it('fetches only changed helices for a reference-classification mutation', async () => {
    const { deps, message } = harness()
    await message({
      type: 'design-changed', source: 'editor-2', metadata_only: true,
      changed_helix_ids: ['h7', 'h9'],
    })
    expect(deps.api.getDesign).toHaveBeenCalledWith({ metadataOnly: true })
    expect(deps.api.getGeometry).toHaveBeenCalledWith(['h7', 'h9'])
    expect(deps.syncBadge.syncLog.mock.calls[0][2]).toContain('partial-geometry(2)')
  })

  it('owns editor discovery and removes departed editors', async () => {
    const { message } = harness()
    await message({
      type: 'editor-announce', source: 'tab-2', windowName: 'editor-2', designName: 'Beta',
    })
    const dropdown = document.getElementById('editor-tab-dropdown')
    expect(dropdown.textContent).toContain('Beta')
    expect(dropdown.style.display).toBe('')
    await message({ type: 'editor-goodbye', source: 'tab-2' })
    expect(dropdown.style.display).toBe('none')
  })
})

describe('selection broadcasts', () => {
  const selection = (...ids) => ({ items: ids.map(id => ({ kind: 'strand', id })) })

  it('does not echo an unchanged selection after design reconciliation', () => {
    const { deps, storeHandler } = harness()
    deps.broadcast.emit.mockClear()
    storeHandler({ selection: selection('merged') }, { selection: selection('merged') })
    expect(deps.broadcast.emit).not.toHaveBeenCalledWith('selection-changed', expect.anything())
  })

  it('ignores order-only changes in the selected strand set', () => {
    const { deps, storeHandler } = harness()
    deps.broadcast.emit.mockClear()
    storeHandler({ selection: selection('b', 'a') }, { selection: selection('a', 'b') })
    expect(deps.broadcast.emit).not.toHaveBeenCalledWith('selection-changed', expect.anything())
  })

  it('still broadcasts a different positive selection', () => {
    const { deps, storeHandler } = harness()
    deps.broadcast.emit.mockClear()
    storeHandler({ selection: selection('b') }, { selection: selection('a') })
    expect(deps.broadcast.emit).toHaveBeenCalledWith('selection-changed', { strandIds: ['b'] })
  })
})
