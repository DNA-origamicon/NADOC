import { describe, it, expect, afterEach } from 'vitest'
import {
  LEVELS, TAB_CYCLE, BTN_LEVEL, LEVEL_BTN,
  isDrillV2, normalizeLevel, nextTabLevel, toggleLevel, hoverPreviewTarget,
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

describe('hoverPreviewTarget — red-glow leaf preview gate', () => {
  const beadHit = (sid) => ({ kind: 'bead', entry: { nuc: { strand_id: sid } } })
  const coneHit = (sid) => ({ kind: 'cone', cone: { strandId: sid } })
  const base = { drillV2: true, selLevel: 'default', mode: 'strand', strandId: 'S1' }

  it('previews the hovered bead when it belongs to the selected strand', () => {
    const hit = beadHit('S1')
    expect(hoverPreviewTarget({ ...base, hit })).toEqual({ kind: 'bead', entry: hit.entry })
  })
  it('previews the hovered cone when it belongs to the selected strand', () => {
    const hit = coneHit('S1')
    expect(hoverPreviewTarget({ ...base, hit })).toEqual({ kind: 'cone', cone: hit.cone })
  })
  it('no preview when the hovered element is on a DIFFERENT strand', () => {
    expect(hoverPreviewTarget({ ...base, hit: beadHit('S2') })).toBeNull()
    expect(hoverPreviewTarget({ ...base, hit: coneHit('S2') })).toBeNull()
  })
  it('no preview unless drill-v2 is on', () => {
    expect(hoverPreviewTarget({ ...base, drillV2: false, hit: beadHit('S1') })).toBeNull()
  })
  it('no preview outside the default level (fixed levels select on every click)', () => {
    for (const lv of ['cluster', 'domain', 'end', 'xover']) {
      expect(hoverPreviewTarget({ ...base, selLevel: lv, hit: beadHit('S1') })).toBeNull()
    }
  })
  it('no preview until a strand is selected (mode must be "strand")', () => {
    for (const m of ['none', 'bead', 'cone', 'cluster', 'domain']) {
      expect(hoverPreviewTarget({ ...base, mode: m, hit: beadHit('S1') })).toBeNull()
    }
  })
  it('no preview when nothing is under the cursor', () => {
    expect(hoverPreviewTarget({ ...base, hit: null })).toBeNull()
  })
})
