import { describe, expect, it } from 'vitest'
import {
  budgetHours, budgetState, estimateRows, runpodEstimateKey, runpodPlanShape,
  runpodReadiness, selectedRow, storageRows,
} from './md_job_wizard_runpod_model.js'

const stage = (role, steps, ns, dcdfreq = 5000) =>
  ({ role, steps, ns, params: { dcdfreq } })

// A ladder whose first chunk runs slow (the soft 1 fs chunk) and the rest at 4 fs.
const RELAX_PLAN = {
  stages: [
    stage('minimization', 10_000, 0.0),
    stage('settle', 100_000, 0.1),          // 1 fs
    stage('ladder', 240_000, 0.96),         // 4 fs
    stage('ladder', 240_000, 0.96),
  ],
}

const PROD_PLAN = {
  stages: [stage('production', 1_250_000, 5.0, 2500)],
}

const ROW = {
  key: 'NVIDIA GeForce RTX 4090', label: 'RTX 4090', sm: 'sm_89', vram_gb: 24,
  usd_per_hour: 0.69, live_price: true, available: true,
  ns_day: 24.0, ns_day_relax: 12.0,
  relax_hours: 4.0, relax_cost: 2.76,
  production_hours: 5.0, production_cost: 3.45,
  total_hours: 9.0, total_cost: 6.21,
}

describe('runpodPlanShape', () => {
  it('splits relaxation from production by stage role', () => {
    const s = runpodPlanShape({ stages: [...RELAX_PLAN.stages, ...PROD_PLAN.stages] })
    expect(s.relax_steps).toBe(590_000)
    expect(s.production_steps).toBe(1_250_000)
    expect(s.production_ns).toBeCloseTo(5.0, 3)
    expect(s.production_source).toBe('plan')
  })

  it('reports the step-weighted mean timestep, not a nominal one', () => {
    // 590k steps producing 2.02 ns => 3.42 fs mean, NOT the 4 fs the ladder nominally runs at.
    // Quoting 4 fs would under-report the ladder, which is the direction that costs money.
    const s = runpodPlanShape(RELAX_PLAN)
    expect(s.relax_timestep_fs).toBeCloseTo(1e6 * s.relax_ns / s.relax_steps, 3)
    expect(s.relax_timestep_fs).toBeLessThan(4.0)
  })

  it('keeps hours exact for a mixed-timestep ladder', () => {
    // hours = steps * ms_step / 3.6e6 — the timestep cancels, so a (ns, mean_dt) pair that is
    // consistent with the true step count gives the right wall-clock whatever the mix.
    const s = runpodPlanShape(RELAX_PLAN)
    const impliedSteps = 1e6 * s.relax_ns / s.relax_timestep_fs
    // Both numbers are rounded to 4 dp for the wire, so agree to 0.01% rather than exactly.
    expect(Math.abs(impliedSteps - s.relax_steps) / s.relax_steps).toBeLessThan(1e-4)
  })

  it('falls back to the intended production length when none is planned', () => {
    const s = runpodPlanShape(RELAX_PLAN, { productionNsIntent: 50 })
    expect(s.production_source).toBe('intent')
    expect(s.production_ns).toBe(50)
    expect(s.production_timestep_fs).toBe(4.0)
  })

  it('says so when there is no production at all', () => {
    expect(runpodPlanShape(RELAX_PLAN).production_source).toBe('none')
  })

  it('carries steps and dcd_freq per stage for the disk forecast', () => {
    const s = runpodPlanShape(PROD_PLAN)
    expect(s.stages).toEqual([{ steps: 1_250_000, dcd_freq: 2500 }])
  })

  it('never emits a zero dcd_freq', () => {
    const s = runpodPlanShape({ stages: [stage('ladder', 100, 0.4, 0)] })
    expect(s.stages[0].dcd_freq).toBe(1)
  })

  it('survives a missing plan', () => {
    expect(runpodPlanShape(null).relax_steps).toBe(0)
  })
})

