import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computeFilterToggle, initSelectionFilter } from './selection_filter.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'

// All dataKeys the module touches (SEL_KEY_MAP + LEVEL_BTN). LEVEL_BTN's keys are
// clust/strand/line/ends/xover/base; SEL_KEY_MAP adds scaf/stap/loop/skip/ovhangs.
// `base` is level-only — it has no selectableTypes key, so it lives in LEVEL_ONLY_BTNS.
const DATA_KEYS = ['scaf', 'stap', 'clust', 'strand', 'line', 'ends', 'xover', 'base', 'loop', 'skip', 'ovhangs']

/** Build the #select-filter container with a .sf-btn[data-key] per key. */
function mountSelectFilter() {
  document.body.innerHTML = ''
  const wrap = document.createElement('div')
  wrap.id = 'select-filter'
  const btns = {}
  for (const dk of DATA_KEYS) {
    const b = document.createElement('button')
    b.className = 'sf-btn'
    b.setAttribute('data-key', dk)
    wrap.appendChild(b)
    btns[dk] = b
  }
  document.body.appendChild(wrap)
  return { wrap, btns }
}

const FULL_SELECTABLE = {
  scaffold: true, staples: true, clusters: false, strands: true, domains: false,
  ends: false, crossoverArcs: false, loops: false, skips: false, extensions: false, overhangs: false,
}
const ALL_KEYS = ['scaffold', 'staples', 'clusters', 'strands', 'domains', 'ends', 'crossoverArcs', 'loops', 'skips', 'overhangs']

describe('computeFilterToggle (pure)', () => {
  it('plain key toggles off→on', () => {
    const out = computeFilterToggle({ selectableTypes: { ...FULL_SELECTABLE, clusters: false }, storeKey: 'clusters', allKeys: ALL_KEYS, preLoopSkip: null })
    expect(out.selectableTypes.clusters).toBe(true)
    expect(out.preLoopSkip).toBe(null)
    // other fields untouched
    expect(out.selectableTypes.scaffold).toBe(true)
  })

  it('plain key toggles on→off', () => {
    const out = computeFilterToggle({ selectableTypes: { ...FULL_SELECTABLE, strands: true }, storeKey: 'strands', allKeys: ALL_KEYS, preLoopSkip: null })
    expect(out.selectableTypes.strands).toBe(false)
  })

  it('turning on loops from all-off snapshots prior state and clears everything else', () => {
    const out = computeFilterToggle({ selectableTypes: FULL_SELECTABLE, storeKey: 'loops', allKeys: ALL_KEYS, preLoopSkip: null })
    expect(out.selectableTypes.loops).toBe(true)
    // everything else in allKeys is false
    for (const k of ALL_KEYS) if (k !== 'loops') expect(out.selectableTypes[k]).toBe(false)
    // snapshot captured the FULL prior state
    expect(out.preLoopSkip).toEqual(FULL_SELECTABLE)
  })

  it('cleared selectableTypes only contains allKeys (drops keys like extensions)', () => {
    const out = computeFilterToggle({ selectableTypes: FULL_SELECTABLE, storeKey: 'skips', allKeys: ALL_KEYS, preLoopSkip: null })
    expect('extensions' in out.selectableTypes).toBe(false)
    expect(out.selectableTypes.skips).toBe(true)
  })

  it('turning on a SECOND loop-group key while one is on does NOT re-snapshot', () => {
    const cur = { ...FULL_SELECTABLE, loops: true, scaffold: false, strands: false, staples: false }
    const priorSnap = { ...FULL_SELECTABLE }
    const out = computeFilterToggle({ selectableTypes: cur, storeKey: 'overhangs', allKeys: ALL_KEYS, preLoopSkip: priorSnap })
    // overhangs was off → turning on; but loops is on so the snapshot condition fails → keep prior snapshot
    expect(out.preLoopSkip).toBe(priorSnap)
    expect(out.selectableTypes.overhangs).toBe(true)
    expect(out.selectableTypes.loops).toBe(false) // cleared
  })

  it('turning off a loop-group key WITH snapshot restores the snapshot and clears preLoopSkip', () => {
    const snap = { ...FULL_SELECTABLE, clusters: true }
    const out = computeFilterToggle({ selectableTypes: { ...FULL_SELECTABLE, loops: true }, storeKey: 'loops', allKeys: ALL_KEYS, preLoopSkip: snap })
    expect(out.selectableTypes).toEqual(snap)
    expect(out.preLoopSkip).toBe(null)
  })

  it('turning off a loop-group key WITHOUT snapshot just clears that one', () => {
    const cur = { ...FULL_SELECTABLE, skips: true }
    const out = computeFilterToggle({ selectableTypes: cur, storeKey: 'skips', allKeys: ALL_KEYS, preLoopSkip: null })
    expect(out.selectableTypes.skips).toBe(false)
    expect(out.selectableTypes.scaffold).toBe(true) // rest untouched
    expect(out.preLoopSkip).toBe(null)
  })
})

