import { describe, it, expect } from 'vitest'
import {
  supportedColoringSet, nextColoringMode, COLORING_SUPPORT,
  reprMenuState, coloringFallbackMode,
  coloringOptionStates, COLORING_ORDER, COLORING_LABELS,
} from './coloring_modes.js'

describe('supportedColoringSet', () => {
  it('uses the static table in design (non-assembly) mode', () => {
    expect([...supportedColoringSet('full', false)]).toEqual([...COLORING_SUPPORT.full])
    expect([...supportedColoringSet('surface', false)]).toEqual(['strand', 'cluster'])
  })
  it('atom reprs in assembly mode swap to cpk/strand/cluster/source (no base)', () => {
    expect([...supportedColoringSet('vdw', true)]).toEqual(['cpk', 'strand', 'cluster', 'source'])
    expect(supportedColoringSet('ballstick', true).has('base')).toBe(false)
  })
  it('surface in assembly mode adds source', () => {
    expect([...supportedColoringSet('surface', true)]).toEqual(['strand', 'cluster', 'source'])
  })
  it('falls back to strand/base/cluster for an unknown repr', () => {
    expect([...supportedColoringSet('mystery', false)]).toEqual(['strand', 'base', 'cluster'])
  })
})

describe('nextColoringMode', () => {
  const modes = ['strand', 'base', 'cluster']
  it('advances and wraps', () => {
    expect(nextColoringMode(modes, 'strand')).toBe('base')
    expect(nextColoringMode(modes, 'cluster')).toBe('strand')
  })
  it('treats an unknown current as before-the-start (→ first)', () => {
    expect(nextColoringMode(modes, 'zzz')).toBe('strand') // idx -1 → 0
  })
  it('returns null when fewer than 2 options', () => {
    expect(nextColoringMode(['strand'], 'strand')).toBeNull()
    expect(nextColoringMode([], 'x')).toBeNull()
  })
})

describe('reprMenuState', () => {
  it('returns none for no instances (null/empty)', () => {
    expect(reprMenuState(null)).toEqual({ kind: 'none' })
    expect(reprMenuState([])).toEqual({ kind: 'none' })
  })
  it('returns single when all instances agree', () => {
    expect(reprMenuState([{ representation: 'cylinders' }, { representation: 'cylinders' }]))
      .toEqual({ kind: 'single', repr: 'cylinders' })
  })
  it('defaults a missing representation to full', () => {
    expect(reprMenuState([{}, { representation: 'full' }]))
      .toEqual({ kind: 'single', repr: 'full' })
  })
  it('returns mixed when instances disagree', () => {
    expect(reprMenuState([{ representation: 'full' }, { representation: 'beads' }]))
      .toEqual({ kind: 'mixed' })
  })
  it('treats a missing representation as full when computing mixed', () => {
    // one explicit 'beads' + one defaulted 'full' → disagree
    expect(reprMenuState([{ representation: 'beads' }, {}]))
      .toEqual({ kind: 'mixed' })
  })
})

describe('coloringFallbackMode', () => {
  it('returns null when the current mode is still supported', () => {
    expect(coloringFallbackMode('full', 'base', false)).toBeNull()
    expect(coloringFallbackMode('cylinders', 'strand', false)).toBeNull()
  })
  it('falls back to strand when current is unsupported (non-atomistic)', () => {
    // cylinders drops 'base' → base is unsupported → strand
    expect(coloringFallbackMode('cylinders', 'base', false)).toBe('strand')
  })
  it('prefers cpk for atomistic reprs when current is unsupported', () => {
    // vdw supports cpk; overhang-only is unsupported there → cpk
    expect(coloringFallbackMode('vdw', 'overhang-only', false)).toBe('cpk')
  })
  it('returns null for hull-prism (supports nothing)', () => {
    expect(coloringFallbackMode('hull-prism', 'strand', false)).toBeNull()
  })
  it('honors assembly-mode support sets', () => {
    // surface in assembly mode adds 'source'; 'base' still unsupported → strand
    expect(coloringFallbackMode('surface', 'base', true)).toBe('strand')
    expect(coloringFallbackMode('surface', 'source', true)).toBeNull()
  })
})

describe('coloringOptionStates', () => {
  it('returns every mode in fixed order, regardless of repr', () => {
    const states = coloringOptionStates('full', false, 'strand')
    expect(states.map(s => s.mode)).toEqual(COLORING_ORDER)
    expect(states.map(s => s.label)).toEqual(COLORING_ORDER.map(m => COLORING_LABELS[m]))
  })
  it('enables only the modes the representation supports', () => {
    // cylinders supports strand/cluster/overhang-only — base/cpk/source disabled.
    const byMode = Object.fromEntries(
      coloringOptionStates('cylinders', false, 'strand').map(s => [s.mode, s.enabled]))
    expect(byMode.strand).toBe(true)
    expect(byMode.cluster).toBe(true)
    expect(byMode['overhang-only']).toBe(true)
    expect(byMode.base).toBe(false)
    expect(byMode.cpk).toBe(false)
    expect(byMode.source).toBe(false)
  })
  it('hull-prism disables everything', () => {
    expect(coloringOptionStates('hull-prism', false, 'strand').every(s => !s.enabled)).toBe(true)
  })
  it('marks active only when the mode is the current AND supported', () => {
    const cpkActive = coloringOptionStates('vdw', false, 'cpk').find(s => s.mode === 'cpk')
    expect(cpkActive).toMatchObject({ enabled: true, active: true })
    // 'source' is unsupported in design mode → never active even if it were current.
    const src = coloringOptionStates('vdw', false, 'source').find(s => s.mode === 'source')
    expect(src).toMatchObject({ enabled: false, active: false })
  })
  it('source becomes enabled for surface in assembly mode', () => {
    const src = coloringOptionStates('surface', true, 'source').find(s => s.mode === 'source')
    expect(src).toMatchObject({ enabled: true, active: true })
  })
})
