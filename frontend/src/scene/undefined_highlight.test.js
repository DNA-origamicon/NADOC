import { describe, it, expect, beforeEach, vi } from 'vitest'
import { computeUndefinedEntries, initUndefinedHighlight } from './undefined_highlight.js'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

// ── pure: computeUndefinedEntries ────────────────────────────────────────────
// Helper: backbone entry shape the renderer hands us.
const entry = (strand_id, helix_id, bp_index) => ({ nuc: { strand_id, helix_id, bp_index } })

describe('computeUndefinedEntries', () => {
  it('returns [] for a null design', () => {
    expect(computeUndefinedEntries(null, [entry('s1', 0, 0)])).toEqual([])
  })

  it('flags every entry of a strand with no sequence', () => {
    const design = { helices: [{ id: 0, loop_skips: [] }], strands: [{ id: 's1' /* no sequence */ }] }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 1), entry('s2', 0, 2)]
    const out = computeUndefinedEntries(design, backbone)
    expect(out.map(e => e.nuc.strand_id)).toEqual(['s1', 's1'])
  })

  it('flags only the helix:bp position whose assigned char is N (forward domain)', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [] }],
      strands: [{ id: 's1', sequence: 'GNG', domains: [{ helix_id: 0, start_bp: 0, end_bp: 2, direction: 'FORWARD' }] }],
    }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 1), entry('s1', 0, 2)]
    const out = computeUndefinedEntries(design, backbone)
    expect(out.map(e => e.nuc.bp_index)).toEqual([1])
  })

  it('walks a reverse domain from start_bp downward', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [] }],
      // bp 2,1,0 consume seq[0,1,2]; seq[0]='N' → bp 2 flagged
      strands: [{ id: 's1', sequence: 'NGG', domains: [{ helix_id: 0, start_bp: 2, end_bp: 0, direction: 'REVERSE' }] }],
    }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 1), entry('s1', 0, 2)]
    const out = computeUndefinedEntries(design, backbone)
    expect(out.map(e => e.nuc.bp_index)).toEqual([2])
  })

  it('a skip (delta=-1) consumes no sequence char — alignment preserved', () => {
    const design = {
      // bp 0 → seq[0]='G', bp 1 skipped (no char), bp 2 → seq[1]='N' → flag 0:2
      helices: [{ id: 0, loop_skips: [{ bp_index: 1, delta: -1 }] }],
      strands: [{ id: 's1', sequence: 'GN', domains: [{ helix_id: 0, start_bp: 0, end_bp: 2, direction: 'FORWARD' }] }],
    }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 1), entry('s1', 0, 2)]
    const out = computeUndefinedEntries(design, backbone)
    expect(out.map(e => e.nuc.bp_index)).toEqual([2])
  })

  it('a loop (delta=+1) consumes 2 chars; an N in either copy flags the bp', () => {
    const design = {
      // bp0=seq[0]='G'; bp1 loop → c0=seq[1]='N', c1=seq[2]='C' → flag 0:1; bp2=seq[3]='G'
      helices: [{ id: 0, loop_skips: [{ bp_index: 1, delta: 1 }] }],
      strands: [{ id: 's1', sequence: 'GNCG', domains: [{ helix_id: 0, start_bp: 0, end_bp: 2, direction: 'FORWARD' }] }],
    }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 1), entry('s1', 0, 2)]
    const out = computeUndefinedEntries(design, backbone)
    expect(out.map(e => e.nuc.bp_index)).toEqual([1])
  })

  it('skips position checks for overhang domains but advances seqIdx by their length', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [] }],
      strands: [{
        id: 's1', sequence: 'XXN',  // first 2 chars belong to the overhang (unchecked)
        domains: [
          { helix_id: 9, start_bp: 0, end_bp: 1, overhang_id: 'o1' },   // len 2, advance only
          { helix_id: 0, start_bp: 0, end_bp: 0, direction: 'FORWARD' }, // bp0 → seq[2]='N'
        ],
      }],
    }
    const backbone = [entry('s1', 9, 0), entry('s1', 9, 1), entry('s1', 0, 0)]
    const out = computeUndefinedEntries(design, backbone)
    // overhang positions never flagged; only the real bp whose char is N
    expect(out.map(e => `${e.nuc.helix_id}:${e.nuc.bp_index}`)).toEqual(['0:0'])
  })

  it('returns [] when a fully-sequenced design has no N anywhere', () => {
    const design = {
      helices: [{ id: 0, loop_skips: [] }],
      strands: [{ id: 's1', sequence: 'GCAT', domains: [{ helix_id: 0, start_bp: 0, end_bp: 3, direction: 'FORWARD' }] }],
    }
    const backbone = [entry('s1', 0, 0), entry('s1', 0, 3)]
    expect(computeUndefinedEntries(design, backbone)).toEqual([])
  })
})

