/**
 * Unit tests for the strand-length histogram.
 *
 *   computeStrandLengthBins  — pure binning core, real Design objects (no mocks).
 *   initStrandLengthHistogram — factory wiring, jsdom DOM + mock store/api/selectionManager.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { computeStrandLengthBins, initStrandLengthHistogram, HIST_MIN_NT, HIST_MAX_NT } from './strand_length_histogram.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

// A strand whose single forward domain spans `len` nt (start_bp..start_bp+len-1).
// strandLengthNtFromDesign = |end-start|+1, so this yields exactly `len`.
function staple(id, len, helixId = 'h0') {
  return { id, strand_type: 'staple', domains: [{ helix_id: helixId, start_bp: 0, end_bp: len - 1 }] }
}
function scaffold(id, len, helixId = 'h0') {
  return { id, strand_type: 'scaffold', domains: [{ helix_id: helixId, start_bp: 0, end_bp: len - 1 }] }
}
function design(strands) {
  return { strands, helices: [{ id: 'h0' }] }
}

// ── computeStrandLengthBins (pure) ──────────────────────────────────────────────

describe('computeStrandLengthBins', () => {
  it('reports no-design when there are no strands', () => {
    expect(computeStrandLengthBins(null).status).toBe('no-design')
    expect(computeStrandLengthBins({ strands: [] }).status).toBe('no-design')
    expect(computeStrandLengthBins(null).summary).toBe('No design loaded.')
  })

  it('reports no-staples when strands exist but none are staples', () => {
    const r = computeStrandLengthBins(design([scaffold('s', 100)]))
    expect(r.status).toBe('no-staples')
    expect(r.summary).toBe('No staple strands.')
  })

  it('bins staples by length, sorted ascending, with counts', () => {
    const r = computeStrandLengthBins(design([
      staple('a', 32), staple('b', 32), staple('c', 21),
    ]))
    expect(r.status).toBe('ok')
    expect(r.bins.map(b => b.length)).toEqual([21, 32])
    expect(r.bins.find(b => b.length === 32).count).toBe(2)
    expect(r.bins.find(b => b.length === 32).strandIds).toEqual(['a', 'b'])
    expect(r.minLen).toBe(21)
    expect(r.maxLen).toBe(32)
    expect(r.maxCount).toBe(2)
  })

  it('flags out-of-range bins (< 18 or > 50) and ignores scaffold strands', () => {
    const r = computeStrandLengthBins(design([
      staple('short', 10), staple('ok', 32), staple('long', 60), scaffold('scaf', 7000),
    ]))
    expect(r.staples.length).toBe(3)            // scaffold excluded
    expect(r.nShort).toBe(1)
    expect(r.nOk).toBe(1)
    expect(r.nLong).toBe(1)
    const isOut = Object.fromEntries(r.bins.map(b => [b.length, b.isOut]))
    expect(isOut[10]).toBe(true)
    expect(isOut[32]).toBe(false)
    expect(isOut[60]).toBe(true)
  })

  it('boundary lengths 18 and 50 are in-range (not flagged)', () => {
    const r = computeStrandLengthBins(design([staple('lo', HIST_MIN_NT), staple('hi', HIST_MAX_NT)]))
    expect(r.nOk).toBe(2)
    expect(r.nShort).toBe(0)
    expect(r.nLong).toBe(0)
    expect(r.bins.every(b => b.isOut === false)).toBe(true)
  })

  it('summary reports staple count, in-range pct, and short/long suffixes', () => {
    const allOk = computeStrandLengthBins(design([staple('a', 32), staple('b', 40)]))
    expect(allOk.summary).toBe('2 staples · 100% in 18–50 nt')

    const mixed = computeStrandLengthBins(design([staple('a', 32), staple('b', 10), staple('c', 60), staple('d', 40)]))
    // 2 of 4 in range → 50%, with short + long suffixes
    expect(mixed.summary).toBe('4 staples · 50% in 18–50 nt · 1 short · 1 long')
  })
})

// ── initStrandLengthHistogram (factory) ─────────────────────────────────────────

function mountDom() {
  document.body.innerHTML = `
    <div id="strand-hist-heading"></div>
    <span id="strand-hist-arrow"></span>
    <div id="strand-hist-body" style="display:none"></div>
    <canvas id="strand-hist-canvas" width="120" height="60"></canvas>
    <div id="strand-hist-tooltip"></div>
    <div id="strand-hist-summary"></div>
    <div id="hist-ctx-menu" style="display:none">
      <span id="hist-ctx-header"></span><span id="hist-ctx-count"></span>
      <button id="hist-ctx-delete-btn"></button>
    </div>`
}

function makeStore(initialDesign) {
  let subscriber = null
  let state = { currentDesign: initialDesign }
  return {
    getState: () => state,
    subscribe: cb => { subscriber = cb },
    _emit: next => { const prev = state; state = next; subscriber?.(next, prev) },
  }
}

describe('initStrandLengthHistogram (factory)', () => {
  let store, selectionManager, api, centerOnStrand
  const D = () => design([staple('a', 32), staple('b', 32), staple('c', 10)])

  beforeEach(() => {
    mountDom()
    // jsdom has no canvas 2d context — stub the calls _redraw makes.
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
      clearRect: vi.fn(), fillRect: vi.fn(), fillText: vi.fn(),
      fillStyle: '', font: '', textAlign: '',
    }))
    HTMLCanvasElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 120, height: 60 })
    store = makeStore(D())
    selectionManager = { selectStrand: vi.fn() }
    api = { deleteStrand: vi.fn(() => Promise.resolve()), deleteStrandsBatch: vi.fn(() => Promise.resolve()) }
    centerOnStrand = vi.fn()
  })

  it('returns a no-op api and does not throw when DOM is absent', () => {
    document.body.innerHTML = ''
    const h = initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    expect(() => h.redraw(D())).not.toThrow()
  })

  it('expanding the heading shows the body and draws bars from the current design', () => {
    initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    document.getElementById('strand-hist-heading').click()
    expect(document.getElementById('strand-hist-body').style.display).toBe('block')
    expect(document.getElementById('strand-hist-summary').textContent).toContain('3 staples')
  })

  it('collapsing again hides the body', () => {
    initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    const heading = document.getElementById('strand-hist-heading')
    heading.click()  // expand
    heading.click()  // collapse
    expect(document.getElementById('strand-hist-body').style.display).toBe('none')
  })

  it('redraw() populates hit areas so a bar click selects + centers a strand', () => {
    const h = initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    h.redraw(D())
    // Click somewhere inside the canvas; at width 120 with 2 bins a bar covers x≈4..
    const canvas = document.getElementById('strand-hist-canvas')
    canvas.dispatchEvent(new MouseEvent('click', { clientX: 8, clientY: 50, bubbles: true }))
    expect(selectionManager.selectStrand).toHaveBeenCalledTimes(1)
    expect(centerOnStrand).toHaveBeenCalledTimes(1)
  })

  it('store design change while expanded redraws the summary', () => {
    initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    document.getElementById('strand-hist-heading').click()  // expand
    store._emit({ currentDesign: design([staple('x', 40)]) })
    expect(document.getElementById('strand-hist-summary').textContent).toContain('1 staples')
  })

  it('store design change while collapsed does NOT redraw', () => {
    initStrandLengthHistogram({ store, selectionManager, api, centerOnStrand })
    // never expanded → summary stays empty
    store._emit({ currentDesign: design([staple('x', 40)]) })
    expect(document.getElementById('strand-hist-summary').textContent).toBe('')
  })
})
