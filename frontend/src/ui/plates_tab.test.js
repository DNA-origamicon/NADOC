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
})
