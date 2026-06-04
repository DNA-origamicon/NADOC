/**
 * Unit tests for the Fluorescence + FRET Checker controller.
 *
 *   buildFretLookups  — pure lookup-table build (no mocks).
 *   initFretChecker   — factory wiring, jsdom menu buttons + mock store/designRenderer.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { buildFretLookups, FRET_PAIRS, initFretChecker } from './fret_checker.js'

// ── buildFretLookups (pure) ─────────────────────────────────────────────────────

describe('buildFretLookups', () => {
  it('returns empty maps for empty / null input', () => {
    for (const v of [[], null, undefined]) {
      const { donorMap, r0Map } = buildFretLookups(v)
      expect(donorMap.size).toBe(0)
      expect(r0Map.size).toBe(0)
    }
  })

  it('groups acceptors under each donor and keys r0 by donor:acceptor', () => {
    const { donorMap, r0Map } = buildFretLookups([
      { donor: 'cy3', acceptor: 'cy5',  r0: 5.4 },
      { donor: 'cy3', acceptor: 'bhq2', r0: 4.5 },
      { donor: 'fam', acceptor: 'tamra', r0: 4.6 },
    ])
    expect(donorMap.get('cy3')).toEqual(['cy5', 'bhq2'])
    expect(donorMap.get('fam')).toEqual(['tamra'])
    expect(r0Map.get('cy3:cy5')).toBe(5.4)
    expect(r0Map.get('cy3:bhq2')).toBe(4.5)
    expect(r0Map.get('fam:tamra')).toBe(4.6)
  })

  it('shapes the shipped FRET_PAIRS table consistently', () => {
    const { donorMap, r0Map } = buildFretLookups(FRET_PAIRS)
    // every pair contributes exactly one r0 entry
    expect(r0Map.size).toBe(FRET_PAIRS.length)
    // fam donates to three acceptors (tamra, bhq1, bhq2)
    expect(donorMap.get('fam')).toEqual(['tamra', 'bhq1', 'bhq2'])
  })
})

// ── initFretChecker (factory, jsdom) ────────────────────────────────────────────

const mountMenu = () => mountIds({ 'menu-view-fluorescence': 'button', 'menu-view-fret': 'button' })

// fluoro entries: two glowing fluorophores (cy3 donor, cy5 acceptor) + one
// non-emitting quencher (bhq2, present for distance checks but never glowed).
function makeEntries() {
  return [
    { nuc: { modification: 'cy3' }, pos: new THREE.Vector3(0, 0, 0) },
    { nuc: { modification: 'cy5' }, pos: new THREE.Vector3(1, 0, 0) },
    { nuc: { modification: 'bhq2' }, pos: new THREE.Vector3(9, 9, 9) },
  ]
}

function makeDeps() {
  const store = createMockStore({ currentGeometry: { v: 0 } })
  const designRenderer = {
    getFluoroEntries: vi.fn(() => makeEntries()),
    setFluorescenceGlow: vi.fn(),
    clearFluorescenceGlow: vi.fn(),
  }
  const setMenuToggle = vi.fn()
  return { store, designRenderer, setMenuToggle }
}

beforeEach(() => clearDom())

describe('initFretChecker', () => {
  it('does not glow anything before any mode is toggled on', () => {
    mountMenu()
    const deps = makeDeps()
    const fret = initFretChecker(deps)
    expect(fret.isFretOn()).toBe(false)
    expect(deps.designRenderer.setFluorescenceGlow).not.toHaveBeenCalled()
  })

  it('toggling Fluorescence on glows the emitting fluorophores (quencher excluded)', () => {
    mountMenu()
    const deps = makeDeps()
    initFretChecker(deps)
    document.getElementById('menu-view-fluorescence').click()
    expect(deps.setMenuToggle).toHaveBeenCalledWith('menu-view-fluorescence', true)
    const entries = deps.designRenderer.setFluorescenceGlow.mock.calls.at(-1)[0]
    // cy3 + cy5 glow; bhq2 filtered out (not in FLUORO_EMISSION_COLORS)
    expect(entries).toHaveLength(2)
    expect(entries.every(e => e.scale === undefined)).toBe(true)   // no quench in pure-fluorescence
  })

  it('toggling Fluorescence off clears the glow', () => {
    mountMenu()
    const deps = makeDeps()
    initFretChecker(deps)
    const btn = document.getElementById('menu-view-fluorescence')
    btn.click()                                  // on
    deps.designRenderer.clearFluorescenceGlow.mockClear()
    btn.click()                                  // off
    expect(deps.setMenuToggle).toHaveBeenLastCalledWith('menu-view-fluorescence', false)
    expect(deps.designRenderer.clearFluorescenceGlow).toHaveBeenCalled()
  })

  it('FRET mode quenches a donor within Förster radius of a compatible acceptor', () => {
    mountMenu()
    const deps = makeDeps()
    const fret = initFretChecker(deps)
    document.getElementById('menu-view-fret').click()
    expect(fret.isFretOn()).toBe(true)
    const entries = deps.designRenderer.setFluorescenceGlow.mock.calls.at(-1)[0]
    // cy3 donor is ~0.1 nm from cy5 acceptor (r0 5.4) → quenched (scale 3)
    const cy3 = entries.find(e => e.emissionColor === 0xddff00)
    expect(cy3.scale).toBe(3)
  })

  it('refreshIfFret re-runs glow only while FRET is on', () => {
    mountMenu()
    const deps = makeDeps()
    const fret = initFretChecker(deps)
    deps.designRenderer.getFluoroEntries.mockClear()
    fret.refreshIfFret()                          // FRET off → no-op
    expect(deps.designRenderer.getFluoroEntries).not.toHaveBeenCalled()
    document.getElementById('menu-view-fret').click()
    deps.designRenderer.getFluoroEntries.mockClear()
    fret.refreshIfFret()                          // FRET on → refreshes
    expect(deps.designRenderer.getFluoroEntries).toHaveBeenCalled()
  })

  it('rebuilds glow when geometry reloads while a mode is on, but not while both off', () => {
    mountMenu()
    const deps = makeDeps()
    initFretChecker(deps)
    // both off → geometry change is ignored
    deps.designRenderer.getFluoroEntries.mockClear()
    deps.store._emit({ currentGeometry: { v: 1 } })
    expect(deps.designRenderer.getFluoroEntries).not.toHaveBeenCalled()
    // turn fluorescence on, then a geometry reload refreshes
    document.getElementById('menu-view-fluorescence').click()
    deps.designRenderer.getFluoroEntries.mockClear()
    deps.store._emit({ currentGeometry: { v: 2 } })
    expect(deps.designRenderer.getFluoroEntries).toHaveBeenCalled()
  })
})
