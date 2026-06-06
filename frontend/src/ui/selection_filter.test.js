import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computeFilterToggle, initSelectionFilter } from './selection_filter.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'

// All dataKeys the module touches (SEL_KEY_MAP + LEVEL_BTN). LEVEL_BTN's keys are
// clust/strand/line/ends/xover; SEL_KEY_MAP adds scaf/stap/loop/skip/ovhangs.
const DATA_KEYS = ['scaf', 'stap', 'clust', 'strand', 'line', 'ends', 'xover', 'loop', 'skip', 'ovhangs']

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

describe('initSelectionFilter (factory)', () => {
  let store, sm
  beforeEach(() => {
    mountSelectFilter()
    store = createMockStore({ selectableTypes: { ...FULL_SELECTABLE }, deformToolActive: false, translateRotateActive: false })
    sm = { resetDrill: vi.fn(), getDrillLock: vi.fn(() => null), setDrillLock: vi.fn() }
  })

  const make = () => initSelectionFilter({ store, getSelectionManager: () => sm })

  it('isManualSelect is false until a button is pinned, true after', () => {
    const f = make()
    f.attachFilterButtons()
    expect(f.isManualSelect()).toBe(false)
    document.querySelector('.sf-btn[data-key="clust"]').click()
    expect(f.isManualSelect()).toBe(true)
  })

  it('reflectDrillLevel lights only the matching level button (and is a no-op in manual mode)', () => {
    const f = make()
    f.reflectDrillLevel('cluster')
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="strand"]').classList.contains('active')).toBe(false)
    // null clears all
    f.reflectDrillLevel(null)
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
    // manual mode → no-op (pin a button first)
    f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="ends"]').click()
    f.reflectDrillLevel('cluster')
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
  })

  it('reflectLockOnButtons toggles sf-pinned on the matching level button; null clears', () => {
    const f = make()
    f.reflectLockOnButtons('domain') // → 'line'
    expect(document.querySelector('.sf-btn[data-key="line"]').classList.contains('sf-pinned')).toBe(true)
    f.reflectLockOnButtons(null)
    expect(document.querySelector('.sf-btn[data-key="line"]').classList.contains('sf-pinned')).toBe(false)
  })

  it('resetToAutoBaseline clears pins, writes baseline selectableTypes, sets button .active, resets drill', () => {
    const f = make()
    // pin something first so there is state to clear
    document.querySelector('.sf-btn[data-key="clust"]').classList.add('sf-pinned')
    f.resetToAutoBaseline()
    expect(document.querySelectorAll('.sf-btn.sf-pinned').length).toBe(0)
    const st = store.getState().selectableTypes
    expect(st.scaffold).toBe(true)
    expect(st.staples).toBe(true)
    expect(st.strands).toBe(true)
    expect(st.clusters).toBe(false)
    expect(document.querySelector('.sf-btn[data-key="scaf"]').classList.contains('active')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
    expect(sm.resetDrill).toHaveBeenCalled()
  })

  it('clicking a filter button pins it, writes selectableTypes, and resets drill', () => {
    const f = make()
    f.attachFilterButtons()
    const btn = document.querySelector('.sf-btn[data-key="clust"]')
    btn.click()
    expect(btn.classList.contains('sf-pinned')).toBe(true)
    expect(store.getState().selectableTypes.clusters).toBe(true)
    expect(sm.resetDrill).toHaveBeenCalled()
  })

  it('click is suppressed while a tool is active', () => {
    store.setState({ deformToolActive: true })
    const f = make()
    f.attachFilterButtons()
    const before = store.getState().selectableTypes
    document.querySelector('.sf-btn[data-key="clust"]').click()
    expect(store.getState().selectableTypes).toBe(before) // unchanged
    expect(f.isManualSelect()).toBe(false)
  })

  it('clicking clears an active drill-lock first', () => {
    sm.getDrillLock = vi.fn(() => 'cluster')
    const f = make()
    f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="strand"]').click()
    expect(sm.setDrillLock).toHaveBeenCalledWith(null)
  })

  it('un-pinning the last pinned button restores the auto baseline', () => {
    const f = make()
    f.attachFilterButtons()
    const btn = document.querySelector('.sf-btn[data-key="clust"]')
    btn.click()                       // pin → manual
    expect(f.isManualSelect()).toBe(true)
    btn.click()                       // un-pin → empty → resetToAutoBaseline
    expect(f.isManualSelect()).toBe(false)
    expect(store.getState().selectableTypes.strands).toBe(true) // baseline applied
  })

  it('manual-mode subscriber syncs button .active from selectableTypes', () => {
    const f = make()
    f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="clust"]').click() // enter manual mode
    // now flip a store field and confirm the subscriber reflects it
    store.setState({ selectableTypes: { ...store.getState().selectableTypes, ends: true } })
    expect(document.querySelector('.sf-btn[data-key="ends"]').classList.contains('active')).toBe(true)
  })

  it('filter-inactive class follows deform/translate tool activation', () => {
    const f = make()
    f.attachFilterButtons()
    store.setState({ deformToolActive: true })
    expect(document.getElementById('select-filter').classList.contains('filter-inactive')).toBe(true)
    store.setState({ deformToolActive: false })
    expect(document.getElementById('select-filter').classList.contains('filter-inactive')).toBe(false)
  })

  afterEach(() => clearDom())
})

