import { describe, it, expect } from 'vitest'
import {
  LEVELS, TAB_CYCLE, BTN_LEVEL, LEVEL_BTN,
  normalizeLevel, nextTabLevel, toggleLevel, hoverPreviewTarget,
  lassoCaptureType, toggleClusterSelection,
} from './selection_level.js'

describe('selection_level — constants & maps', () => {
  it('LEVELS is the seven-state set (strand and base are distinct levels)', () => {
    expect(LEVELS).toEqual(['default', 'cluster', 'strand', 'domain', 'end', 'xover', 'base'])
  })

  it('Tab cycle is strand → domain → end → xover → base → none(default) — cluster excluded (button-only)', () => {
    expect(TAB_CYCLE).toEqual(['strand', 'domain', 'end', 'xover', 'base', 'default'])
    expect(TAB_CYCLE).not.toContain('cluster')
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
  it('from default/none → strand; unknown → strand', () => {
    expect(nextTabLevel('default')).toBe('strand')   // none → first
    expect(nextTabLevel(null)).toBe('strand')         // not in cycle → start
  })
  it('cluster is not in the cycle → Tab from cluster restarts at strand', () => {
    expect(nextTabLevel('cluster')).toBe('strand')   // cluster excluded → first
  })
  it('walks strand → domain → end → xover → base → none(default) → strand', () => {
    expect(nextTabLevel('strand')).toBe('domain')
    expect(nextTabLevel('domain')).toBe('end')
    expect(nextTabLevel('end')).toBe('xover')
    expect(nextTabLevel('xover')).toBe('base')      // base is the finest grain, last stop
    expect(nextTabLevel('base')).toBe('default')    // → none
    expect(nextTabLevel('default')).toBe('strand')  // wraps
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

  it('base level → base only; `ends`/`beadLevel` stay false so it can never drain into _ctrlBeads', () => {
    const r = lassoCaptureType({ selLevel: 'base' })
    expect(r.base).toBe(true)
    // The measurement pool guard: the end-bead lasso path is `useEnds && (beadLevel || isEnd)`,
    // and it pushes into _ctrlBeads (which measurement_tool expects to hold 2). Base must
    // not travel that path.
    expect(r.ends).toBe(false)
    expect(r.beadLevel).toBe(false)
    expect(r.strands).toBe(false)
    expect(r.domains).toBe(false)
    expect(r.cluster).toBe(false)
    expect(r.xover).toBe(false)
  })

  it('every non-base level leaves `base` false', () => {
    for (const lv of ['default', 'strand', 'domain', 'end', 'xover', 'cluster']) {
      expect(lassoCaptureType({ selLevel: lv }).base).toBe(false)
    }
  })

  it('the overhang filter still wins over base, like every other level', () => {
    const r = lassoCaptureType({ selLevel: 'base', overhangFilter: true })
    expect(r.overhangs).toBe(true)
    expect(r.base).toBe(false)
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

  it('overhangs/loops/skips are NOT lasso-capturable by default (they are visibility gates, not levels)', () => {
    const r = lassoCaptureType({ selLevel: 'default' })
    expect(r.overhangs).toBe(false)
    expect(r.loops).toBe(false)
    expect(r.skips).toBe(false)
  })

  it('overhang filter active → overhangs ONLY, taking precedence over the engaged level', () => {
    // Even if a fixed level is engaged, the overhang filter wins (same precedence as
    // a plain click / Ctrl+click give it).
    const r = lassoCaptureType({ selLevel: 'strand', overhangFilter: true })
    expect(r.overhangs).toBe(true)
    expect(r.strands).toBe(false)
    expect(r.domains).toBe(false)
    expect(r.ends).toBe(false)
    expect(r.xover).toBe(false)
    expect(r.cluster).toBe(false)
  })
})

describe('selection_level — toggleClusterSelection', () => {
  it('adds an absent cluster and unions its member strands', () => {
    const r = toggleClusterSelection({ clusterId: 'c1', memberStrandIds: ['s1', 's2'] })
    expect(r.clusterIds).toEqual(['c1'])
    expect(r.strandIds).toEqual(['s1', 's2'])
  })

  it('accumulates a second cluster (Ctrl+click after a plain click)', () => {
    const r = toggleClusterSelection({
      clusterIds: ['c1'], strandIds: ['s1', 's2'],
      clusterId: 'c2', memberStrandIds: ['s3'],
    })
    expect(r.clusterIds).toEqual(['c1', 'c2'])
    expect(r.strandIds).toEqual(['s1', 's2', 's3'])
  })

  it('removes a present cluster and drops its member strands', () => {
    const r = toggleClusterSelection({
      clusterIds: ['c1', 'c2'], strandIds: ['s1', 's2', 's3'],
      clusterId: 'c1', memberStrandIds: ['s1', 's2'],
    })
    expect(r.clusterIds).toEqual(['c2'])
    expect(r.strandIds).toEqual(['s3'])
  })

  it('presence is decided by the cluster pool, not by its strands being selected', () => {
    // s1/s2 already selected at STRAND level; the cluster itself is not in the pool,
    // so Ctrl+clicking it must ADD it, not toggle it off.
    const r = toggleClusterSelection({
      clusterIds: [], strandIds: ['s1', 's2'],
      clusterId: 'c1', memberStrandIds: ['s1', 's2'],
    })
    expect(r.clusterIds).toEqual(['c1'])
    expect(r.strandIds).toEqual(['s1', 's2'])
  })

  it('does not duplicate a strand shared by two selected clusters', () => {
    const r = toggleClusterSelection({
      clusterIds: ['c1'], strandIds: ['s1', 'shared'],
      clusterId: 'c2', memberStrandIds: ['shared', 's3'],
    })
    expect(r.strandIds).toEqual(['s1', 'shared', 's3'])
  })

  it('no clusterId → identity (returns copies)', () => {
    const clusterIds = ['c1'], strandIds = ['s1']
    const r = toggleClusterSelection({ clusterIds, strandIds, clusterId: null })
    expect(r.clusterIds).toEqual(['c1'])
    expect(r.strandIds).toEqual(['s1'])
    expect(r.clusterIds).not.toBe(clusterIds)
  })
})
