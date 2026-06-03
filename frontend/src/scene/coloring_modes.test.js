import { describe, it, expect } from 'vitest'
import { supportedColoringSet, nextColoringMode, COLORING_SUPPORT } from './coloring_modes.js'

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
