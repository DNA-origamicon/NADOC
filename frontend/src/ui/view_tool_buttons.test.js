/**
 * Tests for ui/view_tool_buttons.js — the right-panel `.vt-btn` row factory and
 * its pure length-heatmap colour-map core.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { buildLengthHeatmapColors, initViewToolButtons } from './view_tool_buttons.js'

// heatmapHex extremes (pinned by hand from scene/color_util.js): a min-length
// strand (≤14 nt → t=0 → hue 240) is blue 0x0D0DF2; a max-length strand
// (≥60 nt → t=1 → hue 0) is red 0xF20D0D.
const BLUE = 0x0d0df2
const RED  = 0xf20d0d

describe('buildLengthHeatmapColors (pure)', () => {
  it('keys staples by id, skips scaffold, maps short→blue / long→red', () => {
    const strands = [
      { id: 'sc', strand_type: 'scaffold', domains: [{ start_bp: 0, end_bp: 100 }] },
      { id: 'a',  strand_type: 'staple',   domains: [{ start_bp: 0, end_bp: 13 }] },  // 14 nt
      { id: 'b',  strand_type: 'staple',   domains: [{ start_bp: 0, end_bp: 59 }] },  // 60 nt
    ]
    const m = buildLengthHeatmapColors(strands)
    expect(m.has('sc')).toBe(false)
    expect(m.get('a')).toBe(BLUE)
    expect(m.get('b')).toBe(RED)
    expect(m.size).toBe(2)
  })

  it('returns an empty map for null / empty input', () => {
    expect(buildLengthHeatmapColors(undefined).size).toBe(0)
    expect(buildLengthHeatmapColors([]).size).toBe(0)
  })

  it('treats a domainless strand as length 0 → blue floor', () => {
    const m = buildLengthHeatmapColors([{ id: 'x', strand_type: 'staple' }])
    expect(m.get('x')).toBe(BLUE)
  })
})

const VT = ['lengthHeatmap', 'sequences', 'undefinedBases', 'grid', 'overhangNames',
            'expanded', 'deform', 'unfold', 'cadnano2d']

function mountVtDom() {
  document.body.innerHTML = ''
  const legend = document.createElement('div')
  legend.id = 'length-heatmap-legend'
  document.body.appendChild(legend)
  const buttons = {}
  for (const vt of VT) {
    const b = document.createElement('button')
    b.className = 'vt-btn'
    b.setAttribute('data-vt', vt)
    document.body.appendChild(b)
    buttons[vt] = b
  }
  // menu pill targets used by setMenuToggle in real code (here setMenuToggle is mocked)
  return { legend, buttons }
}

function makeDeps(initialState = {}) {
  const store = createMockStore({
    showSequences: false, showOverhangNames: false,
    unfoldActive: false, cadnanoActive: false, deformVisuActive: false,
    currentDesign: null,
    ...initialState,
  })
  let _undef = false
  const deps = {
    store,
    scene: { add: vi.fn() },
    designRenderer: {
      getBackboneEntries: vi.fn(() => []),
      getSlabEntries: vi.fn(() => []),
      getConeEntries: vi.fn(() => []),
      setEntryColor: vi.fn(),
      clearUndefinedHighlight: vi.fn(),
    },
    expandedSpacing: { isActive: vi.fn(() => false), toggle: vi.fn() },
    setMenuToggle: vi.fn(),
    refreshUndefinedHighlight: vi.fn(),
    getUndefinedHighlightOn: () => _undef,
    setUndefinedHighlightOn: vi.fn((v) => { _undef = v }),
    toggleDeformView: vi.fn(),
    toggleUnfold: vi.fn(),
    toggleCadnano: vi.fn(),
  }
  return deps
}

beforeEach(() => { document.body.innerHTML = '' })

describe('initViewToolButtons', () => {
  it('adds a grid helper to the scene and returns its API', () => {
    const deps = makeDeps()
    const api = initViewToolButtons(deps)
    expect(deps.scene.add).toHaveBeenCalledTimes(1)
    const grid = deps.scene.add.mock.calls[0][0]
    expect(grid.visible).toBe(false)
    expect(typeof api.syncButtons).toBe('function')
    expect(api.isLengthHeatmapOn()).toBe(false)
  })

  it('does not throw when the vt buttons are absent', () => {
    const deps = makeDeps()
    expect(() => initViewToolButtons(deps)).not.toThrow()
  })

  it('lengthHeatmap click colours staple entries, second click reverts', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps({
      currentDesign: { strands: [{ id: 'a', strand_type: 'staple', domains: [{ start_bp: 0, end_bp: 13 }] }] },
    })
    const entry = { nuc: { strand_id: 'a' }, defaultColor: 0x123456 }
    deps.designRenderer.getBackboneEntries = vi.fn(() => [entry])
    const api = initViewToolButtons(deps)

    buttons.lengthHeatmap.click()
    expect(api.isLengthHeatmapOn()).toBe(true)
    expect(deps.designRenderer.setEntryColor).toHaveBeenCalledWith(entry, BLUE)
    expect(document.getElementById('length-heatmap-legend').classList.contains('visible')).toBe(true)
    expect(buttons.lengthHeatmap.classList.contains('active')).toBe(true)

    deps.designRenderer.setEntryColor.mockClear()
    buttons.lengthHeatmap.click()
    expect(api.isLengthHeatmapOn()).toBe(false)
    expect(deps.designRenderer.setEntryColor).toHaveBeenCalledWith(entry, 0x123456)  // defaultColor
    expect(document.getElementById('length-heatmap-legend').classList.contains('visible')).toBe(false)
  })

  it('sequences click flips the store flag and sets the menu pill', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps({ showSequences: false })
    initViewToolButtons(deps)
    buttons.sequences.click()
    expect(deps.store.getState().showSequences).toBe(true)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-sequences', true)
  })

  it('undefinedBases click turns highlight on (refresh) then off (clear)', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps()
    initViewToolButtons(deps)

    buttons.undefinedBases.click()
    expect(deps.setUndefinedHighlightOn).toHaveBeenLastCalledWith(true)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-undefined-bases', true)
    expect(deps.refreshUndefinedHighlight).toHaveBeenCalledTimes(1)
    expect(deps.designRenderer.clearUndefinedHighlight).not.toHaveBeenCalled()

    buttons.undefinedBases.click()
    expect(deps.setUndefinedHighlightOn).toHaveBeenLastCalledWith(false)
    expect(deps.designRenderer.clearUndefinedHighlight).toHaveBeenCalledTimes(1)
    expect(deps.refreshUndefinedHighlight).toHaveBeenCalledTimes(1)  // not called again
  })

  it('grid click toggles GridHelper visibility (reflected on the button)', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps()
    const api = initViewToolButtons(deps)
    const grid = deps.scene.add.mock.calls[0][0]
    buttons.grid.click()
    expect(grid.visible).toBe(true)
    expect(buttons.grid.classList.contains('active')).toBe(true)
    buttons.grid.click()
    expect(grid.visible).toBe(false)
    expect(buttons.grid.classList.contains('active')).toBe(false)
    expect(api).toBeTruthy()
  })

  it('overhangNames click flips the store flag and sets the menu pill', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps({ showOverhangNames: false })
    initViewToolButtons(deps)
    buttons.overhangNames.click()
    expect(deps.store.getState().showOverhangNames).toBe(true)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-overhang-names', true)
  })

  it('expanded / deform / unfold / cadnano2d clicks delegate to their callbacks', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps()
    initViewToolButtons(deps)
    buttons.expanded.click()
    expect(deps.expandedSpacing.toggle).toHaveBeenCalledTimes(1)
    buttons.deform.click()
    expect(deps.toggleDeformView).toHaveBeenCalledTimes(1)
    buttons.unfold.click()
    expect(deps.toggleUnfold).toHaveBeenCalledTimes(1)
    buttons.cadnano2d.click()
    expect(deps.toggleCadnano).toHaveBeenCalledTimes(1)
  })

  it('store change re-syncs the active classes from state', () => {
    const { buttons } = mountVtDom()
    const deps = makeDeps({ showSequences: false, unfoldActive: false })
    initViewToolButtons(deps)
    expect(buttons.sequences.classList.contains('active')).toBe(false)
    deps.store.setState({ showSequences: true, unfoldActive: true })
    expect(buttons.sequences.classList.contains('active')).toBe(true)
    expect(buttons.unfold.classList.contains('active')).toBe(true)
  })

  it('re-applies the heatmap on design change while it is on, not while off', () => {
    const { buttons } = mountVtDom()
    const design1 = { strands: [{ id: 'a', strand_type: 'staple', domains: [{ start_bp: 0, end_bp: 13 }] }] }
    const deps = makeDeps({ currentDesign: design1 })
    const entry = { nuc: { strand_id: 'a' }, defaultColor: 0x000000 }
    deps.designRenderer.getBackboneEntries = vi.fn(() => [entry])
    initViewToolButtons(deps)

    // off → a design change does NOT recolour
    deps.store.setState({ currentDesign: { ...design1 } })
    expect(deps.designRenderer.setEntryColor).not.toHaveBeenCalled()

    // turn on, then a design change recolours
    buttons.lengthHeatmap.click()
    deps.designRenderer.setEntryColor.mockClear()
    deps.store.setState({ currentDesign: { ...design1 } })
    expect(deps.designRenderer.setEntryColor).toHaveBeenCalledWith(entry, BLUE)
  })
})
