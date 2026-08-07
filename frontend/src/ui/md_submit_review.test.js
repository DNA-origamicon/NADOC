/**
 * Unit tests for the pure helpers of md_submit_review.js (Phase-4 Alpine submit).
 * All pure — no DOM needed.
 */
import { describe, it, expect } from 'vitest'
import {
  fmtQueueMinutes, fmtNs, formatResourceSummary, reviewSubmitPayload,
  alpineTargetDisabledReason, remoteJobBadge, partitionSelectOptions, qosSelectOptions,
} from './md_submit_review.js'

describe('fmtQueueMinutes', () => {
  it('formats sub-hour, hour, and hour+min', () => {
    expect(fmtQueueMinutes(0)).toBe('~0 min')
    expect(fmtQueueMinutes(45)).toBe('~45 min')
    expect(fmtQueueMinutes(60)).toBe('~1 h')
    expect(fmtQueueMinutes(135)).toBe('~2 h 15 min')
  })
  it('returns unknown for null/NaN', () => {
    expect(fmtQueueMinutes(null)).toBe('unknown')
    expect(fmtQueueMinutes(Infinity)).toBe('unknown')
  })
})

describe('fmtNs', () => {
  it('scales precision by magnitude', () => {
    expect(fmtNs(250)).toBe('250')
    expect(fmtNs(19.2)).toBe('19.2')
    expect(fmtNs(1.234)).toBe('1.23')
  })
  it('guards missing values', () => {
    expect(fmtNs(null)).toBe('?')
    expect(fmtNs(NaN)).toBe('?')
  })
})

describe('formatResourceSummary', () => {
  const rec = {
    n_atoms: 178518, total_ns: 19.2,
    resources: {
      partition: 'aa100', kind: 'gpu', gpus: 1, cores: 8, mem_gb: 19,
      walltime: '42:30:00', qos: 'long', expected_ns_per_day: 16.2, measured: false,
      est_queue_min: 135, est_cost_su: 4944, safety_factor: 1.5,
      notes: ['No measured throughput yet — guessing.'],
    },
  }
  it('builds display strings from the recommendation', () => {
    const s = formatResourceSummary(rec)
    expect(s.system).toBe('178,518 atoms')
    expect(s.totalNs).toBe('19.2 ns total')
    expect(s.partition).toBe('aa100 (gpu)')
    expect(s.hardware).toBe('1 GPU · 8 core · 19 GB')
    expect(s.walltime).toBe('42:30:00')
    expect(s.qos).toBe('long')
    expect(s.throughput).toBe('16.2 ns/day (estimated)')
    expect(s.queue).toBe('~2 h 15 min')
    expect(s.cost).toBe('4,944 SU')
    expect(s.notes).toHaveLength(1)
  })
  it('marks measured throughput distinctly', () => {
    const s = formatResourceSummary({ ...rec, resources: { ...rec.resources, measured: true } })
    expect(s.throughput).toBe('16.2 ns/day (measured)')
  })
  it('tolerates a missing resources block', () => {
    const s = formatResourceSummary({ n_atoms: 0 })
    expect(s.partition).toBe('? (?)')
    expect(s.cost).toBe('unknown')
    expect(s.notes).toEqual([])
  })
})

describe('reviewSubmitPayload', () => {
  const base = { partition: 'aa100', gpus: 1, cores: 8, mem_gb: 19, walltime: '10:00:00', qos: 'normal' }
  it('sends only the cluster name when nothing was edited (auto-recommend)', () => {
    expect(reviewSubmitPayload({ baseResources: base, overrides: {} }))
      .toEqual({ cluster_name: 'alpine' })
  })
  it('treats blank/null overrides as unchanged', () => {
    expect(reviewSubmitPayload({ baseResources: base, overrides: { partition: '', cores: null } }))
      .toEqual({ cluster_name: 'alpine' })
  })
  it('merges edits onto the base and coerces numeric fields', () => {
    const p = reviewSubmitPayload({
      baseResources: base, overrides: { cores: '16', walltime: '20:00:00' },
    })
    expect(p.cluster_name).toBe('alpine')
    expect(p.resources.cores).toBe(16)          // coerced to number
    expect(p.resources.walltime).toBe('20:00:00')
    expect(p.resources.partition).toBe('aa100') // base preserved
  })
  it('drops non-numeric numeric overrides', () => {
    const p = reviewSubmitPayload({ baseResources: base, overrides: { gpus: 'abc', qos: 'long' } })
    expect(p.resources.gpus).toBe(1)            // kept base, junk dropped
    expect(p.resources.qos).toBe('long')
  })
  it('honours a custom cluster name', () => {
    expect(reviewSubmitPayload({ clusterName: 'summit', overrides: {} }))
      .toEqual({ cluster_name: 'summit' })
  })
})

