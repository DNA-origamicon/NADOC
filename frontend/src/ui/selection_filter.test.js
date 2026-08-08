import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { collapsedSelectable, computeFilterToggle, initSelectionFilter } from './selection_filter.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { clearDom } from '../test-helpers/factory_dom.js'

// All dataKeys the module touches (SEL_KEY_MAP + LEVEL_BTN). LEVEL_BTN's keys are
// clust/strand/line/ends/xover/base; SEL_KEY_MAP adds scaf/stap/loop/skip/ovhangs.
// `base` is level-only — it has no selectableTypes key, so it lives in LEVEL_ONLY_BTNS.
const DATA_KEYS = ['scaf', 'stap', 'clust', 'strand', 'line', 'ends', 'xover', 'base', 'loop', 'skip', 'ovhangs']

/**
 * Build the collapsed picker: #select-filter > trigger + #select-filter-menu, with a
 * .sf-btn[data-key] per key inside the menu (mirrors index.html, including the
 * `default` row and each row's <svg> that the trigger clones).
 */
function mountSelectFilter() {
  document.body.innerHTML = ''
  const wrap = document.createElement('div')
  wrap.id = 'select-filter'
  wrap.innerHTML = `
    <button id="select-filter-trigger" class="sf-trigger">
      <span class="sf-trigger-icon"></span>
      <span class="sf-trigger-text"></span>
      <span class="sf-trigger-note"></span>
    </button>
    <div id="select-filter-menu" hidden><div class="sf-menu-marker"></div></div>`
  const menu = wrap.querySelector('#select-filter-menu')
  const btns = {}
  for (const dk of [...DATA_KEYS, 'default']) {
    const b = document.createElement('button')
    b.className = 'sf-btn'
    b.setAttribute('data-key', dk)
    b.innerHTML = '<svg></svg><span class="sf-label-text"></span>'
    menu.appendChild(b)
    btns[dk] = b
  }
  document.body.appendChild(wrap)
  return { wrap, menu, btns, trigger: wrap.querySelector('#select-filter-trigger') }
}

const isMenuOpen = () => !document.getElementById('select-filter-menu').hidden

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
    // default (no engaged level) lights the explicit `default` row and nothing else
    f.reflectDrillLevel('default')
    expect(document.querySelector('.sf-btn[data-key="strand"]').classList.contains('active')).toBe(false)
    expect(document.querySelector('.sf-btn[data-key="clust"]').classList.contains('active')).toBe(false)
    expect(document.querySelector('.sf-btn[data-key="default"]').classList.contains('active')).toBe(true)
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

describe('collapsedSelectable (pure)', () => {
  const T = o => ({ ...FULL_SELECTABLE, ...o })

  it('reports the engaged level', () => {
    expect(collapsedSelectable({ selectionLevel: 'domain', selectableTypes: T() }))
      .toEqual({ key: 'line', label: 'dom', note: '' })
    expect(collapsedSelectable({ selectionLevel: 'cluster', selectableTypes: T() }).label).toBe('clust')
  })

  it('default level reports "default"', () => {
    expect(collapsedSelectable({ selectionLevel: 'default', selectableTypes: T() }))
      .toEqual({ key: 'default', label: 'default', note: '' })
  })

  it('an unknown level falls back to default', () => {
    expect(collapsedSelectable({ selectionLevel: 'bogus', selectableTypes: T() }).key).toBe('default')
  })

  it('an engaged exclusive gate OUTRANKS the level (it wins clicks + lasso)', () => {
    expect(collapsedSelectable({ selectionLevel: 'domain', selectableTypes: T({ overhangs: true }) }))
      .toEqual({ key: 'ovhangs', label: 'ovhg', note: '' })
    expect(collapsedSelectable({ selectionLevel: 'domain', selectableTypes: T({ loops: true }) }).label).toBe('loop')
    expect(collapsedSelectable({ selectionLevel: 'base', selectableTypes: T({ skips: true }) }).label).toBe('skip')
  })

  it('a scaffold/staple restriction shows as a note', () => {
    expect(collapsedSelectable({ selectionLevel: 'strand', selectableTypes: T({ staples: false }) }).note).toBe('scaf only')
    expect(collapsedSelectable({ selectionLevel: 'strand', selectableTypes: T({ scaffold: false }) }).note).toBe('stap only')
    expect(collapsedSelectable({ selectionLevel: 'strand', selectableTypes: T({ scaffold: false, staples: false }) }).note).toBe('none')
  })

  it('no note while an exclusive gate is up (it clears scaf+stap by design)', () => {
    expect(collapsedSelectable({
      selectionLevel: 'strand', selectableTypes: T({ scaffold: false, staples: false, loops: true }),
    }).note).toBe('')
  })

  it('survives an empty argument', () => {
    expect(collapsedSelectable()).toEqual({ key: 'default', label: 'default', note: 'none' })
  })
})

