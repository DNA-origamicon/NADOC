import { describe, it, expect } from 'vitest'
import {
  newChainStage, isRelax, engineCanSeedFrom, stagePreflight, queuePreflightLevel,
  estimateStageSeconds, estimateTotalSeconds, formatDuration, groupIntoChains,
  chainGroups, liveStageBadge, latestHealthSample, toChainStagePayload,
} from './chain_sim_model.js'

const relax = (o = {}) => newChainStage({ protocol: 'relax', ...o })
const prod = (o = {}) => newChainStage({ protocol: 'production', ...o })

describe('newChainStage / isRelax', () => {
  it('defaults to an oxDNA production stage', () => {
    const s = newChainStage()
    expect(s.engine).toBe('oxdna')
    expect(s.protocol).toBe('production')
    expect(isRelax(s)).toBe(false)
    expect(isRelax(relax())).toBe(true)
  })
})

describe('engineCanSeedFrom', () => {
  it('allows same-engine and NAMD←oxDNA/mrDNA only', () => {
    expect(engineCanSeedFrom('oxdna', 'oxdna')).toBe(true)
    expect(engineCanSeedFrom('namd', 'namd')).toBe(true)
    expect(engineCanSeedFrom('namd', 'oxdna')).toBe(true)
    expect(engineCanSeedFrom('namd', 'mrdna')).toBe(true)
    expect(engineCanSeedFrom('oxdna', 'namd')).toBe(false)  // can't rebuild coarse from atomistic
    expect(engineCanSeedFrom('oxdna', null)).toBe(false)
  })
})

describe('stagePreflight', () => {
  it('errors on a production with no upstream and no seed job', () => {
    const stages = [prod({ engine: 'oxdna' })]
    const pf = stagePreflight(stages, 0)
    expect(pf.level).toBe('error')
    expect(pf.seedFrom).toBeNull()
  })

  it('greens a production seeded off an earlier relax stage, with a note', () => {
    const stages = [relax({ engine: 'oxdna' }), prod({ engine: 'oxdna' })]
    const pf = stagePreflight(stages, 1)
    expect(pf.level).toBe('ok')
    expect(pf.seedFrom.kind).toBe('stage')
    expect(pf.seedFrom.label).toMatch(/seeds from stage 1/)
  })

  it('greens a production seeded off an existing completed job, naming it', () => {
    const stages = [prod({ engine: 'namd', seed_job_id: 'j1', seed_job_name: 'relax-A', seed_engine: 'namd' })]
    const pf = stagePreflight(stages, 0)
    expect(pf.level).toBe('ok')
    expect(pf.seedFrom.kind).toBe('job')
    expect(pf.seedFrom.label).toMatch(/relax-A/)
  })

  it('errors when a supplied job list no longer contains the seed job', () => {
    const stages = [prod({ engine: 'namd', seed_job_id: 'ghost', seed_engine: 'namd' })]
    const completedJobs = [{ job_id: 'other', name: 'x', engine: 'namd' }]
    expect(stagePreflight(stages, 0, { completedJobs }).level).toBe('error')
  })

  it('errors when oxDNA tries to seed from a NAMD job', () => {
    const stages = [prod({ engine: 'oxdna', seed_job_id: 'jn', seed_engine: 'namd' })]
    expect(stagePreflight(stages, 0).level).toBe('error')
  })

  it('errors when oxDNA tries to seed from a NAMD predecessor', () => {
    const stages = [relax({ engine: 'namd' }), prod({ engine: 'oxdna' })]
    expect(stagePreflight(stages, 1).level).toBe('error')
  })

  it('allows a NAMD production seeded cross-engine from an oxDNA relax', () => {
    const stages = [relax({ engine: 'oxdna' }), prod({ engine: 'namd' })]
    const pf = stagePreflight(stages, 1)
    expect(pf.level).toBe('ok')
    expect(pf.seedFrom.kind).toBe('stage')
  })

  it('warns on a field with no anchor', () => {
    const stages = [relax({ engine: 'oxdna', field: { field_pN: 5, dir: [1, 0, 0] } })]
    expect(stagePreflight(stages, 0).level).toBe('warn')
  })

  it('clears the field warning once an anchor is present', () => {
    const stages = [relax({ engine: 'oxdna', field: { field_pN: 5, dir: [1, 0, 0] }, anchors: [{ strand_id: 's' }] })]
    expect(stagePreflight(stages, 0).level).toBe('ok')
  })

  it('clears the field warning when a surface opposes the field (deposition)', () => {
    // The real 6hbx100_1xT stage: field −y pressing into a +y floor holds it — no anchor.
    const stages = [relax({
      engine: 'oxdna',
      field: { field_pN: 5, dir: [0, -1, 0] },
      surface: { dir: [0, 1, 0], offset_nm: 0, stiff: 0.25 },
    })]
    expect(stagePreflight(stages, 0).level).toBe('ok')
  })

  it('still warns when the surface does not oppose the field (in-plane drift)', () => {
    const stages = [relax({
      engine: 'oxdna',
      field: { field_pN: 5, dir: [1, 0, 0] },        // in-plane vs a +y floor
      surface: { dir: [0, 1, 0], offset_nm: 0, stiff: 0.25 },
    })]
    expect(stagePreflight(stages, 0).level).toBe('warn')
  })

  it('warns on an Alpine stage with no cluster', () => {
    const stages = [relax({ engine: 'namd', run_target: 'alpine' })]
    expect(stagePreflight(stages, 0).level).toBe('warn')
  })
})

