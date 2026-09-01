// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  initPlateView: vi.fn(),
  plateView: { setData: vi.fn(), resetView: vi.fn() },
}))

vi.mock('./plate_view.js', () => ({ initPlateView: mocks.initPlateView }))
vi.mock('../scene/helix_renderer.js', () => ({
  buildStapleColorMap: () => new Map([['staple-1', 0xff0000]]),
}))

import { initPlatesTab } from './plates_tab.js'

describe('initPlatesTab', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <canvas id="plate-canvas"></canvas>
      <div id="plate-canvas-wrap"></div>
      <div id="plate-toolbar"></div>
      <div id="plate-tubes"></div>
      <section id="tab-content-plates"></section>
    `
    mocks.initPlateView.mockReset().mockReturnValue(mocks.plateView)
    mocks.plateView.setData.mockReset()
    mocks.plateView.resetView.mockReset()
  })

  it('normalizes visible staple records from design state', () => {
    let subscriber
    const state = {
      currentDesign: {
        id: 'd1',
        helices: [{ id: 'h1' }],
        strands: [{
          id: 'staple-1', strand_type: 'staple', sequence: 'ACGT',
          domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 3 }],
        }],
        extensions: [],
      },
      currentGeometry: [{ strand_id: 'staple-1' }],
      strandColors: {},
      strandGroups: [],
    }
    initPlatesTab({
      api: { savePlateLayout: vi.fn() },
      designRenderer: { getHelixCtrl: () => null },
      selectionManager: {},
      store: {
        getState: () => state,
        subscribe: handler => { subscriber = handler },
      },
    })
    subscriber(state)
    expect(mocks.plateView.setData).toHaveBeenCalledWith([
      expect.objectContaining({
        strandId: 'staple-1', color: '#ff0000', lengthNt: 4, sequence: 'ACGT',
      }),
    ], null)
  })

  it('includes linker and overhang-binding oligos in autofill records', () => {
    let subscriber
    const state = {
      currentDesign: {
        id: 'd1',
        helices: [{ id: 'h1' }],
        strands: [
          { id: 'linker-1', strand_type: 'linker', sequence: 'AAAA', domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 3 }] },
          { id: 'binder-1', strand_type: 'oh_binder', sequence: 'TTTTT', domains: [{ helix_id: 'h1', start_bp: 4, end_bp: 8 }] },
          { id: 'scaffold-1', strand_type: 'scaffold', sequence: 'CCCC', domains: [{ helix_id: 'h1', start_bp: 9, end_bp: 12 }] },
        ],
        extensions: [],
      },
      currentGeometry: [], strandColors: {}, strandGroups: [],
    }
    initPlatesTab({
      api: { savePlateLayout: vi.fn() },
      designRenderer: { getHelixCtrl: () => null },
      selectionManager: {},
      store: { getState: () => state, subscribe: handler => { subscriber = handler } },
    })

    subscriber(state)

    const records = mocks.plateView.setData.mock.calls.at(-1)[0]
    expect(records.map(record => record.strandId)).toEqual(['linker-1', 'binder-1'])
    expect(records.map(record => record.lengthNt)).toEqual([4, 5])
  })

  it('routes well selection through the canonical selection manager', () => {
    const selectionManager = { selectStrand: vi.fn(), clearSelection: vi.fn() }
    initPlatesTab({
      api: { savePlateLayout: vi.fn() },
      designRenderer: { getHelixCtrl: () => null },
      selectionManager,
      store: { getState: () => ({}), subscribe: vi.fn() },
    })
    const options = mocks.initPlateView.mock.calls[0][1]
    options.onStrandClick('strand-7')
    options.onStrandClick(null)
    expect(selectionManager.selectStrand).toHaveBeenCalledWith('strand-7')
    expect(selectionManager.clearSelection).toHaveBeenCalledOnce()
  })

  it('ignores its own layout save but refreshes layout-only undo and redo', () => {
    let subscriber
    let state = {
      currentDesign: {
        id: 'd1', helices: [{ id: 'h1' }], extensions: [], plate_layout: null,
        strands: [{
          id: 'staple-1', strand_type: 'staple', sequence: 'ACGT',
          domains: [{ helix_id: 'h1', start_bp: 0, end_bp: 3 }],
        }],
      },
      currentGeometry: [{ strand_id: 'staple-1' }],
      strandColors: {}, strandGroups: [],
    }
    const api = { savePlateLayout: vi.fn() }
    initPlatesTab({
      api,
      designRenderer: { getHelixCtrl: () => null },
      selectionManager: {},
      store: {
        getState: () => state,
        subscribe: handler => { subscriber = handler },
      },
    })
    subscriber(state)
    const callsAfterInitialRender = mocks.plateView.setData.mock.calls.length
    const tubed = {
      orientation: '8x12', plate_count: 1, wells: [],
      tubes: [{ strand_id: 'staple-1', reason: 'manual' }],
    }
    const options = mocks.initPlateView.mock.calls[0][1]

    // The local view already applied this layout before saving it. Its response
    // must not reset the view.
    options.onSaveLayout(tubed)
    state = { ...state, currentDesign: { ...state.currentDesign, plate_layout: tubed } }
    subscriber(state)
    expect(mocks.plateView.setData).toHaveBeenCalledTimes(callsAfterInitialRender)

    // Undo and redo are layout-only design changes, but each must repaint.
    state = { ...state, currentDesign: { ...state.currentDesign, plate_layout: null } }
    subscriber(state)
    expect(mocks.plateView.setData).toHaveBeenLastCalledWith(expect.any(Array), null)
    state = { ...state, currentDesign: { ...state.currentDesign, plate_layout: tubed } }
    subscriber(state)
    expect(mocks.plateView.setData).toHaveBeenLastCalledWith(expect.any(Array), tubed)
    expect(api.savePlateLayout).toHaveBeenCalledWith(tubed)
  })
})
