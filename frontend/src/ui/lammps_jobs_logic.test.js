import { describe, it, expect } from 'vitest'
import {
  progressPct, jobIsActive, anyActive, runButtonState, availabilityMessage,
  jobRowLabel, buildCreatePayload, jobIsViewable, flexStatusText, maxRanks, ranksError, freeRanks,
} from './lammps_jobs_logic.js'

describe('progressPct', () => {
  it('is 0 when steps is missing/zero', () => {
    expect(progressPct({ current_step: 500 })).toBe(0)
    expect(progressPct({ steps: 0, current_step: 5 })).toBe(0)
  })
  it('rounds current/steps and clamps to [0,100]', () => {
    expect(progressPct({ steps: 1000, current_step: 400 })).toBe(40)
    expect(progressPct({ steps: 1000, current_step: 5000 })).toBe(100)
    expect(progressPct({ steps: 1000, current_step: -5 })).toBe(0)
  })
})

describe('jobIsActive / anyActive', () => {
  it('active for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) expect(jobIsActive({ status: s })).toBe(true)
    for (const s of ['completed', 'failed', 'stopped']) expect(jobIsActive({ status: s })).toBe(false)
  })
  it('anyActive scans the list', () => {
    expect(anyActive([{ status: 'completed' }, { status: 'running' }])).toBe(true)
    expect(anyActive([{ status: 'completed' }, { status: 'failed' }])).toBe(false)
    expect(anyActive([])).toBe(false)
  })
})

describe('runButtonState', () => {
  it('checking when availability unknown', () => {
    expect(runButtonState(null).enabled).toBe(false)
  })
  it('disabled + reason when LAMMPS missing', () => {
    const st = runButtonState({ available: false })
    expect(st.enabled).toBe(false)
    expect(st.label).toMatch(/not installed/)
  })
  it('disabled + reason when CG-DNA missing', () => {
    const st = runButtonState({ available: true, cgdna_capable: false })
    expect(st.enabled).toBe(false)
    expect(st.label).toMatch(/CG-DNA/)
  })
  it('enabled when available + CG-DNA capable', () => {
    const st = runButtonState({ available: true, cgdna_capable: true })
    expect(st.enabled).toBe(true)
    expect(st.label).toMatch(/Run on LAMMPS/)
  })
})

describe('availabilityMessage', () => {
  it('reflects the three states', () => {
    expect(availabilityMessage({ available: false })).toMatch(/not installed/)
    expect(availabilityMessage({ available: true, cgdna_capable: false })).toMatch(/CG-DNA/)
    expect(availabilityMessage({ available: true, cgdna_capable: true })).toMatch(/ready/)
  })
})

describe('jobRowLabel', () => {
  it('shows progress for active, frames for completed', () => {
    expect(jobRowLabel({ design_name: '6hb', status: 'running', steps: 1000, current_step: 400 }))
      .toBe('6hb — running 40%')
    expect(jobRowLabel({ design_name: '6hb', status: 'completed', frames: 5 }))
      .toBe('6hb — completed (5 frames)')
    expect(jobRowLabel({ design_name: '6hb', status: 'failed' })).toBe('6hb — failed')
  })
})

describe('jobIsViewable', () => {
  it('true only for a finished run with frames', () => {
    expect(jobIsViewable({ status: 'completed', frames: 5 })).toBe(true)
    expect(jobIsViewable({ status: 'stopped', frames: 2 })).toBe(true)
    expect(jobIsViewable({ status: 'completed', frames: 0 })).toBe(false)
    expect(jobIsViewable({ status: 'running', frames: 5 })).toBe(false)
    expect(jobIsViewable(null)).toBe(false)
  })
})

describe('flexStatusText', () => {
  it('summarizes RMSF and flags a short run as preliminary', () => {
    const s = flexStatusText({ ok: true, min: 0.001, max: 0.05, nFrames: 6 })
    expect(s).toMatch(/RMSF 0.001–0.050 nm over 6 frames/)
    expect(s).toMatch(/preliminary/)
  })
  it('no preliminary note for a long run; empty for a failed result', () => {
    expect(flexStatusText({ ok: true, min: 0.1, max: 0.4, nFrames: 50 })).not.toMatch(/preliminary/)
    expect(flexStatusText({ ok: false })).toBe('')
  })
})

