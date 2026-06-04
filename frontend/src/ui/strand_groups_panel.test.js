/**
 * Unit tests for the strand groups panel ("Staple Groups").
 *
 *   effectiveStrandColors / groupStrandsByColor / trimGroupsRemovingStrands /
 *   selectableGroupStrandIds — pure cores, plain data (no mocks).
 *   initStrandGroupsPanel    — factory wiring, jsdom DOM + mock store/selectionManager.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  effectiveStrandColors,
  groupStrandsByColor,
  trimGroupsRemovingStrands,
  selectableGroupStrandIds,
  initStrandGroupsPanel,
} from './strand_groups_panel.js'

// ── effectiveStrandColors (pure) ────────────────────────────────────────────────

describe('effectiveStrandColors', () => {
  it('returns a copy of base colors when there are no groups', () => {
    const base = { s1: 0x111111 }
    const out = effectiveStrandColors(base, [])
    expect(out).toEqual({ s1: 0x111111 })
    expect(out).not.toBe(base)          // copy, not the same ref
  })

  it('handles null/undefined inputs', () => {
    expect(effectiveStrandColors(null, null)).toEqual({})
    expect(effectiveStrandColors(undefined, undefined)).toEqual({})
  })

  it('applies group color overrides parsed from #rrggbb', () => {
    const out = effectiveStrandColors({ s1: 0x000000 }, [
      { color: '#ff0000', strandIds: ['s1', 's2'] },
    ])
    expect(out).toEqual({ s1: 0xff0000, s2: 0xff0000 })
  })

  it('skips groups with no color and later groups override earlier ones', () => {
    const out = effectiveStrandColors({}, [
      { strandIds: ['s1'] },                       // no color → ignored
      { color: '#00ff00', strandIds: ['s1'] },
      { color: '#0000ff', strandIds: ['s1'] },     // wins
    ])
    expect(out).toEqual({ s1: 0x0000ff })
  })
})

// ── groupStrandsByColor (pure) ──────────────────────────────────────────────────

describe('groupStrandsByColor', () => {
  it('buckets staples by effective color, excluding scaffold', () => {
    const strands = [
      { id: 's1', strand_type: 'staple' },
      { id: 's2', strand_type: 'staple' },
      { id: 'sc', strand_type: 'scaffold' },
    ]
    const out = groupStrandsByColor(strands, { s1: 0xff0000, s2: 0xff0000 }, new Map())
    expect(out).toEqual([{ color: '#ff0000', strandIds: ['s1', 's2'] }])
  })

  it('resolves color via effective → strand.color → palette, in that order', () => {
    const strands = [
      { id: 'a', color: '#abcdef' },               // strand.color
      { id: 'b' },                                  // palette fallback
      { id: 'c' },                                  // effective override
    ]
    const effective = { c: 0x123456 }
    const palette = new Map([['b', 0x00ff00]])
    const out = groupStrandsByColor(strands, effective, palette)
    const keys = out.map(g => g.color).sort()
    expect(keys).toEqual(['#00ff00', '#123456', '#abcdef'])
  })

  it('skips strands with no resolvable color', () => {
    const out = groupStrandsByColor([{ id: 'x' }], {}, new Map())
    expect(out).toEqual([])
  })

  it('handles null/undefined strands + palette', () => {
    expect(groupStrandsByColor(null, {}, null)).toEqual([])
  })
})

// ── trimGroupsRemovingStrands (pure) ────────────────────────────────────────────

describe('trimGroupsRemovingStrands', () => {
  it('returns the same array reference when nothing to remove', () => {
    const groups = [{ id: 'g', strandIds: ['s1'] }]
    expect(trimGroupsRemovingStrands(groups, [])).toBe(groups)
    expect(trimGroupsRemovingStrands(groups, null)).toBe(groups)
  })

  it('removes the given ids from every group', () => {
    const groups = [
      { id: 'g1', strandIds: ['s1', 's2'] },
      { id: 'g2', strandIds: ['s2', 's3'] },
    ]
    const out = trimGroupsRemovingStrands(groups, ['s2'])
    expect(out).toEqual([
      { id: 'g1', strandIds: ['s1'] },
      { id: 'g2', strandIds: ['s3'] },
    ])
    expect(groups[0].strandIds).toEqual(['s1', 's2'])  // input untouched
  })
})

// ── selectableGroupStrandIds (pure) ─────────────────────────────────────────────

describe('selectableGroupStrandIds', () => {
  it('keeps only strand ids that still exist in the design', () => {
    const group = { strandIds: ['s1', 'gone', 's2'] }
    const design = { strands: [{ id: 's1' }, { id: 's2' }] }
    expect(selectableGroupStrandIds(group, design)).toEqual(['s1', 's2'])
  })

  it('returns [] for empty group / missing design', () => {
    expect(selectableGroupStrandIds({}, { strands: [] })).toEqual([])
    expect(selectableGroupStrandIds(null, null)).toEqual([])
  })
})

// ── initStrandGroupsPanel (factory, jsdom) ──────────────────────────────────────

function mountDom() {
  document.body.innerHTML = `
    <div id="groups-panel">
      <h2 id="groups-panel-heading">Staple Groups <span id="groups-panel-arrow"></span></h2>
      <div id="groups-list"></div>
      <button id="groups-colors-btn">From colors</button>
      <button id="groups-new-btn">New</button>
    </div>`
}

function makeStore(initial) {
  let state = {
    currentDesign: null,
    currentGeometry: null,
    strandColors: {},
    strandGroups: [],
    multiSelectedStrandIds: [],
    ...initial,
  }
  const subs = []
  return {
    getState: () => state,
    setState: patch => {
      const prev = state
      state = { ...state, ...patch }
      subs.forEach(cb => cb(state, prev))
    },
    subscribe: cb => { subs.push(cb) },
    _emit: patch => {
      const prev = state
      state = { ...state, ...patch }
      subs.forEach(cb => cb(state, prev))
    },
  }
}

function makeDeps(initial) {
  const store = makeStore(initial)
  const selectionManager = { setMultiHighlight: vi.fn() }
  return { store, selectionManager }
}

beforeEach(() => { document.body.innerHTML = '' })

describe('initStrandGroupsPanel', () => {
  it('no-ops gracefully when panel DOM is absent', () => {
    const deps = makeDeps()
    const api = initStrandGroupsPanel(deps)
    expect(api.rebuild).toBeTypeOf('function')
    expect(() => api.rebuild([])).not.toThrow()
  })

  it('starts expanded and rebuilds a row per group on strandGroups change', () => {
    mountDom()
    const deps = makeDeps()
    initStrandGroupsPanel(deps)
    deps.store._emit({ strandGroups: [
      { id: 'g1', name: 'Group 1', color: '#74b9ff', strandIds: ['s1', 's2'] },
      { id: 'g2', name: 'Group 2', color: '#6bcb77', strandIds: ['s3'] },
    ] })
    const rows = [...document.getElementById('groups-list').children]
    expect(rows.length).toBe(2)
    expect(rows[0].querySelector('span').textContent).toBe('Group 1')
    // count badge reflects strand count
    expect(rows[1].textContent).toContain('1')
  })

  it('collapse via heading hides list + buttons and suppresses rebuild', () => {
    mountDom()
    const deps = makeDeps({ strandGroups: [{ id: 'g1', name: 'G', color: '#fff', strandIds: [] }] })
    initStrandGroupsPanel(deps)
    document.getElementById('groups-panel-heading').click()      // collapse
    const list = document.getElementById('groups-list')
    expect(list.style.display).toBe('none')
    expect(document.getElementById('groups-new-btn').style.display).toBe('none')
    // while collapsed, a strandGroups change does NOT repopulate the list
    deps.store._emit({ strandGroups: [{ id: 'g2', name: 'X', color: '#fff', strandIds: [] }] })
    expect(list.children.length).toBe(0)
  })

  it('row click multi-selects the group\'s live strands', () => {
    mountDom()
    const design = { strands: [{ id: 's1' }, { id: 's2' }] }
    const deps = makeDeps({ currentDesign: design })
    initStrandGroupsPanel(deps)
    deps.store._emit({ strandGroups: [{ id: 'g1', name: 'G', color: '#fff', strandIds: ['s1', 'gone', 's2'] }] })
    document.getElementById('groups-list').firstChild.click()
    expect(deps.selectionManager.setMultiHighlight).toHaveBeenCalledWith(['s1', 's2'])
  })

  it('New button appends a group seeded from the current multi-selection', () => {
    mountDom()
    const deps = makeDeps({ multiSelectedStrandIds: ['s5', 's6'] })
    initStrandGroupsPanel(deps)
    document.getElementById('groups-new-btn').click()
    const gs = deps.store.getState().strandGroups
    expect(gs.length).toBe(1)
    expect(gs[0].strandIds).toEqual(['s5', 's6'])
    expect(gs[0].name).toBe('Group 1')
  })

  it('New button removes the seed strands from pre-existing groups', () => {
    mountDom()
    const deps = makeDeps({
      strandGroups: [{ id: 'old', name: 'Old', color: '#fff', strandIds: ['s5', 's7'] }],
      multiSelectedStrandIds: ['s5'],
    })
    initStrandGroupsPanel(deps)
    document.getElementById('groups-new-btn').click()
    const gs = deps.store.getState().strandGroups
    expect(gs[0].strandIds).toEqual(['s7'])        // s5 trimmed from the old group
    expect(gs[1].strandIds).toEqual(['s5'])        // seeded into the new group
  })

  it('From colors button buckets staples by color', () => {
    mountDom()
    const deps = makeDeps({
      currentDesign: { strands: [
        { id: 's1', strand_type: 'staple', color: '#ff0000' },
        { id: 's2', strand_type: 'staple', color: '#ff0000' },
        { id: 's3', strand_type: 'staple', color: '#00ff00' },
        { id: 'sc', strand_type: 'scaffold', color: '#123456' },
      ] },
    })
    initStrandGroupsPanel(deps)
    document.getElementById('groups-colors-btn').click()
    const gs = deps.store.getState().strandGroups
    expect(gs.length).toBe(2)
    expect(gs.find(g => g.strandIds.includes('s1')).strandIds).toEqual(['s1', 's2'])
  })

  it('delete button removes its group', () => {
    mountDom()
    const deps = makeDeps()
    initStrandGroupsPanel(deps)
    deps.store._emit({ strandGroups: [
      { id: 'g1', name: 'A', color: '#fff', strandIds: [] },
      { id: 'g2', name: 'B', color: '#fff', strandIds: [] },
    ] })
    const firstRow = document.getElementById('groups-list').firstChild
    const delBtn = [...firstRow.querySelectorAll('button')].find(b => b.textContent === '×')
    delBtn.click()
    const gs = deps.store.getState().strandGroups
    expect(gs.map(g => g.id)).toEqual(['g2'])
  })
})