describe('runpodEstimateKey', () => {
  const shape = runpodPlanShape(RELAX_PLAN, { productionNsIntent: 50 })

  it('is stable for an unchanged plan', () => {
    expect(runpodEstimateKey(shape)).toBe(runpodEstimateKey(runpodPlanShape(
      RELAX_PLAN, { productionNsIntent: 50 })))
  })

  it('moves when the production length moves', () => {
    const longer = runpodPlanShape(RELAX_PLAN, { productionNsIntent: 100 })
    expect(runpodEstimateKey(longer)).not.toBe(runpodEstimateKey(shape))
  })

  it('moves when the run length moves', () => {
    const longer = runpodPlanShape({ stages: [...RELAX_PLAN.stages, stage('ladder', 240_000, 0.96)] })
    expect(runpodEstimateKey(longer)).not.toBe(runpodEstimateKey(shape))
  })

  it('moves when dcd_freq moves — that changes BYTES even though cost is identical', () => {
    const dense = runpodPlanShape({ stages: [stage('ladder', 240_000, 0.96, 500)] })
    const sparse = runpodPlanShape({ stages: [stage('ladder', 240_000, 0.96, 5000)] })
    expect(runpodEstimateKey(dense)).not.toBe(runpodEstimateKey(sparse))
  })

  it('distinguishes live prices from indicative ones', () => {
    expect(runpodEstimateKey(shape, { connected: true }))
      .not.toBe(runpodEstimateKey(shape, { connected: false }))
  })

  it('does NOT move with the budget — a cap edit must cost no round trip', () => {
    // The budget is not part of the shape at all; this pins that it never sneaks in.
    expect(runpodEstimateKey({ ...shape, budget: 15 }))
      .toBe(runpodEstimateKey({ ...shape, budget: 999 }))
  })
})

describe('budgetHours', () => {
  it('says how long the cap buys on a card', () => {
    expect(budgetHours(15, 0.69)).toBeCloseTo(21.7, 1)
  })

  it('is shorter on a dearer card — the cap is a budget, not a duration', () => {
    expect(budgetHours(15, 2.99)).toBeLessThan(budgetHours(15, 0.69))
  })

  it('never promises less than the backend’s 15-minute floor', () => {
    expect(budgetHours(0.01, 100)).toBeCloseTo(0.25, 3)
  })

  it('returns null when either number is missing', () => {
    expect(budgetHours(null, 0.69)).toBeNull()
    expect(budgetHours(15, 0)).toBeNull()
  })
})

describe('budgetState', () => {
  const balance = { available: true, balance: 42 }

  it('flags an over-budget estimate', () => {
    const s = budgetState({ budget: { budget_usd: 5, estimated_usd: 6.21, over_budget: true },
      balance })
    expect(s.over).toBe(true)
    expect(s.message).toContain('$6.21')
    expect(s.message).toContain('$5.00')
  })

  it('is quiet when the estimate fits', () => {
    const s = budgetState({ budget: { budget_usd: 15, estimated_usd: 6.21, over_budget: false },
      balance })
    expect(s.over).toBe(false)
  })

  it('surfaces already-billing pods as a warning, with the burn rate', () => {
    const s = budgetState({
      budget: { budget_usd: 15, estimated_usd: 1, over_budget: false },
      balance,
      livePods: [{ id: 'p1', cost_per_hr: 0.69 }, { id: 'p2', cost_per_hr: 2.99 }],
    })
    expect(s.livePods).toBe(2)
    expect(s.billingPerHour).toBeCloseTo(3.68, 2)
    expect(s.billingMessage).toMatch(/2 pods already billing/)
  })

  it('exposes the raw balance for the gate, not just the sentence', () => {
    expect(budgetState({ budget: {}, balance }).balanceUsd).toBe(42)
    expect(budgetState({ budget: {}, balance: { available: false } }).balanceUsd).toBeNull()
  })
})

describe('estimateRows', () => {
  const shape = runpodPlanShape(RELAX_PLAN, { productionNsIntent: 50 })

  it('shows relaxation and production separately plus a total', () => {
    const labels = estimateRows(ROW, shape).map(r => r[0])
    expect(labels).toEqual(['Relaxation ladder', 'Production', 'Total'])
  })

  it('captions an intended production length as not yet planned', () => {
    const prod = estimateRows(ROW, shape).find(r => r[0] === 'Production')
    expect(prod[2]).toMatch(/intended/)
  })

  it('prompts for a production length when there is none', () => {
    const noProd = runpodPlanShape(RELAX_PLAN)
    const rows = estimateRows({ ...ROW, production_hours: null, production_cost: null }, noProd)
    expect(rows.find(r => r[0] === 'Production')[1]).toBe('not set')
  })

  it('returns nothing without a card', () => {
    expect(estimateRows(null, shape)).toEqual([])
  })
})