describe('queuePreflightLevel', () => {
  it('reports the worst level in the queue', () => {
    expect(queuePreflightLevel([relax(), prod()])).toBe('ok')
    expect(queuePreflightLevel([relax({ field: { field_pN: 3, dir: [1, 0, 0] } })])).toBe('warn')
    expect(queuePreflightLevel([prod()])).toBe('error')  // production first → error dominates
  })
})

describe('ETA', () => {
  it('estimates oxDNA by steps and NAMD by ns, totalling', () => {
    const stages = [
      relax({ engine: 'oxdna', steps: 1_000_000 }),
      prod({ engine: 'namd', length_ns: 10 }),
    ]
    const s0 = estimateStageSeconds(stages[0])
    const s1 = estimateStageSeconds(stages[1])
    expect(s0).toBeGreaterThan(0)
    expect(s1).toBeGreaterThan(0)
    expect(estimateTotalSeconds(stages)).toBeCloseTo(s0 + s1)
  })

  it('honors a measured oxDNA throughput override', () => {
    const st = prod({ engine: 'oxdna', steps: 2_000_000 })
    const slow = estimateStageSeconds(st, { oxdnaStepsPerSec: 1e5 })
    const fast = estimateStageSeconds(st, { oxdnaStepsPerSec: 1e7 })
    expect(slow).toBeGreaterThan(fast)
  })

  it('formats durations compactly', () => {
    expect(formatDuration(0)).toBe('≈ —')
    expect(formatDuration(90)).toMatch(/m/)
    expect(formatDuration(3 * 86400)).toMatch(/day/)
  })
})

describe('groupIntoChains', () => {
  it('folds a relax + N productions into ONE rootless chain', () => {
    const stages = [
      relax({ engine: 'oxdna' }),
      prod({ engine: 'oxdna', steps: 1e6 }),
      prod({ engine: 'oxdna', steps: 2e6 }),
    ]
    const chains = groupIntoChains(stages)
    expect(chains).toHaveLength(1)
    expect(chains[0].root_job_id).toBeNull()
    expect(chains[0].root_engine).toBe('oxdna')
    expect(chains[0].stages).toHaveLength(3)
    expect(chains[0].stages[0].protocol).toBe('relax')
  })

  it('splits two engines into two chains', () => {
    const stages = [
      relax({ engine: 'oxdna' }), prod({ engine: 'oxdna' }),
      relax({ engine: 'namd' }), prod({ engine: 'namd' }),
    ]
    const chains = groupIntoChains(stages)
    expect(chains).toHaveLength(2)
    expect(chains[0].root_engine).toBe('oxdna')
    expect(chains[1].root_engine).toBe('namd')
  })

  it('roots a chain at an existing completed job via seed_job_id', () => {
    const stages = [
      prod({ engine: 'namd', seed_job_id: 'jrelax', seed_job_name: 'R', seed_engine: 'namd' }),
      prod({ engine: 'namd' }),
    ]
    const chains = groupIntoChains(stages)
    expect(chains).toHaveLength(1)
    expect(chains[0].root_job_id).toBe('jrelax')
    expect(chains[0].root_engine).toBe('namd')
    expect(chains[0].stages).toHaveLength(2)
  })

  it('skips a preflight-error stage rather than emitting an invalid chain', () => {
    const stages = [prod({ engine: 'oxdna' })]   // orphan production
    expect(groupIntoChains(stages)).toHaveLength(0)
  })

  it('toChainStagePayload drops a disabled field and UI-only keys', () => {
    const p = toChainStagePayload(prod({ engine: 'oxdna', field: { enabled: false, field_pN: 5, dir: [1, 0, 0] }, seed_job_id: 'x' }))
    expect(p.field).toBeNull()
    expect(p).not.toHaveProperty('seed_job_id')
    expect(p).not.toHaveProperty('id')
  })
})

describe('chainGroups (launch mapping)', () => {
  it('keeps the model stages (with ids) per lineage, parallel to groupIntoChains', () => {
    const stages = [
      relax({ engine: 'oxdna', id: 'a' }),
      prod({ engine: 'oxdna', id: 'b' }),
      relax({ engine: 'namd', id: 'c' }),
    ]
    const groups = chainGroups(stages)
    expect(groups).toHaveLength(2)
    expect(groups[0].stages.map((s) => s.id)).toEqual(['a', 'b'])   // stage ids preserved for the live map
    expect(groups[1].stages.map((s) => s.id)).toEqual(['c'])
    // groupIntoChains is the payload projection of the same grouping.
    expect(groupIntoChains(stages)).toHaveLength(2)
  })
})

describe('liveStageBadge / latestHealthSample', () => {
  it('maps executor status to a queued/running/done/failed badge', () => {
    expect(liveStageBadge('running').label).toBe('running')
    expect(liveStageBadge('done').symbol).toBe('✓')
    expect(liveStageBadge('failed').color).toBe('#d9534f')
    expect(liveStageBadge('pending').label).toBe('queued')
    expect(liveStageBadge(undefined).label).toBe('queued')   // safe fallback
  })

  it('returns the latest health sample or null', () => {
    expect(latestHealthSample(null)).toBeNull()
    expect(latestHealthSample({ health_samples: [] })).toBeNull()
    expect(latestHealthSample({ health_samples: [{ passed: true }, { passed: false }] })).toEqual({ passed: false })
  })
})