describe('buildCreatePayload', () => {
  it('applies defaults for blank/invalid input', () => {
    expect(buildCreatePayload({})).toEqual({
      steps: 100000, dump_every: 1000, temperature: 0.1, salt_molar: 0.5, ranks: 1,
    })
  })
  it('coerces valid strings and floors ranks at 1', () => {
    const p = buildCreatePayload({ steps: '5000', dumpEvery: '250', temperature: '0.09', salt: '0.3', ranks: '0' })
    expect(p).toEqual({ steps: 5000, dump_every: 250, temperature: 0.09, salt_molar: 0.3, ranks: 1 })
  })
  it('omits design path + forces when absent', () => {
    const p = buildCreatePayload({})
    expect('design_source_path' in p).toBe(false)
    expect('field' in p).toBe(false)
    expect('anchors' in p).toBe(false)
  })
  it('attaches design path, a positive field, and non-empty anchors', () => {
    const p = buildCreatePayload({
      designSourcePath: '/ws/d.nadoc',
      field: { field_pN: 30, dir: [1, 0, 0] },
      anchors: [{ kind: 'strand', id: 's1' }],
    })
    expect(p.design_source_path).toBe('/ws/d.nadoc')
    expect(p.field).toEqual({ field_pN: 30, dir: [1, 0, 0] })
    expect(p.anchors).toEqual([{ kind: 'strand', id: 's1' }])
  })
  it('drops a zero-magnitude field and empty anchors', () => {
    const p = buildCreatePayload({ field: { field_pN: 0, dir: [1, 0, 0] }, anchors: [] })
    expect('field' in p).toBe(false)
    expect('anchors' in p).toBe(false)
  })
  it('attaches a surface wall with positive stiffness, drops a zero-stiffness one', () => {
    const wall = { dir: [0, 1, 0], offset_nm: 0.5, stiff: 5 }
    expect(buildCreatePayload({ wall }).wall).toEqual(wall)
    expect('wall' in buildCreatePayload({ wall: { dir: [0, 1, 0], offset_nm: 0, stiff: 0 } })).toBe(false)
  })
  it('clamps ranks to the core ceiling when cores is given', () => {
    expect(buildCreatePayload({ ranks: '16', cores: 4 }).ranks).toBe(4)
    expect(buildCreatePayload({ ranks: '2', cores: 4 }).ranks).toBe(2)   // under → unchanged
    expect(buildCreatePayload({ ranks: '16' }).ranks).toBe(16)           // no ceiling → unclamped
  })
})

describe('maxRanks', () => {
  it('reads a positive max_ranks, else falls back to 1', () => {
    expect(maxRanks({ max_ranks: 16 })).toBe(16)
    expect(maxRanks({ max_ranks: 0 })).toBe(1)
    expect(maxRanks(null)).toBe(1)
    expect(maxRanks({})).toBe(1)
  })
})

describe('freeRanks', () => {
  it('reads free_ranks, clamps to the ceiling, falls back to the ceiling', () => {
    expect(freeRanks({ max_ranks: 16, free_ranks: 6 })).toBe(6)
    expect(freeRanks({ max_ranks: 16, free_ranks: 99 })).toBe(16)   // clamp to cap
    expect(freeRanks({ max_ranks: 16 })).toBe(16)                   // missing → cap
    expect(freeRanks({ max_ranks: 16, free_ranks: 0 })).toBe(16)    // invalid → cap
    expect(freeRanks(null)).toBe(1)                                 // nothing → 1
  })
})

describe('ranksError', () => {
  it('flags a request over the core count and passes when within', () => {
    expect(ranksError(3, 2)).toMatch(/only 2 CPU cores/)
    expect(ranksError(2, 2)).toBeNull()
    expect(ranksError(1, 16)).toBeNull()
  })
  it('singularizes a one-core machine', () => {
    expect(ranksError(2, 1)).toMatch(/1 CPU core /)
  })
})