describe('alpineTargetDisabledReason', () => {
  it('returns null only when connected', () => {
    expect(alpineTargetDisabledReason('connected')).toBeNull()
  })
  it('explains each not-connected state', () => {
    expect(alpineTargetDisabledReason('connecting')).toMatch(/Connecting/)
    expect(alpineTargetDisabledReason('expired')).toMatch(/expired/)
    expect(alpineTargetDisabledReason('disconnected')).toMatch(/Connect/)
    expect(alpineTargetDisabledReason(undefined)).toMatch(/Connect/)
  })
})

describe('partitionSelectOptions', () => {
  const rec = {
    resources: { partition: 'acpu' },
    available_partitions: [
      { name: 'aa100', kind: 'gpu', gpu_model: 'NVIDIA A100' },
      { name: 'acpu', kind: 'cpu', gpu_model: '' },
      { name: 'acpu', kind: 'cpu' },          // duplicate
    ],
  }
  it('builds labelled, deduped options and marks the current partition selected', () => {
    const opts = partitionSelectOptions(rec)
    expect(opts).toHaveLength(2)                 // duplicate dropped
    expect(opts[0]).toEqual({ value: 'aa100', label: 'aa100 (gpu) — NVIDIA A100', selected: false })
    expect(opts[1]).toEqual({ value: 'acpu', label: 'acpu (cpu)', selected: true })
  })
  it('injects the current partition when the profile list omits it', () => {
    const opts = partitionSelectOptions({ resources: { partition: 'foo' }, available_partitions: [] })
    expect(opts).toEqual([{ value: 'foo', label: 'foo', selected: true }])
  })
  it('tolerates a missing recommendation', () => {
    expect(partitionSelectOptions(null)).toEqual([])
    expect(partitionSelectOptions({})).toEqual([])
  })
})

describe('qosSelectOptions', () => {
  const rec = {
    resources: { qos: 'gpu-long' },
    available_qos: [
      { name: 'gpu-normal', max_walltime_h: 24 },
      { name: 'gpu-long', max_walltime_h: 168 },
      { name: 'gpu-testing', max_walltime_h: 1 },
    ],
  }
  it('labels tiers with their ceiling and marks the current one selected', () => {
    const opts = qosSelectOptions(rec)
    expect(opts).toEqual([
      { value: 'gpu-normal', label: 'gpu-normal (≤24 h)', selected: false },
      { value: 'gpu-long', label: 'gpu-long (≤168 h)', selected: true },
      { value: 'gpu-testing', label: 'gpu-testing (≤1 h)', selected: false },
    ])
  })
  it('injects the current qos when the list omits it, and tolerates missing data', () => {
    expect(qosSelectOptions({ resources: { qos: 'weird' }, available_qos: [] }))
      .toEqual([{ value: 'weird', label: 'weird', selected: true }])
    expect(qosSelectOptions(null)).toEqual([])
  })
})

describe('remoteJobBadge', () => {
  it('is empty for local jobs', () => {
    expect(remoteJobBadge({ execution_target: 'local' })).toBe('')
    expect(remoteJobBadge(null)).toBe('')
  })
  it('shows SLURM id + partition once submitted', () => {
    expect(remoteJobBadge({
      execution_target: 'alpine', slurm_job_id: '12345', resources: { partition: 'aa100' },
    })).toBe('SLURM 12345 · aa100')
  })
  it('falls back to Alpine before submission', () => {
    expect(remoteJobBadge({ execution_target: 'alpine' })).toBe('Alpine')
  })
})
