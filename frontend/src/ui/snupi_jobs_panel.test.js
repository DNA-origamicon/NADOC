// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import {
  formatProgress,
  jobDisplayName,
  snupiJobIsActive,
  launchBlocked,
  materialLabel,
  advancedGuards,
  solverLabel,
  runningJob,
  solveDetailText,
  detailStatusText,
  stageChip,
  formatSummary,
  snupiRunConfig,
  renderSnupiDisplayProgress,
  SNUPI_LAUNCH_RESOURCE,
} from './snupi_jobs_panel.js'

it('classifies Coarse/Fine launches as CPU work', () => {
  expect(SNUPI_LAUNCH_RESOURCE).toEqual({ usesGpu: false })
})

describe('renderSnupiDisplayProgress', () => {
  it('retains one named row per visualization subprocess', () => {
    const el = document.createElement('div')
    renderSnupiDisplayProgress(el, new Map([
      ['display-data', { done: 1, total: 1 }],
      ['reuse-scene', { done: 1, total: 1 }],
      ['apply', { done: 0, total: 1 }],
    ]))
    expect(el.querySelectorAll('[data-snupi-display-phase]')).toHaveLength(3)
    expect(el.textContent).toContain('Load predicted positions · 1 of 1')
    expect(el.textContent).toContain('Reuse matching live scene · 1 of 1')
    expect(el.textContent).toContain('Apply visualization · 0 of 1')
  })
})

describe('formatProgress', () => {
  it('is 100% when completed, blank when failed/stopped', () => {
    expect(formatProgress({ status: 'completed' })).toBe('100%')
    expect(formatProgress({ status: 'failed' })).toBe('')
    expect(formatProgress({ status: 'stopped' })).toBe('')
  })
  it('rounds the running overall fraction', () => {
    expect(formatProgress({ status: 'running' }, { overall: 0.42 })).toBe('42%')
    expect(formatProgress({ status: 'running' }, { overall: 0 })).toBe('…')
  })
  it('is blank for a null job', () => {
    expect(formatProgress(null)).toBe('')
  })
})

describe('jobDisplayName', () => {
  it('prefers the source-path stem', () => {
    expect(jobDisplayName({ design_source_path: 'a/b/6hbx100.nadoc', design_name: 'x' }))
      .toBe('6hbx100')
  })
  it('falls back to design_name', () => {
    expect(jobDisplayName({ design_name: 'bundle' })).toBe('bundle')
    expect(jobDisplayName({})).toBe('design')
    expect(jobDisplayName(null)).toBe('')
  })
})

describe('snupiJobIsActive', () => {
  it('is true for queued/preparing/running only', () => {
    for (const s of ['queued', 'preparing', 'running']) {
      expect(snupiJobIsActive({ status: s })).toBe(true)
    }
    for (const s of ['completed', 'failed', 'stopped']) {
      expect(snupiJobIsActive({ status: s })).toBe(false)
    }
    expect(snupiJobIsActive(null)).toBe(false)
  })
})

describe('launchBlocked', () => {
  it('blocks while launching', () => {
    expect(launchBlocked(true, [], null)).toBe(true)
  })
  it('blocks when any job in the list is active', () => {
    expect(launchBlocked(false, [{ status: 'completed' }, { status: 'running' }], null)).toBe(true)
  })
  it('blocks when the selected job is active', () => {
    expect(launchBlocked(false, [], { status: 'preparing' })).toBe(true)
  })
  it('allows when idle with no active jobs', () => {
    expect(launchBlocked(false, [{ status: 'completed' }], { status: 'completed' })).toBe(false)
  })
})

describe('materialLabel', () => {
  it('names snupi vs the cando baseline', () => {
    expect(materialLabel({ material: 'snupi' })).toBe('SNUPI')
    expect(materialLabel({ material: 'cando' })).toBe('CanDo (isotropic)')
    expect(materialLabel({})).toBe('SNUPI')   // default
    expect(materialLabel(null)).toBe('SNUPI')
  })
})