describe('initSelectionFilter — selectionLevel + visibility gates', () => {
  let store, sm, level
  beforeEach(() => {
    mountSelectFilter()
    store = createMockStore({ selectableTypes: { ...FULL_SELECTABLE }, deformToolActive: false, translateRotateActive: false })
    level = 'default'
    sm = {
      getSelectionLevel: vi.fn(() => level),
      setSelectionLevel: vi.fn((l) => { level = l }),
    }
  })
  const makeV2 = () => initSelectionFilter({ store, getSelectionManager: () => sm })

  it('clicking a level button sets the mapped selectionLevel (not selectableTypes)', () => {
    const f = makeV2(); f.attachFilterButtons()
    const before = store.getState().selectableTypes
    document.querySelector('.sf-btn[data-key="line"]').click()   // line → domain
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('domain')
    expect(store.getState().selectableTypes).toBe(before)        // level buttons no longer pin types
  })

  it('clicking a tool while active suppresses the click', () => {
    store.setState({ deformToolActive: true })
    const f = makeV2(); f.attachFilterButtons()
    const before = store.getState().selectableTypes
    document.querySelector('.sf-btn[data-key="clust"]').click()
    expect(sm.setSelectionLevel).not.toHaveBeenCalled()
    expect(store.getState().selectableTypes).toBe(before)
  })

  it('filter-inactive class follows deform/translate tool activation', () => {
    const f = makeV2(); f.attachFilterButtons()
    store.setState({ deformToolActive: true })
    expect(document.getElementById('select-filter').classList.contains('filter-inactive')).toBe(true)
    store.setState({ deformToolActive: false })
    expect(document.getElementById('select-filter').classList.contains('filter-inactive')).toBe(false)
  })

  it('a visibility-gate subscriber syncs button .active from selectableTypes', () => {
    const f = makeV2(); f.attachFilterButtons()
    store.setState({ selectableTypes: { ...store.getState().selectableTypes, loops: true } })
    expect(document.querySelector('.sf-btn[data-key="loop"]').classList.contains('active')).toBe(true)
  })

  it('clicking the engaged level button toggles back to default', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'cluster'
    document.querySelector('.sf-btn[data-key="clust"]').click()  // re-click engaged → default
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('the strand button maps to the distinct strand level (not default)', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'cluster'
    document.querySelector('.sf-btn[data-key="strand"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('strand')
  })

  it('reflectDrillLevel paints ONLY .active (no red sf-pinned); default lights no button', () => {
    const f = makeV2()
    f.reflectDrillLevel('xover')
    const xb = document.querySelector('.sf-btn[data-key="xover"]')
    expect(xb.classList.contains('active')).toBe(true)
    expect(xb.classList.contains('sf-pinned')).toBe(false)   // red box removed
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
    // strand level lights the strand button
    f.reflectDrillLevel('strand')
    expect(document.querySelector('.sf-btn[data-key="strand"]').classList.contains('active')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="xover"]').classList.contains('active')).toBe(false)
    // default (no engaged level) lights NO level button
    f.reflectDrillLevel('default')
    expect(document.querySelector('.sf-btn[data-key="strand"]').classList.contains('active')).toBe(false)
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
  })

  // The base button has NO SEL_KEY_MAP row (it gates nothing), so it only gets a click
  // listener via LEVEL_ONLY_BTNS. Without that it would light from Tab and do nothing.
  it('the base button sets the base level and never touches selectableTypes', () => {
    const f = makeV2(); f.attachFilterButtons()
    const before = store.getState().selectableTypes
    document.querySelector('.sf-btn[data-key="base"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('base')
    expect(store.getState().selectableTypes).toBe(before)
  })

  it('re-clicking the engaged base button toggles back to default', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'base'
    document.querySelector('.sf-btn[data-key="base"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('reflectDrillLevel lights the base button and clears the others', () => {
    const f = makeV2()
    f.reflectDrillLevel('base')
    expect(document.querySelector('.sf-btn[data-key="base"]').classList.contains('active')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="xover"]').classList.contains('active')).toBe(false)
    f.reflectDrillLevel('xover')
    expect(document.querySelector('.sf-btn[data-key="base"]').classList.contains('active')).toBe(false)
  })

  it('the base button is suppressed while a tool is active, like every level button', () => {
    store.setState({ deformToolActive: true })
    const f = makeV2(); f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="base"]').click()
    expect(sm.setSelectionLevel).not.toHaveBeenCalled()
  })

  it('a type-visibility button (loops) still plain-toggles selectableTypes in v2', () => {
    const f = makeV2(); f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="loop"]').click()
    expect(store.getState().selectableTypes.loops).toBe(true)
    expect(sm.setSelectionLevel).not.toHaveBeenCalled()
  })

  afterEach(() => clearDom())
})