describe('initSelectionFilter — drill v2 (selectionLevel)', () => {
  let store, sm, level
  beforeEach(() => {
    mountSelectFilter()
    store = createMockStore({ selectableTypes: { ...FULL_SELECTABLE }, deformToolActive: false, translateRotateActive: false })
    level = 'default'
    sm = {
      resetDrill: vi.fn(),
      getSelectionLevel: vi.fn(() => level),
      setSelectionLevel: vi.fn((l) => { level = l }),
    }
  })
  const makeV2 = () => initSelectionFilter({ store, getSelectionManager: () => sm, drillV2: true })

  it('clicking a level button sets the mapped selectionLevel (not selectableTypes)', () => {
    const f = makeV2(); f.attachFilterButtons()
    const before = store.getState().selectableTypes
    document.querySelector('.sf-btn[data-key="line"]').click()   // line → domain
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('domain')
    expect(store.getState().selectableTypes).toBe(before)        // level buttons no longer pin types
    expect(f.isManualSelect()).toBe(false)
  })

  it('clicking the engaged level button toggles back to default', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'cluster'
    document.querySelector('.sf-btn[data-key="clust"]').click()  // re-click engaged → default
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('the strand button maps to default', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'cluster'
    document.querySelector('.sf-btn[data-key="strand"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('default')
  })

  it('reflectDrillLevel paints active+sf-pinned on the engaged level (default→strand)', () => {
    const f = makeV2()
    f.reflectDrillLevel('xover')
    const xb = document.querySelector('.sf-btn[data-key="xover"]')
    expect(xb.classList.contains('active')).toBe(true)
    expect(xb.classList.contains('sf-pinned')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('sf-pinned')).toBe(false)
    // default lights the strand button
    f.reflectDrillLevel('default')
    expect(document.querySelector('.sf-btn[data-key="strand"]').classList.contains('active')).toBe(true)
    expect(document.querySelector('.sf-btn[data-key="xover"]').classList.contains('active')).toBe(false)
  })

  it('a type-visibility button (loops) still plain-toggles selectableTypes in v2', () => {
    const f = makeV2(); f.attachFilterButtons()
    document.querySelector('.sf-btn[data-key="loop"]').click()
    expect(store.getState().selectableTypes.loops).toBe(true)
    expect(sm.setSelectionLevel).not.toHaveBeenCalled()
  })

  afterEach(() => clearDom())
})