describe('solveDetailText', () => {
  it('shows the step counter and rate so a long solve visibly ticks', () => {
    const t = solveDetailText({ step: 4500, n_steps: 60000, steps_per_s: 148 })
    expect(t).toContain('step 4,500/60,000')
    expect(t).toContain('148 steps/s')
  })
  it('explains a restart — the ONE case where the step count goes backwards', () => {
    // On divergence the integrator halves dt and restarts the whole trajectory (a 2×/4× wall-clock
    // hit). Silent before; now it says so.
    expect(solveDetailText({ step: 100, n_steps: 60000, attempt: 2 }))
      .toContain('restart 2 (dt halved — diverged)')
    expect(solveDetailText({ step: 100, n_steps: 60000, attempt: 0 })).not.toContain('restart')
  })
  it('is blank when the job reports no detail', () => {
    expect(solveDetailText(null)).toBe('')
    expect(solveDetailText({})).toBe('')
  })
})

describe('runningJob', () => {
  it('finds the job in flight so Stop can target it, not the selected one', () => {
    const jobs = [
      { job_id: 'old', status: 'completed' },
      { job_id: 'live', status: 'running' },
    ]
    expect(runningJob(jobs)?.job_id).toBe('live')
  })
  it('is null when nothing is active — Stop stays greyed out', () => {
    expect(runningJob([{ job_id: 'a', status: 'completed' }])).toBeNull()
    expect(runningJob([])).toBeNull()
    expect(runningJob(undefined)).toBeNull()
  })
})

describe('solverLabel', () => {
  it('names Fine/Coarse from the nonlinear flag', () => {
    expect(solverLabel({ nonlinear: true })).toBe('Fine (nonlinear)')
    expect(solverLabel({ nonlinear: false })).toBe('Coarse (linear)')
  })
  it('distinguishes coarse-grained hydrodynamics from the exact per-bp friction', () => {
    // A coarse run only APPROXIMATES the RPY kinetics (1 hydrodynamic bead per k bp), so the label
    // must say so — it must not read as the exact friction.
    expect(solverLabel({ dynamics: true, hydrodynamics: true, hydro_coarse_bp: 8 }))
      .toBe('Dynamics (RPY, 1 bead/8 bp)')
    expect(solverLabel({ dynamics: true, hydrodynamics: true, hydro_coarse_bp: null }))
      .toBe('Dynamics (RPY, exact)')
  })
  it('names the Langevin dynamics modes when dynamics is set', () => {
    expect(solverLabel({ dynamics: true })).toBe('Dynamics (Langevin)')
    expect(solverLabel({ dynamics: true, hydrodynamics: true })).toBe('Dynamics (RPY, exact)')
  })
  it('names the free ssDNA tails — a NADOC extension published SNUPI cannot represent', () => {
    expect(solverLabel({ dynamics: true, tails: true })).toBe('Dynamics (Langevin) + ssDNA tails')
    expect(solverLabel({ dynamics: true, hydrodynamics: true, hydro_coarse_bp: 8, tails: true }))
      .toBe('Dynamics (RPY, 1 bead/8 bp) + ssDNA tails')
    expect(solverLabel({ nonlinear: true, tails: true })).toBe('Fine (nonlinear)')  // static: no tails
  })
})