// ── factory: initUndefinedHighlight ──────────────────────────────────────────
function makeDeps(initialState = {}) {
  const store = createMockStore(initialState)
  const designRenderer = {
    getBackboneEntries: vi.fn(() => []),
    clearUndefinedHighlight: vi.fn(),
    setUndefinedHighlight: vi.fn(),
  }
  const setMenuToggle = vi.fn()
  return { store, designRenderer, setMenuToggle }
}

const designWithN = {
  helices: [{ id: 0, loop_skips: [] }],
  strands: [{ id: 's1', sequence: 'GNG', domains: [{ helix_id: 0, start_bp: 0, end_bp: 2, direction: 'FORWARD' }] }],
}

describe('initUndefinedHighlight', () => {
  beforeEach(() => { clearDom() })

  it('no-throws and returns API when the menu button is absent', () => {
    const api = initUndefinedHighlight(makeDeps())
    expect(api.isOn()).toBe(false)
    expect(typeof api.refresh).toBe('function')
  })

  it('isOn/setOn round-trip', () => {
    const api = initUndefinedHighlight(makeDeps())
    api.setOn(true)
    expect(api.isOn()).toBe(true)
    api.setOn(false)
    expect(api.isOn()).toBe(false)
  })

  it('menu click ON: sets pill, computes + paints undefined entries', () => {
    mountIds({ 'menu-view-undefined-bases': 'button' })
    const deps = makeDeps({ currentDesign: designWithN })
    deps.designRenderer.getBackboneEntries.mockReturnValue([
      { nuc: { strand_id: 's1', helix_id: 0, bp_index: 1 } },
    ])
    const api = initUndefinedHighlight(deps)
    document.getElementById('menu-view-undefined-bases').click()
    expect(api.isOn()).toBe(true)
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-undefined-bases', true)
    expect(deps.designRenderer.setUndefinedHighlight).toHaveBeenCalledTimes(1)
    expect(deps.designRenderer.setUndefinedHighlight.mock.calls[0][0]).toHaveLength(1)
  })

  it('menu click ON with no undefined entries clears instead of painting', () => {
    mountIds({ 'menu-view-undefined-bases': 'button' })
    const deps = makeDeps({ currentDesign: { helices: [], strands: [] } })
    const api = initUndefinedHighlight(deps)
    document.getElementById('menu-view-undefined-bases').click()
    expect(api.isOn()).toBe(true)
    expect(deps.designRenderer.setUndefinedHighlight).not.toHaveBeenCalled()
    expect(deps.designRenderer.clearUndefinedHighlight).toHaveBeenCalled()
  })

  it('menu click OFF clears the highlight and pill', () => {
    mountIds({ 'menu-view-undefined-bases': 'button' })
    const deps = makeDeps({ currentDesign: designWithN })
    deps.designRenderer.getBackboneEntries.mockReturnValue([
      { nuc: { strand_id: 's1', helix_id: 0, bp_index: 1 } },
    ])
    initUndefinedHighlight(deps)
    const btn = document.getElementById('menu-view-undefined-bases')
    btn.click()  // on
    deps.designRenderer.clearUndefinedHighlight.mockClear()
    btn.click()  // off
    expect(deps.setMenuToggle).toHaveBeenLastCalledWith('menu-view-undefined-bases', false)
    expect(deps.designRenderer.clearUndefinedHighlight).toHaveBeenCalledTimes(1)
    expect(deps.designRenderer.setUndefinedHighlight).toHaveBeenCalledTimes(1)  // only from the ON click
  })

  it('refresh() with no design clears the highlight', () => {
    const deps = makeDeps({ currentDesign: null })
    const api = initUndefinedHighlight(deps)
    api.refresh()
    expect(deps.designRenderer.clearUndefinedHighlight).toHaveBeenCalled()
    expect(deps.designRenderer.getBackboneEntries).not.toHaveBeenCalled()
  })

  it('design-change subscriber refreshes only while the toggle is ON', () => {
    const deps = makeDeps({ currentDesign: null })
    const api = initUndefinedHighlight(deps)
    // OFF: a design change does not re-highlight
    deps.store.setState({ currentDesign: designWithN })
    expect(deps.designRenderer.getBackboneEntries).not.toHaveBeenCalled()
    // ON: a subsequent design change re-highlights
    api.setOn(true)
    deps.designRenderer.getBackboneEntries.mockReturnValue([])
    deps.store.setState({ currentDesign: { ...designWithN } })
    expect(deps.designRenderer.getBackboneEntries).toHaveBeenCalled()
  })
})
