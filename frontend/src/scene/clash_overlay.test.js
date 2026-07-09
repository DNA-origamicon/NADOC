/**
 * Tests for clash_overlay.js — red highlight over steric-clash backbone beads.
 *   clashEntriesFor  — pure: clash pair list + backbone entries → entries to glow.
 *   initClashOverlay — factory: toggle fetches the report, drives
 *                      setClashHighlight/clearClashHighlight + the count badge,
 *                      re-fetches on geometry change.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { clashEntriesFor, initClashOverlay } from './clash_overlay.js'

function entry(nuc) { return { pos: { x: 0, y: 0, z: 0 }, nuc } }
const ENTRIES = [
  entry({ helix_id: 'h1', bp_index: 5, direction: 'FORWARD' }),
  entry({ helix_id: 'h2', bp_index: 5, direction: 'REVERSE' }),
  entry({ helix_id: 'h3', bp_index: 9, direction: 'FORWARD' }),
]
// One clash pair between the first two entries.
const REPORT = {
  count: 1,
  clashes: [{
    a: { helix_id: 'h1', bp_index: 5, direction: 'FORWARD' },
    b: { helix_id: 'h2', bp_index: 5, direction: 'REVERSE' },
    distance_nm: 0.28,
  }],
}

describe('clashEntriesFor', () => {
  it('returns the backbone entries on either side of a clash pair', () => {
    const out = clashEntriesFor(REPORT.clashes, ENTRIES)
    expect(out).toHaveLength(2)
    expect(out.map(e => e.nuc.helix_id).sort()).toEqual(['h1', 'h2'])
    // the non-clashing entry (h3) is excluded
    expect(out.some(e => e.nuc.helix_id === 'h3')).toBe(false)
  })

  it('de-duplicates when a nucleotide appears in more than one pair', () => {
    const clashes = [
      REPORT.clashes[0],
      { a: { helix_id: 'h1', bp_index: 5, direction: 'FORWARD' },
        b: { helix_id: 'h3', bp_index: 9, direction: 'FORWARD' }, distance_nm: 0.3 },
    ]
    const out = clashEntriesFor(clashes, ENTRIES)
    expect(out).toHaveLength(3)      // h1 counted once, plus h2 + h3
  })

  it('matches on direction (does not confuse FORWARD/REVERSE at same helix:bp)', () => {
    const clashes = [{
      a: { helix_id: 'h1', bp_index: 5, direction: 'REVERSE' },   // no such entry
      b: { helix_id: 'h3', bp_index: 9, direction: 'FORWARD' },
      distance_nm: 0.3,
    }]
    const out = clashEntriesFor(clashes, ENTRIES)
    expect(out.map(e => e.nuc.helix_id)).toEqual(['h3'])
  })

  it('returns [] for empty clashes or entries', () => {
    expect(clashEntriesFor([], ENTRIES)).toEqual([])
    expect(clashEntriesFor(REPORT.clashes, [])).toEqual([])
  })
})

describe('initClashOverlay', () => {
  function makeDeps({ report = REPORT, geometry = [] } = {}) {
    let _geo = geometry
    const subs = []
    const designRenderer = {
      getBackboneEntries: vi.fn(() => ENTRIES),
      setClashHighlight: vi.fn(),
      clearClashHighlight: vi.fn(),
    }
    const store = {
      getState: () => ({ currentDesign: { id: 'd' }, currentGeometry: _geo }),
      subscribe: (fn) => subs.push(fn),
      _fireGeometry: (g) => { _geo = g; subs.forEach(fn => fn()) },
    }
    const api = { getClashes: vi.fn(async () => report) }
    return { designRenderer, store, api }
  }

  beforeEach(() => {
    document.body.innerHTML =
      '<div id="clash-legend"><span id="clash-legend-text"></span></div>'
  })

  it('toggle on → fetches report, highlights clashing beads, shows count badge', async () => {
    const { designRenderer, store, api } = makeDeps()
    const overlay = initClashOverlay({ store, designRenderer, api })
    expect(overlay.toggle()).toBe(true)
    await Promise.resolve(); await Promise.resolve()
    expect(api.getClashes).toHaveBeenCalledTimes(1)
    expect(designRenderer.setClashHighlight).toHaveBeenCalledTimes(1)
    expect(designRenderer.setClashHighlight.mock.calls[0][0]).toHaveLength(2)
    const legend = document.getElementById('clash-legend')
    expect(legend.classList.contains('visible')).toBe(true)
    expect(legend.classList.contains('none')).toBe(false)
    expect(document.getElementById('clash-legend-text').textContent).toBe('1 clash')
  })

  it('toggle off → clears highlight + hides badge', async () => {
    const { designRenderer, store, api } = makeDeps()
    const overlay = initClashOverlay({ store, designRenderer, api })
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(overlay.toggle()).toBe(false)
    expect(designRenderer.clearClashHighlight).toHaveBeenCalled()
    expect(document.getElementById('clash-legend').classList.contains('visible')).toBe(false)
  })

  it('clean design (0 clashes) → no highlight, green "0 clashes" badge', async () => {
    const { designRenderer, store, api } = makeDeps({ report: { count: 0, clashes: [] } })
    const overlay = initClashOverlay({ store, designRenderer, api })
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(designRenderer.setClashHighlight).not.toHaveBeenCalled()
    expect(designRenderer.clearClashHighlight).toHaveBeenCalled()
    const legend = document.getElementById('clash-legend')
    expect(legend.classList.contains('visible')).toBe(true)
    expect(legend.classList.contains('none')).toBe(true)
    expect(document.getElementById('clash-legend-text').textContent).toBe('0 clashes')
  })

  it('re-fetches when the posed geometry changes while on', async () => {
    const { designRenderer, store, api } = makeDeps()
    const overlay = initClashOverlay({ store, designRenderer, api })
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    api.getClashes.mockClear()
    store._fireGeometry([{ changed: true }])
    await Promise.resolve(); await Promise.resolve()
    expect(api.getClashes).toHaveBeenCalledTimes(1)
  })

  it('does NOT fetch on geometry change while off', async () => {
    const { store, designRenderer, api } = makeDeps()
    initClashOverlay({ store, designRenderer, api })
    store._fireGeometry([{ changed: true }])
    await Promise.resolve()
    expect(api.getClashes).not.toHaveBeenCalled()
  })
})
