/**
 * Unit tests for the overhang sequences panel.
 *
 *   liveOverhangs / selectedStrandIds — pure cores, plain data (no mocks).
 *   initOverhangSequencesPanel        — factory wiring, jsdom DOM + mock store/api/selectionManager.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// The panel imports the Connections-section singleton entry point; mock it so we
// can assert the link icon opens the right pair without booting that module.
vi.mock('./overhang_connections_panel.js', () => ({
  openConnectionForPair: vi.fn(),
}))
import { openConnectionForPair } from './overhang_connections_panel.js'

import {
  liveOverhangs,
  selectedStrandIds,
  sortOverhangsForDisplay,
  connectionPairForOverhang,
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

// ── connectionPairForOverhang (pure) ─────────────────────────────────────────────

describe('connectionPairForOverhang', () => {
  it('returns null when the overhang is in no connection', () => {
    expect(connectionPairForOverhang({}, 'o1')).toBeNull()
    expect(connectionPairForOverhang({ overhang_bindings: [] }, 'o1')).toBeNull()
  })

  it('finds a binding pair (either side)', () => {
    const d = { overhang_bindings: [{ overhang_a_id: 'o1', overhang_b_id: 'o2' }] }
    expect(connectionPairForOverhang(d, 'o1')).toEqual({ a: 'o1', b: 'o2' })
    expect(connectionPairForOverhang(d, 'o2')).toEqual({ a: 'o1', b: 'o2' })
  })

  it('falls back to a linker, then a version, when no binding', () => {
    expect(connectionPairForOverhang(
      { overhang_connections: [{ overhang_a_id: 'o3', overhang_b_id: 'o4' }] }, 'o4'),
    ).toEqual({ a: 'o3', b: 'o4' })
    expect(connectionPairForOverhang(
      { connection_versions: [{ overhang_a_id: 'o5', overhang_b_id: 'o6' }] }, 'o5'),
    ).toEqual({ a: 'o5', b: 'o6' })
  })

  it('prefers a binding over a linker/version', () => {
    const d = {
      overhang_bindings:    [{ overhang_a_id: 'o1', overhang_b_id: 'o2' }],
      overhang_connections: [{ overhang_a_id: 'o1', overhang_b_id: 'oX' }],
    }
    expect(connectionPairForOverhang(d, 'o1')).toEqual({ a: 'o1', b: 'o2' })
  })
})

// ── sortOverhangsForDisplay (pure) ──────────────────────────────────────────────

describe('sortOverhangsForDisplay', () => {
  it('sorts alphanumerically by label (Name)', () => {
    const out = sortOverhangsForDisplay([
      { id: 'x', label: 'beta' }, { id: 'y', label: 'alpha' }, { id: 'z', label: 'gamma' },
    ])
    expect(out.map(o => o.label)).toEqual(['alpha', 'beta', 'gamma'])
  })

  it('uses natural numeric order (oh2 before oh10) and is case-insensitive', () => {
    const out = sortOverhangsForDisplay([
      { id: '1', label: 'oh10' }, { id: '2', label: 'OH2' }, { id: '3', label: 'oh1' },
    ])
    expect(out.map(o => o.label)).toEqual(['oh1', 'OH2', 'oh10'])
  })

  it('breaks label ties by sequence, then by id', () => {
    const out = sortOverhangsForDisplay([
      { id: 'b', label: 'p', sequence: 'GGGG' },
      { id: 'a', label: 'p', sequence: 'AAAA' },
      { id: 'c', label: 'p', sequence: 'AAAA' },
    ])
    expect(out.map(o => o.id)).toEqual(['a', 'c', 'b'])  // AAAA(a,c by id) then GGGG(b)
  })

  it('handles missing label/sequence without throwing and does not mutate input', () => {
    const input = [{ id: 'z' }, { id: 'a', label: 'a' }]
    const out = sortOverhangsForDisplay(input)
    expect(out.map(o => o.id)).toEqual(['z', 'a'])   // '' label sorts before 'a'
    expect(input.map(o => o.id)).toEqual(['z', 'a']) // original order preserved
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

// Build the DOM the factory queries by id (getElementById ignores nesting).
const mountDom = () => mountIds({
  'overhang-panel': 'div',
  'overhang-panel-heading': 'div',
  'overhang-panel-arrow': 'span',
  'overhang-label-size-row': 'div',
  'overhang-label-size': 'input',
  'overhang-label-size-val': 'span',
  'overhang-list': 'div',
})

function makeDeps(design) {
  const store = createMockStore({
    currentDesign: design,
    selectedObject: null,
    multiSelectedStrandIds: [],
    multiSelectedDomainIds: [],
    multiSelectedOverhangIds: [],
  })
  const selectionManager = { selectStrand: vi.fn(), selectOverhang: vi.fn() }
  const api = {
    generateOverhangRandomSequence: vi.fn(() => Promise.resolve()),
    patchOverhang: vi.fn(() => Promise.resolve()),
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

beforeEach(() => clearDom())

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

  it('renders a duplex coverage line (paired green + toehold grey) under an overhang in a duplex', () => {
    mountDom()
    const DUPLEX_DESIGN = {
      strands: [
        { id: 's1', domains: [{ helix_id: 'hA', start_bp: 0, end_bp: 5, overhang_id: 'o1' }] },
        { id: 's2', domains: [{ helix_id: 'hB', start_bp: 5, end_bp: 0, overhang_id: 'o2' }] },
      ],
      overhangs: [
        { id: 'o1', strand_id: 's1', label: 'A', sequence: 'AAACGG' },
        { id: 'o2', strand_id: 's2', label: 'B', sequence: 'GTTTCC' },
      ],
      duplexes: [{
        id: 'd1', left: { overhang_id: 'o1', start_bp: 0, end_bp: 3 },
        right: { overhang_id: 'o2', start_bp: 5, end_bp: 2 }, allow_n_wildcard: true,
      }],
    }
    initOverhangSequencesPanel(makeDeps(DUPLEX_DESIGN))
    document.getElementById('overhang-panel-heading').click()
    const spans = [...document.getElementById('overhang-list').querySelectorAll('span')]
    const paired = spans.find(s => s.textContent === 'AAAC')
    const toehold = spans.find(s => s.textContent === 'GG')
    expect(paired?.style.color).toBe('rgb(63, 185, 80)')     // #3fb950 paired
    expect(toehold?.style.color).toBe('rgb(139, 148, 158)')  // #8b949e toehold
  })

  it('renders rows sorted alphanumerically by Name regardless of design order', () => {
    mountDom()
    const unsorted = {
      strands: [{ id: 's1' }, { id: 's2' }, { id: 's3' }],
      overhangs: [
        { id: 'o3', strand_id: 's3', label: 'oh10' },
        { id: 'o1', strand_id: 's1', label: 'oh2' },
        { id: 'o2', strand_id: 's2', label: 'oh1' },
      ],
    }
    const deps = makeDeps(unsorted)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    // oh1, oh2, oh10 → strands s2, s1, s3
    expect(rows.map(r => r.dataset.strandId)).toEqual(['s2', 's1', 's3'])
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

  it('Gen button shows for empty/all-N OR connected overhangs (choice reachable)', () => {
    mountDom()
    // Two UNCONNECTED overhangs: one all-N (Gen shown), one sequenced (Gen hidden).
    const deps = makeDeps({
      strands: [{ id: 's1' }, { id: 's2' }],
      overhangs: [
        { id: 'o1', strand_id: 's1', label: 'A', sequence: 'NNN' },
        { id: 'o2', strand_id: 's2', label: 'B', sequence: 'ACGT' },
      ],
    })
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    const genOf = row => [...row.querySelectorAll('button')].find(b => b.textContent === 'Gen')
    expect(genOf(rows[0]).style.display).toBe('')       // all-N → shown
    expect(genOf(rows[1]).style.display).toBe('none')   // sequenced + UNconnected → hidden
  })

  it('Gen button stays shown for a CONNECTED sequenced overhang (so the Gen choice is reachable)', () => {
    mountDom()
    const deps = makeDeps(DESIGN)   // DESIGN binds o1↔o2
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const rows = [...document.getElementById('overhang-list').children].filter(c => c.dataset.strandId)
    const genOf = row => [...row.querySelectorAll('button')].find(b => b.textContent === 'Gen')
    // o2 ('ACGT') is connected to o1 via the binding → Gen shown.
    expect(genOf(rows[1]).style.display).toBe('')
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

  it('shows a link icon for a connected overhang; click opens the pair', () => {
    openConnectionForPair.mockClear()
    mountDom()
    const deps = makeDeps(DESIGN)   // o1↔o2 share a binding
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    const linkBtn = row.querySelector('button svg')?.closest('button')
    expect(linkBtn).toBeTruthy()
    expect(linkBtn.title).toBe('Open connection with B')   // o2's label
    linkBtn.click()
    expect(openConnectionForPair).toHaveBeenCalledWith('o1', 'o2')
  })

  it('shows no link icon (em dash) for an unconnected overhang', () => {
    mountDom()
    const design = { ...DESIGN, overhang_bindings: [], overhang_connections: [], connection_versions: [] }
    const deps = makeDeps(design)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    expect(row.querySelector('button svg')).toBeNull()
    expect(row.lastElementChild.textContent).toBe('—')
  })

  it('row click selects only the overhang domain via selectionManager.selectOverhang', () => {
    mountDom()
    const deps = makeDeps(DESIGN)
    initOverhangSequencesPanel(deps)
    document.getElementById('overhang-panel-heading').click()
    const row = [...document.getElementById('overhang-list').children].find(c => c.dataset.strandId === 's1')
    row.click()
    expect(deps.selectionManager.selectOverhang).toHaveBeenCalledWith('o1')
    expect(deps.selectionManager.selectStrand).not.toHaveBeenCalled()
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