describe('storageRows', () => {
  it('reports output, upload and the volume', () => {
    const rows = storageRows({
      output_bytes: 5 * 1024 ** 3, package_bytes: 1024 ** 3,
      volume_size_gb: 50, used_known: false, free_bytes: 50 * 1024 ** 3,
      staging: { minutes: 13.2, usd: 0.18 },
    })
    const labels = rows.map(r => r[0])
    expect(labels).toContain('Trajectories + restarts')
    expect(labels).toContain('Upload before it starts')
    expect(labels).toContain('Network volume')
    expect(rows.find(r => r[0] === 'Upload before it starts')[2]).toMatch(/13.2 min/)
  })

  it('says free space is unmeasurable rather than implying it measured it', () => {
    const note = storageRows({ output_bytes: 1, volume_size_gb: 50, used_known: false })
      .find(r => r[0] === 'Network volume')[2]
    expect(note).toMatch(/not its free space/)
  })

  it('reports real free space once it is known', () => {
    const note = storageRows({
      output_bytes: 1, volume_size_gb: 50, used_known: true, free_bytes: 20 * 1024 ** 3,
    }).find(r => r[0] === 'Network volume')[2]
    expect(note).toMatch(/20.0 GB free/)
  })
})

describe('selectedRow', () => {
  const preview = { gpus: [ROW, { ...ROW, key: 'other', label: 'L40S' }] }

  it('returns the chosen card', () => {
    expect(selectedRow(preview, 'other').label).toBe('L40S')
  })

  it('falls back to the backend’s best-value row, never a re-sort', () => {
    expect(selectedRow(preview, null).label).toBe('RTX 4090')
    expect(selectedRow(preview, 'gone').label).toBe('RTX 4090')
  })
})

describe('runpodReadiness — the gate', () => {
  const ok = {
    preflight: { ok: true }, volumeId: 'vol1', gpuKey: ROW.key,
    preview: { gpus: [ROW] },
    budget: { over: false, estimated: 6.21, balanceUsd: 100 },
  }

  it('passes when everything is in place', () => {
    expect(runpodReadiness(ok)).toEqual({ ready: true, reason: '' })
  })

  it('blocks before the pre-flight has run', () => {
    expect(runpodReadiness({ ...ok, preflight: null }).ready).toBe(false)
  })

  it('reports the pre-flight’s own reason, not a generic one', () => {
    const r = runpodReadiness({ ...ok, preflight: { ok: false },
      blockReason: 'SSH key: not registered' })
    expect(r.reason).toBe('SSH key: not registered')
  })

  it('blocks on a missing volume before it asks for a GPU', () => {
    const r = runpodReadiness({ ...ok, volumeId: null, gpuKey: null })
    expect(r.reason).toMatch(/network volume/)
  })

  it('blocks while the estimate is in flight', () => {
    expect(runpodReadiness({ ...ok, busy: true }).reason).toMatch(/cost/)
  })

  it('blocks when no card is available at all', () => {
    expect(runpodReadiness({ ...ok, preview: { gpus: [] } }).reason).toMatch(/No compatible GPU/)
  })

  it('asks for a card, naming BOTH value axes', () => {
    const r = runpodReadiness({ ...ok, gpuKey: null })
    expect(r.reason).toMatch(/\$\/ns/)
    expect(r.reason).toMatch(/ns\/day/)
  })

  it('blocks over budget and says what to do', () => {
    const r = runpodReadiness({ ...ok,
      budget: { over: true, message: 'Estimated $18.40 against a $15.00 cap.', estimated: 18.4 } })
    expect(r.ready).toBe(false)
    expect(r.reason).toMatch(/Raise the cap or shorten the run/)
  })

  it('blocks when the balance cannot cover the run', () => {
    const r = runpodReadiness({ ...ok,
      budget: { over: false, estimated: 6.21, balanceUsd: 2.0 } })
    expect(r.ready).toBe(false)
    expect(r.reason).toMatch(/destroys every pod at \$0/)
  })

  it('does not block on an unknown balance', () => {
    expect(runpodReadiness({ ...ok,
      budget: { over: false, estimated: 6.21, balanceUsd: null } }).ready).toBe(true)
  })
})
