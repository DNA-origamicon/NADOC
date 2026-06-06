import { describe, it, expect, afterEach } from 'vitest'
import {
  LEVELS, TAB_CYCLE, BTN_LEVEL, LEVEL_BTN,
  isDrillV2, normalizeLevel, nextTabLevel, toggleLevel,
} from './selection_level.js'

describe('selection_level — constants & maps', () => {
  it('LEVELS is the five-state set', () => {
    expect(LEVELS).toEqual(['default', 'cluster', 'domain', 'end', 'xover'])
  })

  it('Tab cycle excludes strand/default', () => {
    expect(TAB_CYCLE).toEqual(['cluster', 'domain', 'end', 'xover'])
    expect(TAB_CYCLE).not.toContain('default')
    expect(TAB_CYCLE).not.toContain('strand')
  })

  it('BTN_LEVEL and LEVEL_BTN round-trip (strand ↔ default)', () => {
    for (const [dk, lvl] of Object.entries(BTN_LEVEL)) {
      expect(LEVEL_BTN[lvl]).toBe(dk)
    }
    expect(BTN_LEVEL.strand).toBe('default')
    expect(LEVEL_BTN.default).toBe('strand')
  })
})

describe('normalizeLevel', () => {
  it('passes valid levels through', () => {
    for (const l of LEVELS) expect(normalizeLevel(l)).toBe(l)
  })
  it('coerces unknowns / null to default', () => {
    expect(normalizeLevel('bead')).toBe('default')   // legacy name → default
    expect(normalizeLevel(null)).toBe('default')
    expect(normalizeLevel(undefined)).toBe('default')
    expect(normalizeLevel('nonsense')).toBe('default')
  })
})

describe('nextTabLevel — Tab cycle', () => {
  it('from default/anywhere lands on cluster', () => {
    expect(nextTabLevel('default')).toBe('cluster')
    expect(nextTabLevel(null)).toBe('cluster')
    expect(nextTabLevel('strand')).toBe('cluster')   // not in cycle → start
  })
  it('walks cluster → domain → end → xover → cluster', () => {
    expect(nextTabLevel('cluster')).toBe('domain')
    expect(nextTabLevel('domain')).toBe('end')
    expect(nextTabLevel('end')).toBe('xover')
    expect(nextTabLevel('xover')).toBe('cluster')   // wraps
  })
})

describe('toggleLevel — filter-button toggle', () => {
  it('engaging a level from default sets it', () => {
    expect(toggleLevel('default', 'cluster')).toBe('cluster')
    expect(toggleLevel('default', 'xover')).toBe('xover')
  })
  it('re-engaging the active level turns it off (→ default)', () => {
    expect(toggleLevel('cluster', 'cluster')).toBe('default')
    expect(toggleLevel('xover', 'xover')).toBe('default')
  })
  it('switching to a different level replaces it', () => {
    expect(toggleLevel('cluster', 'domain')).toBe('domain')
  })
  it('clicking the strand button (→default) from any level returns to default', () => {
    expect(toggleLevel('cluster', 'default')).toBe('default')
    expect(toggleLevel('default', 'default')).toBe('default')
  })
})

describe('isDrillV2 — feature flag', () => {
  afterEach(() => {
    try { localStorage.removeItem('NADOC_DRILL_V2') } catch { /* ignore */ }
  })
  it('off by default', () => {
    expect(isDrillV2()).toBe(false)
  })
  it('on when localStorage NADOC_DRILL_V2 === "true"', () => {
    localStorage.setItem('NADOC_DRILL_V2', 'true')
    expect(isDrillV2()).toBe(true)
  })
  it('stays off for any other localStorage value', () => {
    localStorage.setItem('NADOC_DRILL_V2', '1')
    expect(isDrillV2()).toBe(false)
  })
})