describe('initSelectionFilter — collapsed trigger + menu', () => {
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
  const trigger = () => document.getElementById('select-filter-trigger')

  it('the trigger toggles the menu open and closed', () => {
    const f = makeV2(); f.attachFilterButtons()
    expect(isMenuOpen()).toBe(false)
    trigger().click()
    expect(isMenuOpen()).toBe(true)
    trigger().click()
    expect(isMenuOpen()).toBe(false)
  })

  it('picking a LEVEL closes the menu; toggling a GATE leaves it open', () => {
    const f = makeV2(); f.attachFilterButtons()
    trigger().click()
    document.querySelector('.sf-btn[data-key="loop"]').click()
    expect(isMenuOpen()).toBe(true)                       // gate → stay open
    document.querySelector('.sf-btn[data-key="ends"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('end')
    expect(isMenuOpen()).toBe(false)                      // level → close
  })

  it('the default row sets the default level directly and closes', () => {
    const f = makeV2(); f.attachFilterButtons()
    level = 'xover'
    trigger().click()
    document.querySelector('.sf-btn[data-key="default"]').click()
    expect(sm.setSelectionLevel).toHaveBeenCalledWith('default')
    expect(store.getState().selectableTypes).toEqual(FULL_SELECTABLE)  // no gate touched
    expect(isMenuOpen()).toBe(false)
  })

  it('a pointerdown outside closes the menu; inside does not', () => {
    const f = makeV2(); f.attachFilterButtons()
    trigger().click()
    document.getElementById('select-filter-menu').dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(isMenuOpen()).toBe(true)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(isMenuOpen()).toBe(false)
  })

  it('Escape closes the menu', () => {
    const f = makeV2(); f.attachFilterButtons()
    trigger().click()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(isMenuOpen()).toBe(false)
  })

  it('activating a tool locks the row AND closes an open menu', () => {
    const f = makeV2(); f.attachFilterButtons()
    trigger().click()
    store.setState({ translateRotateActive: true })
    expect(isMenuOpen()).toBe(false)
    expect(document.getElementById('select-filter').classList.contains('filter-inactive')).toBe(true)
  })

  it('the trigger follows the level, and a gate overrides it', () => {
    const f = makeV2(); f.attachFilterButtons()
    expect(trigger().querySelector('.sf-trigger-text').textContent).toBe('default')
    f.reflectDrillLevel('base')
    expect(trigger().dataset.key).toBe('base')
    expect(trigger().querySelector('.sf-trigger-text').textContent).toBe('base')
    store.setState({ selectableTypes: { ...store.getState().selectableTypes, overhangs: true } })
    expect(trigger().querySelector('.sf-trigger-text').textContent).toBe('ovhg')
  })

  it('the trigger clones the reported row’s icon', () => {
    const f = makeV2(); f.attachFilterButtons()
    f.reflectDrillLevel('xover')
    expect(trigger().querySelector('.sf-trigger-icon svg')).toBeTruthy()
  })
})

describe('initSelectionFilter — Tab flash', () => {
  let store, sm
  beforeEach(() => {
    vi.useFakeTimers()
    mountSelectFilter()
    store = createMockStore({ selectableTypes: { ...FULL_SELECTABLE }, deformToolActive: false, translateRotateActive: false })
    sm = { getSelectionLevel: vi.fn(() => 'default'), setSelectionLevel: vi.fn() }
  })
  afterEach(() => { vi.useRealTimers(); clearDom() })
  const makeV2 = () => initSelectionFilter({ store, getSelectionManager: () => sm })

  it('pops the menu open read-only and closes it again', () => {
    const f = makeV2(); f.attachFilterButtons()
    f.flashLevelChange('strand', 'domain')
    const menu = document.getElementById('select-filter-menu')
    expect(isMenuOpen()).toBe(true)
    expect(menu.classList.contains('sf-flash')).toBe(true)   // click-through while flashing
    vi.advanceTimersByTime(260)
    expect(isMenuOpen()).toBe(false)
    expect(menu.classList.contains('sf-flash')).toBe(false)
  })

  it('a repeat flash restarts the timer instead of closing mid-cycle', () => {
    const f = makeV2(); f.attachFilterButtons()
    f.flashLevelChange('strand', 'domain')
    vi.advanceTimersByTime(200)
    f.flashLevelChange('domain', 'end')
    vi.advanceTimersByTime(200)
    expect(isMenuOpen()).toBe(true)      // would have closed at 250 without the restart
    vi.advanceTimersByTime(100)
    expect(isMenuOpen()).toBe(false)
  })

  it('leaves a hand-opened menu open', () => {
    const f = makeV2(); f.attachFilterButtons()
    document.getElementById('select-filter-trigger').click()
    f.flashLevelChange('strand', 'domain')
    vi.advanceTimersByTime(500)
    expect(isMenuOpen()).toBe(true)
    expect(document.getElementById('select-filter-menu').classList.contains('sf-flash')).toBe(false)
  })

  it('the marker lands on the incoming level’s row', () => {
    const f = makeV2(); f.attachFilterButtons()
    const marker = document.querySelector('.sf-menu-marker')
    f.flashLevelChange('strand', 'xover')
    // jsdom reports offsetTop 0 for everything, so assert the transition was armed
    // toward a row rather than the pixel value.
    expect(marker.style.transition).toContain('top')
    expect(marker.style.top).toBe('0px')
  })
})
