/**
 * Tests for clash_overlay.js — red highlight over steric-clash backbone beads.
 *   clashEntriesFor  — pure: clash pair list + backbone entries → entries to glow.
 *   initClashOverlay — factory: toggle fetches the report, drives
 *                      setClashHighlight/clearClashHighlight + the count badge,
 *                      re-fetches on geometry change.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as THREE from 'three'
import { clashEntriesFor, piercingEntriesFor, initClashOverlay } from './clash_overlay.js'

function entry(nuc) { return { pos: { x: 0, y: 0, z: 0 }, nuc } }
const ENTRIES = [
  entry({ helix_id: 'h1', bp_index: 5, direction: 'FORWARD' }),
  entry({ helix_id: 'h2', bp_index: 5, direction: 'REVERSE' }),
  entry({ helix_id: 'h3', bp_index: 9, direction: 'FORWARD' }),
]
// One clash pair between the first two entries.
const REPORT = {
  piercing: { count: 1, truncated: false, nucleotides: [
    { helix_id: 'h3', bp_index: 9, direction: 'FORWARD', position: [0, 0, 0] },
  ] },
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
      setPiercingHighlight: vi.fn(),
      clearPiercingHighlight: vi.fn(),
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
      '<div id="clash-legend"><span id="clash-legend-text"></span><span id="piercing-legend-text"></span><span id="piercing-check-progress" hidden><span id="piercing-check-percent"></span></span><span id="clash-legend-status"></span></div>'
  })
  afterEach(() => vi.useRealTimers())

  it('shows measured progress only after one second and clears it on completion', async () => {
    vi.useFakeTimers()
    const deps = makeDeps()
    let finish, options
    deps.api.getClashes.mockImplementation(opts => { options = opts; return new Promise(resolve => { finish = resolve }) })
    const overlay = initClashOverlay(deps), indicator = document.getElementById('piercing-check-progress')
    overlay.toggle()
    options.onProgress({ percent: 27, stage: 'Checking bonds' })
    await vi.advanceTimersByTimeAsync(999)
    expect(indicator.hidden).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    expect(indicator.hidden).toBe(false)
    expect(document.getElementById('piercing-check-percent').textContent).toBe('27%')
    finish(REPORT)
    await vi.advanceTimersByTimeAsync(1)
    expect(indicator.hidden).toBe(true)
    expect(document.getElementById('piercing-legend-text').textContent).toBe('1 piercing')
    overlay.dispose()
  })

  it('never flashes a spinner for fast checks', async () => {
    vi.useFakeTimers()
    const overlay = initClashOverlay(makeDeps())
    overlay.toggle()
    await vi.advanceTimersByTimeAsync(1500)
    expect(document.getElementById('piercing-check-progress').hidden).toBe(true)
    overlay.dispose()
  })

  it('aborts superseded work, ignores its progress, and hides progress on error/off', async () => {
    vi.useFakeTimers()
    const deps = makeDeps(), calls = []
    deps.api.getClashes.mockImplementation(opts => new Promise(resolve => calls.push({ ...opts, resolve })))
    const overlay = initClashOverlay(deps), indicator = document.getElementById('piercing-check-progress')
    overlay.toggle()
    deps.store._fireGeometry([{}])
    expect(calls[0].signal.aborted).toBe(true)
    calls[1].onProgress({ percent: 15 })
    calls[0].onProgress({ percent: 90 })
    calls[0].resolve(REPORT)
    await vi.advanceTimersByTimeAsync(1001)
    expect(indicator.hidden).toBe(false)
    expect(document.getElementById('piercing-check-percent').textContent).toBe('15%')
    calls[1].resolve(null)
    await vi.advanceTimersByTimeAsync(1)
    expect(indicator.hidden).toBe(true)
    expect(document.getElementById('clash-legend-status').textContent).toContain('unavailable')
    overlay.refresh()
    await vi.advanceTimersByTimeAsync(1001)
    overlay.toggle()
    expect(indicator.hidden).toBe(true)
    expect(calls[2].signal.aborted).toBe(true)
    calls[2].resolve(REPORT)
    overlay.dispose()
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
    expect(document.getElementById('piercing-legend-text').textContent).toBe('1 piercing')
    expect(designRenderer.setPiercingHighlight).toHaveBeenLastCalledWith([ENTRIES[2]])
  })

  // A display-only rebuild (the oxDNA capture-strand injection) replaces the backbone
  // entries the glow was painted onto but moves no design nucleotide, so the standing
  // report is still valid — repaint it rather than re-fetching one per keystroke.
  it('repaints the standing report on a display-only rebuild without re-fetching', async () => {
    const { designRenderer, store, api } = makeDeps()
    const overlay = initClashOverlay({ store, designRenderer, api })
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    api.getClashes.mockClear(); designRenderer.setClashHighlight.mockClear()
    window.dispatchEvent(new CustomEvent('nadoc:display-rebuilt'))
    expect(api.getClashes).not.toHaveBeenCalled()
    expect(designRenderer.setClashHighlight).toHaveBeenCalledTimes(1)
    expect(designRenderer.setClashHighlight.mock.calls[0][0]).toHaveLength(2)
  })

  it('a display-only rebuild is a no-op while the overlay is off', async () => {
    const { designRenderer, store, api } = makeDeps()
    initClashOverlay({ store, designRenderer, api })
    window.dispatchEvent(new CustomEvent('nadoc:display-rebuilt'))
    expect(api.getClashes).not.toHaveBeenCalled()
    expect(designRenderer.setClashHighlight).not.toHaveBeenCalled()
  })

  it('toggle off → clears highlight + hides badge', async () => {
    const { designRenderer, store, api } = makeDeps()
    const overlay = initClashOverlay({ store, designRenderer, api })
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(overlay.toggle()).toBe(false)
    expect(designRenderer.clearClashHighlight).toHaveBeenCalled()
    expect(designRenderer.clearPiercingHighlight).toHaveBeenCalled()
    expect(document.getElementById('clash-legend').classList.contains('visible')).toBe(false)
  })

  it('clean design (0 clashes) → no highlight, green "0 clashes" badge', async () => {
    const { designRenderer, store, api } = makeDeps({ report: { count: 0, clashes: [], piercing: { count: 0, nucleotides: [], truncated: false } } })
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

  it('keeps a piercing-only finding visible when there are zero clashes', async () => {
    const deps = makeDeps({ report: { ...REPORT, count: 0, clashes: [] } })
    const overlay = initClashOverlay(deps)
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(document.getElementById('clash-legend').classList.contains('none')).toBe(false)
    expect(deps.designRenderer.setPiercingHighlight).toHaveBeenLastCalledWith([ENTRIES[2]])
    overlay.dispose()
  })

  it('discards an older request after a geometry change', async () => {
    const deps = makeDeps(), resolve = []
    deps.api.getClashes.mockImplementation(() => new Promise(r => resolve.push(r)))
    const overlay = initClashOverlay(deps)
    overlay.toggle()
    expect(document.getElementById('clash-legend-status').textContent).toContain('Checking')
    deps.store._fireGeometry([{}])
    resolve[1]({ ...REPORT, count: 2 }); await Promise.resolve(); await Promise.resolve()
    resolve[0](REPORT); await Promise.resolve(); await Promise.resolve()
    expect(document.getElementById('clash-legend-text').textContent).toBe('2 clashes')
    overlay.dispose()
  })

  it.each([null, { count: 0, clashes: [] }])('does not label an unavailable piercing check as zero: %j', async report => {
    const deps = makeDeps({ report }), overlay = initClashOverlay(deps)
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(document.getElementById('clash-legend-status').textContent).toContain('unavailable')
    expect(document.getElementById('piercing-legend-text').textContent).not.toBe('0 piercings')
    expect(deps.designRenderer.setPiercingHighlight).not.toHaveBeenCalled()
    overlay.dispose()
  })

  it('clears stale markers on a failed refresh and catches rejected requests', async () => {
    const deps = makeDeps(), overlay = initClashOverlay(deps)
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    deps.api.getClashes.mockRejectedValue(new Error('offline'))
    await expect(overlay.refresh()).resolves.toBeUndefined()
    expect(deps.designRenderer.clearPiercingHighlight).toHaveBeenCalled()
    expect(document.getElementById('clash-legend-status').textContent).toContain('unavailable')
    overlay.dispose()
  })

  it('labels a limited report as a lower bound', async () => {
    const deps = makeDeps({ report: { ...REPORT, piercing: { ...REPORT.piercing, count: 200, truncated: true } } })
    const overlay = initClashOverlay(deps)
    overlay.toggle(); await Promise.resolve(); await Promise.resolve()
    expect(document.getElementById('piercing-legend-text').textContent).toBe('200+ piercings')
    overlay.dispose()
  })
})

describe('piercingEntriesFor', () => {
  it('distinguishes extension indices, loop copies and their common helix anchor', () => {
    const anchor = { helix_id: 'h', bp_index: -5, direction: 'FORWARD' }
    const entries = [entry(anchor), entry({ ...anchor, copy_k: 1 }),
      entry({ ...anchor, helix_id: '__ext_tail', bp_index: 1 }),
      entry({ ...anchor, helix_id: '__ext_tail', bp_index: 2 })]
    const refs = [{ ...anchor, extension_id: 'tail', ext_k: 2 }, { ...anchor, copy_k: 1 }]
    expect(piercingEntriesFor([...refs, ...refs], entries)).toEqual([entries[3], entries[1]])
  })

  it('resolves crossover inserts by simulation index and follows their live mesh position', () => {
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(.1), new THREE.MeshBasicMaterial(), 2)
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(1, 2, 3))
    const out = piercingEntriesFor([{ crossover_id: 'xo', extra_base_k: 0 }], [],
      [{ xoId: 'xo', simK: 0, id: 1, instMesh: mesh }])
    expect(out[0].getPosition().toArray()).toEqual([1, 2, 3])
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(4, 5, 6))
    expect(out[0].getPosition().toArray()).toEqual([4, 5, 6])
    mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose()
  })

  it('uses measured coordinates when a coarse representation omits the base bead', () => {
    const refs = [{ helix_id: 'h', bp_index: 1, direction: 'REVERSE', position: [1, 2, 3] }]
    expect(piercingEntriesFor(refs, [])[0].pos.toArray()).toEqual([1, 2, 3])
  })
})
