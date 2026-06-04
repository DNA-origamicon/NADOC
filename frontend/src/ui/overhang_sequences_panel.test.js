/**
 * Unit tests for the overhang sequences panel.
 *
 *   liveOverhangs / selectedStrandIds — pure cores, plain data (no mocks).
 *   initOverhangSequencesPanel        — factory wiring, jsdom DOM + mock store/api/selectionManager.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  liveOverhangs,
  selectedStrandIds,
  initOverhangSequencesPanel,
} from './overhang_sequences_panel.js'

// ── liveOverhangs (pure) ────────────────────────────────────────────────────────

describe('liveOverhangs', () => {
  it('returns [] for null / empty design', () => {
    expect(liveOverhangs(null)).toEqual([])
    expect(liveOverhangs({})).toEqual([])
    expect(liveOverhangs({ overhangs: [] })).toEqual([])
  })

  it('keeps overhangs whose backing strand is live', () => {
    const design = {
      strands: [{ id: 's1' }, { id: 's2' }],
      overhangs: [{ id: 'o1', strand_id: 's1' }, { id: 'o2', strand_id: 's2' }],
    }
    expect(liveOverhangs(design).map(o => o.id)).toEqual(['o1', 'o2'])
  })

  it('drops overhangs whose backing strand was deleted (ghost filter)', () => {
    const design = {
      strands: [{ id: 's1' }],
      overhangs: [{ id: 'o1', strand_id: 's1' }, { id: 'ghost', strand_id: 'gone' }],
    }
    expect(liveOverhangs(design).map(o => o.id)).toEqual(['o1'])
  })

  it('keeps overhangs with no strand_id (unbacked)', () => {
    const design = {
      strands: [{ id: 's1' }],
      overhangs: [{ id: 'free', strand_id: null }, { id: 'free2' }],
    }
    expect(liveOverhangs(design).map(o => o.id)).toEqual(['free', 'free2'])
  })
})

// ── selectedStrandIds (pure) ────────────────────────────────────────────────────

describe('selectedStrandIds', () => {
  it('returns empty Set for null / empty state', () => {
    expect([...selectedStrandIds(null)]).toEqual([])
    expect([...selectedStrandIds({})]).toEqual([])
  })

  it('includes the single selectedObject strand', () => {
    const ids = selectedStrandIds({ selectedObject: { data: { strand_id: 'sX' } } })
    expect([...ids]).toEqual(['sX'])
  })

  it('includes multi-selected strand ids', () => {
    const ids = selectedStrandIds({ multiSelectedStrandIds: ['a', 'b'] })
    expect([...ids].sort()).toEqual(['a', 'b'])
  })

  it('includes the strandId of each multi-selected domain', () => {
    const ids = selectedStrandIds({ multiSelectedDomainIds: [{ strandId: 'd1' }, { strandId: 'd2' }] })
    expect([...ids].sort()).toEqual(['d1', 'd2'])
  })

  it('unions all three sources and dedupes', () => {
    const ids = selectedStrandIds({
      selectedObject: { data: { strand_id: 'shared' } },
      multiSelectedStrandIds: ['shared', 'm'],
      multiSelectedDomainIds: [{ strandId: 'd' }],
    })
    expect([...ids].sort()).toEqual(['d', 'm', 'shared'])
  })
})

// ── initOverhangSequencesPanel (factory, jsdom) ─────────────────────────────────

// Build the DOM the factory queries by id.
function mountDom() {
  document.body.innerHTML = `
    <div id="overhang-panel">
      <div id="overhang-panel-heading">Overhangs <span id="overhang-panel-arrow"></span></div>
      <div id="overhang-label-size-row"><input id="overhang-label-size" type="range" /><span id="overhang-label-size-val"></span></div>
      <div id="overhang-list"></div>
    </div>`
}

function makeStore(initialDesign) {
  let state = {
    currentDesign: initialDesign,
    selectedObject: null,
    multiSelectedStrandIds: [],
    multiSelectedDomainIds: [],
    multiSelectedOverhangIds: [],
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
    _emit: (patch) => {           // test helper: change state + notify
      const prev = state
      state = { ...state, ...patch }
      subs.forEach(cb => cb(state, prev))
    },
  }
}

function makeDeps(design) {
  const store = makeStore(design)
  const selectionManager = { selectStrand: vi.fn() }
  const api = {
    generateOverhangRandomSequence: vi.fn(() => Promise.resolve()),
    patchOverhang: vi.fn(() => Promise.resolve()),
    patchOverhangBinding: vi.fn(() => Promise.resolve()),
  }
  const overhangNameOverlay = { setScale: vi.fn() }
  return { store, selectionManager, api, overhangNameOverlay }
}

const DESIGN = {
  strands: [{ id: 's1' }, { id: 's2' }],
  overhangs: [
    { id: 'o1', strand_id: 's1', label: 'A', sequence: 'NNN' },
    { id: 'o2', strand_id: 's2', label: 'B', sequence: 'ACGT' },
  ],
  overhang_bindings: [{ id: 'b1', overhang_a_id: 'o1', overhang_b_id: 'o2', bound: false, name: 'pair' }],
}

beforeEach(() => { document.body.innerHTML = '' })

describe('initOverhangSequencesPanel', () => {
  it('no-ops gracefully when panel DOM is absent', () => {
    const deps = makeDeps(DESIGN)
    const api = initOverhangSequencesPanel(deps)
    expect(api.rebuild).toBeTypeOf('function')
    expect(() => api.rebuild(DESIGN)).not.toThrow()
  })

  it('starts collapsed: list hidden, not populated', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    const list = document.getElementById('overhang-list')
    expect(list.style.display).toBe('none')
    expect(list.children.length).toBe(0)
  })

  it('expands on heading click and renders a row per live overhang', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const list = document.getElementById('overhang-list')
    expect(list.style.display).toBe('')
    // header row + one row per overhang
    const rows = [...list.children].filter(c => c.dataset.strandId)
    expect(rows.map(r => r.dataset.strandId)).toEqual(['s1', 's2'])
  })

  it('shows an empty message when expanded with no overhangs', () => {
    mountDom()
    const deps = makeDeps({ strands: [], overhangs: [] })
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    expect(document.getElementById('overhang-list').textContent).toContain('No overhangs')
  })

  it('label-size slider drives overhangNameOverlay.setScale', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    const slider = document.getElementById('overhang-label-size')
    slider.value = '2.5'
    slider.dispatchEvent(new Event('input'))
    expect(deps.overhangNameOverlay.setScale).toHaveBeenCalledWith(2.5)
    expect(document.getElementById('overhang-label-size-val').textContent).toBe('2.5')
  })

  it('Gen button shows only for empty / all-N sequences', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    const genOf = row => [...row.querySelectorAll('button')].find(b => b.textContent === 'Gen')
    // o1 sequence 'NNN' → Gen visible; o2 sequence 'ACGT' → Gen hidden
    expect(genOf(rows[0]).style.display).toBe('')
    expect(genOf(rows[1]).style.display).toBe('none')
  })

  it('Set button persists trimmed/uppercased sequence + label via api.patchOverhang', async () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    const [nameInput, seqInput] = row.querySelectorAll('input')
    nameInput.value = '  myLabel '
    seqInput.value = ' acgt '
    const setBtn = [...row.querySelectorAll('button')].find(b => b.textContent === 'Set')
    setBtn.click()
    expect(deps.api.patchOverhang).toHaveBeenCalledWith('o1', { sequence: 'ACGT', label: 'myLabel' })
  })

  it('Bind toggle calls patchOverhangBinding with the flipped bound flag', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    const bindBtn = [...row.querySelectorAll('button')].find(b => b.textContent === 'Bind')
    expect(bindBtn).toBeTruthy()
    bindBtn.click()
    expect(deps.api.patchOverhangBinding).toHaveBeenCalledWith('b1', { bound: true })
  })

  it('row click selects the overhang via store.setState', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    row.click()
    expect(deps.store.getState().multiSelectedOverhangIds).toEqual(['o1'])
  })

  it('highlights rows whose strand is selected when selection changes', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    deps.store._emit({ multiSelectedStrandIds: ['s1'] })
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    const r1 = rows.find(r => r.dataset.strandId === 's1')
    const r2 = rows.find(r => r.dataset.strandId === 's2')
    expect(r1.style.background).toBe('rgb(30, 58, 95)')   // #1e3a5f
    expect(r2.style.background).toBe('')
  })

  it('rebuilds the list when currentDesign changes (while expanded)', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    deps.store._emit({ currentDesign: { strands: [{ id: 's9' }], overhangs: [{ id: 'o9', strand_id: 's9' }] } })
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    expect(rows.map(r => r.dataset.strandId)).toEqual(['s9'])
  })
})
