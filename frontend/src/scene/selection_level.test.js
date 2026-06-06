import { describe, it, expect } from 'vitest'
import {
  LEVELS, TAB_CYCLE, BTN_LEVEL, LEVEL_BTN,
  normalizeLevel, nextTabLevel, toggleLevel, hoverPreviewTarget,
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

describe('hoverPreviewTarget — red-glow leaf preview gate', () => {
  const beadHit = (sid) => ({ kind: 'bead', entry: { nuc: { strand_id: sid } } })
  const coneHit = (sid) => ({ kind: 'cone', cone: { strandId: sid } })
  const arcHit  = (sid) => ({ kind: 'arc',  arc:  { strandId: sid } })
  const base = { selLevel: 'default', mode: 'strand', strandId: 'S1' }

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

describe('lassoCaptureType — the engaged selLevel is the single source of truth', () => {
  // The motivating bug: Tab to a level, the lasso should capture THAT level's
  // element type (ISSUE-4 filter-audit). selectableTypes is no longer consulted —
  // scaffold/staple gating is applied separately in the lasso loop.

  it('end level → ends (5′/3′ termini only, beadLevel false), NOT strands (the reported bug)', () => {
    const r = lassoCaptureType({ selLevel: 'end' })
    expect(r.ends).toBe(true)
    expect(r.beadLevel).toBe(false)   // user decision: termini only, not every nucleotide
    expect(r.strands).toBe(false)
    expect(r.cluster).toBe(false)
  })

  it('cluster level → cluster, NOT strands', () => {
    const r = lassoCaptureType({ selLevel: 'cluster' })
    expect(r.cluster).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('domain level → domains only', () => {
    const r = lassoCaptureType({ selLevel: 'domain' })
    expect(r.domains).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('xover level → crossovers only', () => {
    const r = lassoCaptureType({ selLevel: 'xover' })
    expect(r.xover).toBe(true)
    expect(r.strands).toBe(false)
  })

  it('default level → strands (strand-first model)', () => {
    const r = lassoCaptureType({ selLevel: 'default' })
    expect(r.strands).toBe(true)
    expect(r.ends).toBe(false)
    expect(r.cluster).toBe(false)
  })

  it('strand level → strands (the distinct fixed strand level captures whole strands)', () => {
    const r = lassoCaptureType({ selLevel: 'strand' })
    expect(r.strands).toBe(true)
    expect(r.domains).toBe(false)
    expect(r.ends).toBe(false)
  })

  it('overhangs/loops/skips are NOT lasso-capturable (they are visibility gates, not levels)', () => {
    const r = lassoCaptureType({ selLevel: 'default' })
    expect(r.overhangs).toBe(false)
    expect(r.loops).toBe(false)
    expect(r.skips).toBe(false)
  })
})