describe('advancedGuards', () => {
  it('gates free ssDNA tails on the dynamics engine — they are absent from the static solve', () => {
    // The failure this replaces: the box looked armed, the flag was dropped, and a plain static
    // solve ran with no tails and no error.
    const off = advancedGuards({ dynamics: false, tails: true })
    expect(off.tailsDisabled).toBe(true)
    expect(off.tailsReason).toMatch(/dynamics/i)
    expect(advancedGuards({ dynamics: true }).tailsDisabled).toBe(false)
  })
  it('gates tails on the SNUPI material — CanDo has no ssDNA chain model', () => {
    expect(advancedGuards({ dynamics: true, material: 'cando' }).tailsDisabled).toBe(true)
    expect(advancedGuards({ dynamics: true, material: 'snupi' }).tailsDisabled).toBe(false)
  })
  it('gates hydrodynamics — and its coarse-bead size — on dynamics', () => {
    expect(advancedGuards({ dynamics: false }).hydroDisabled).toBe(true)
    expect(advancedGuards({ dynamics: true, hydrodynamics: false }).coarseDisabled).toBe(true)
    expect(advancedGuards({ dynamics: true, hydrodynamics: true }).coarseDisabled).toBe(false)
  })
  it('forbids EXACT friction with tails — an ssDNA bead needs its own radius, which only blobs carry', () => {
    expect(advancedGuards({ dynamics: true, hydrodynamics: true, tails: true }).exactDisabled).toBe(true)
    expect(advancedGuards({ dynamics: true, hydrodynamics: true, tails: false }).exactDisabled).toBe(false)
    // no hydrodynamics at all → the choice is moot, not forbidden
    expect(advancedGuards({ dynamics: true, tails: true }).exactDisabled).toBe(false)
  })
})

describe('detailStatusText', () => {
  it('shows the material + solver + ETA while running', () => {
    const t = detailStatusText({ status: 'running', nonlinear: true, material: 'snupi' },
      { overall: 0.5, eta_seconds: 12 })
    expect(t).toContain('SNUPI')
    expect(t).toContain('Fine (nonlinear)')
    expect(t).toContain('50%')
    expect(t).toContain('12s left')
  })
  it('summarises a completed job', () => {
    const t = detailStatusText({ status: 'completed', nonlinear: false, material: 'cando',
      sim_seconds: 3.2, n_nodes: 210 })
    expect(t).toContain('CanDo (isotropic)')
    expect(t).toContain('Coarse (linear)')
    expect(t).toContain('3.2s')
    expect(t).toContain('210 bp nodes')
  })
  it('surfaces the failure error', () => {
    expect(detailStatusText({ status: 'failed', error: 'no duplex core' }))
      .toBe('Failed: no duplex core')
  })
  it('is blank for a null job', () => {
    expect(detailStatusText(null)).toBe('')
  })
})

describe('stageChip', () => {
  it('renders the single solver stage glyph', () => {
    expect(stageChip({ nonlinear: true, stages: [{ name: 'nonlinear', status: 'done' }] }))
      .toBe('● nonlinear')
    // no stages → synthesizes from the nonlinear flag
    expect(stageChip({ nonlinear: false })).toBe('○ linear')
  })
})

describe('snupiRunConfig', () => {
  it('reads the field + anchors a job ran with (for repopulating the cards on select)', () => {
    const job = {
      field: { field_pN: 5, dir: [0, 1, 0] },
      anchors: [{ kind: 'base', helixId: 'h0', bp: 0, direction: 0 }],
    }
    const cfg = snupiRunConfig(job)
    expect(cfg.field).toEqual({ field_pN: 5, dir: [0, 1, 0] })
    expect(cfg.anchors).toHaveLength(1)
  })
  it('normalizes a no-field / no-anchor job to null + [] so the cards reset (off/empty)', () => {
    expect(snupiRunConfig({}).field).toBeNull()
    expect(snupiRunConfig({}).anchors).toEqual([])
    expect(snupiRunConfig(null)).toEqual({ field: null, anchors: [] })
    // a stray non-array anchors value never reaches applyConfig as a non-array
    expect(snupiRunConfig({ anchors: 'oops' }).anchors).toEqual([])
  })
})

describe('formatSummary', () => {
  it('is blank unless completed', () => {
    expect(formatSummary({ status: 'running' })).toBe('')
    expect(formatSummary(null)).toBe('')
  })
  it('shows material, solver, nodes, and the RMSF range', () => {
    const html = formatSummary({ status: 'completed', nonlinear: true, material: 'snupi',
      n_nodes: 210, rmsf_min_nm: 0.12, rmsf_max_nm: 0.88 })
    expect(html).toContain('SNUPI')
    expect(html).toContain('210 bp nodes')
    expect(html).toContain('RMSF 0.12–0.88 nm')
  })
})
