import { describe, it, expect, afterEach } from 'vitest'
import {
  LEVELS, TAB_CYCLE, BTN_LEVEL, LEVEL_BTN,
  isDrillV2, normalizeLevel, nextTabLevel, toggleLevel, hoverPreviewTarget,
  lassoCaptureType,
} from './selection_level.js'

describe('selection_level — constants & maps', () => {
  it('LEVELS is the six-state set (strand is a distinct level)', () => {
    expect(LEVELS).toEqual(['default', 'cluster', 'strand', 'domain', 'end', 'xover'])
  })

  it('Tab cycle is cluster → strand → domain → end → xover → none(default)', () => {
    expect(TAB_CYCLE).toEqual(['cluster', 'strand', 'domain', 'end', 'xover', 'default'])
  })

  it('BTN_LEVEL and LEVEL_BTN round-trip; strand is its own level, default has no button', () => {
    for (const [dk, lvl] of Object.entries(BTN_LEVEL)) {
      expect(LEVEL_BTN[lvl]).toBe(dk)
    }
    expect(BTN_LEVEL.strand).toBe('strand')
    expect(LEVEL_BTN.strand).toBe('strand')
    expect(LEVEL_BTN.default).toBeUndefined()   // default = no button engaged
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
  it('from default/none → cluster; unknown → cluster', () => {
    expect(nextTabLevel('default')).toBe('cluster')   // none → first
    expect(nextTabLevel(null)).toBe('cluster')        // not in cycle → start
  })
  it('walks cluster → strand → domain → end → xover → none(default) → cluster', () => {
    expect(nextTabLevel('cluster')).toBe('strand')
    expect(nextTabLevel('strand')).toBe('domain')
    expect(nextTabLevel('domain')).toBe('end')
    expect(nextTabLevel('end')).toBe('xover')
    expect(nextTabLevel('xover')).toBe('default')   // → none
    expect(nextTabLevel('default')).toBe('cluster') // wraps
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
  it('ON by default (flipped 2026-06-06)', () => {
    expect(isDrillV2()).toBe(true)
  })
  it('opt OUT when localStorage NADOC_DRILL_V2 === "false"', () => {
    localStorage.setItem('NADOC_DRILL_V2', 'false')
    expect(isDrillV2()).toBe(false)
  })
  it('stays ON for any non-"false" localStorage value', () => {
    localStorage.setItem('NADOC_DRILL_V2', '1')
    expect(isDrillV2()).toBe(true)
    localStorage.setItem('NADOC_DRILL_V2', 'true')
    expect(isDrillV2()).toBe(true)
  })
})

describe('hoverPreviewTarget — red-glow leaf preview gate', () => {
  const beadHit = (sid) => ({ kind: 'bead', entry: { nuc: { strand_id: sid } } })
  const coneHit = (sid) => ({ kind: 'cone', cone: { strandId: sid } })
  const arcHit  = (sid) => ({ kind: 'arc',  arc:  { strandId: sid } })
  const base = { drillV2: true, selLevel: 'default', mode: 'strand', strandId: 'S1' }

  it('previews the hovered bead when it belongs to the selected strand', () => {
    const hit = beadHit('S1')
    expect(hoverPreviewTarget({ ...base, hit })).toEqual({ kind: 'bead', entry: hit.entry })
  })
  it('previews the hovered cone when it belongs to the selected strand', () => {
    const hit = coneHit('S1')
    expect(hoverPreviewTarget({ ...base, hit })).toEqual({ kind: 'cone', cone: hit.cone })
  })
  it('previews the hovered crossover arc when it belongs to the selected strand', () => {
    const hit = arcHit('S1')
    expect(hoverPreviewTarget({ ...base, hit })).toEqual({ kind: 'arc', arc: hit.arc })
  })
  it('no preview when the hovered element is on a DIFFERENT strand', () => {
    expect(hoverPreviewTarget({ ...base, hit: beadHit('S2') })).toBeNull()
    expect(hoverPreviewTarget({ ...base, hit: coneHit('S2') })).toBeNull()
    expect(hoverPreviewTarget({ ...base, hit: arcHit('S2')  })).toBeNull()
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

describe('lassoCaptureType — legacy (drillV2 off)', () => {
  const ST = { strands: true, domains: false, ends: false, overhangs: false,
               loops: false, skips: false, crossoverArcs: false }

  it('no auto-drill → selectableTypes gates decide', () => {
    const r = lassoCaptureType({ drillV2: false, selLevel: 'default', drillType: null, selectableTypes: ST })
    expect(r.strands).toBe(true)
    expect(r.ends).toBe(false)
    expect(r.cluster).toBe(false)
  })

  it('auto-drill type-locks: cluster level → cluster capture only', () => {
    const r = lassoCaptureType({ drillV2: false, selLevel: 'default', drillType: 'cluster', selectableTypes: ST })
    expect(r.cluster).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('auto-drill bead level → every bead (beadLevel) + ends', () => {
    const r = lassoCaptureType({ drillV2: false, selLevel: 'default', drillType: 'bead', selectableTypes: ST })
    expect(r.ends).toBe(true)
    expect(r.beadLevel).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('selectableTypes overhangs/loops/skips honored only when no drill active', () => {
    const st = { ...ST, overhangs: true, loops: true, skips: true }
    expect(lassoCaptureType({ drillV2: false, drillType: null, selectableTypes: st }))
      .toMatchObject({ overhangs: true, loops: true, skips: true })
    expect(lassoCaptureType({ drillV2: false, drillType: 'strand', selectableTypes: st }))
      .toMatchObject({ overhangs: false, loops: false, skips: false })
  })
})

describe('lassoCaptureType — drill-v2 honors the engaged selLevel (ISSUE-4 filter-audit)', () => {
  // The motivating bug: Tab to a level in v2, lasso should capture THAT level —
  // not the stale selectableTypes default. selectableTypes here is the default
  // (strands on) to prove the level overrides it.
  const ST = { strands: true, domains: false, ends: false, overhangs: false,
               loops: false, skips: false, crossoverArcs: false }

  it('end level → ends (5′/3′ termini only, beadLevel false), NOT strands (the reported bug)', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'end', drillType: null, selectableTypes: ST })
    expect(r.ends).toBe(true)
    expect(r.beadLevel).toBe(false)   // user decision: termini only, not every nucleotide
    expect(r.strands).toBe(false)
    expect(r.cluster).toBe(false)
  })

  it('cluster level → cluster, NOT strands', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'cluster', drillType: null, selectableTypes: ST })
    expect(r.cluster).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('domain level → domains only', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'domain', drillType: null, selectableTypes: ST })
    expect(r.domains).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('xover level → crossovers only', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'xover', drillType: null, selectableTypes: ST })
    expect(r.xover).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('default level → strands (strand-first model)', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'default', drillType: null, selectableTypes: ST })
    expect(r.strands).toBe(true)
    expect(r.ends).toBe(false)
    expect(r.cluster).toBe(false)
  })

  it('strand level → strands (the distinct fixed strand level captures whole strands)', () => {
    const r = lassoCaptureType({ drillV2: true, selLevel: 'strand', drillType: null, selectableTypes: ST })
    expect(r.strands).toBe(true)
    expect(r.domains).toBe(false)
    expect(r.ends).toBe(false)
  })

  it('overhangs/loops/skips are NOT lasso-capturable in v2 (they are visibility gates, not levels)', () => {
    const st = { ...ST, overhangs: true, loops: true, skips: true }
    const r = lassoCaptureType({ drillV2: true, selLevel: 'default', drillType: null, selectableTypes: st })
    expect(r.overhangs).toBe(false)
    expect(r.loops).toBe(false)
    expect(r.skips).toBe(false)
  })
})
