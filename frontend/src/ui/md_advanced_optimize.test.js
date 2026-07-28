import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  OPTIMIZE_STAGES,
  buildCaveats,
  buildPlan,
  buildPreflight,
  createOptimizeProgress,
  describeRunPath,
  formatStageLine,
  initAdvancedOptimize,
  planHasChanges,
  productionTimestepWarning,
  gpuResidentWarning,
  residentModeFromRecommendation,
  RESIDENT_MIN_ATOMS,
  renderRunPath,
  stagePercent,
} from './md_advanced_optimize.js'

describe('gpu_resident is part of the ⚡ plan', () => {
  it('appears as a diff row, so Optimize can no longer silently skip it', () => {
    // The backend always computed rec.gpu_resident; the card just never listed it, so
    // ⚡ claimed to optimise the run path while leaving this control untouched.
    const plan = buildPlan({ gpu_resident: true }, { gpu_resident: 'auto' })
    const row = plan.find(r => r.key === 'gpu_resident')
    expect(row).toBeTruthy()
    expect(row.label).toBe('GPU-resident')
    expect(row.from).toBe('auto')
    expect(row.to).toBe('on')
    expect(row.changed).toBe(true)
  })

  it('is not in the plan when the backend has no opinion (null)', () => {
    expect(buildPlan({ gpu_resident: null }, { gpu_resident: 'auto' })
      .some(r => r.key === 'gpu_resident')).toBe(false)
  })

  it('maps the recommender\'s boolean onto the select, never back to auto', () => {
    // 'auto' would mean "no opinion" and would throw the recommendation away.
    expect(residentModeFromRecommendation(true)).toBe('on')
    expect(residentModeFromRecommendation(false)).toBe('off')
    expect(residentModeFromRecommendation(null)).toBeNull()
    expect(residentModeFromRecommendation(undefined)).toBeNull()
  })
})

describe('gpuResidentWarning — forcing a mode against the system size', () => {
  it('warns that forcing ON below the crossover is SLOWER, not faster', () => {
    const w = gpuResidentWarning({ mode: 'on', nAtoms: 32_566 })
    expect(w?.tone).toBe('warn')
    expect(w.message).toMatch(/SLOWER/)
    expect(w.message).toMatch(/32,566/)
  })

  it('warns that forcing OFF above the crossover gives up a real speed-up', () => {
    const w = gpuResidentWarning({ mode: 'off', nAtoms: 3_139_238 })
    expect(w?.tone).toBe('warn')
    expect(w.message).toMatch(/3\.2×|3\.2x/)
  })

  it('says nothing when a forced mode agrees with the size', () => {
    expect(gpuResidentWarning({ mode: 'on', nAtoms: 3_139_238 })).toBeNull()
    expect(gpuResidentWarning({ mode: 'off', nAtoms: 32_566 })).toBeNull()
  })

  it('says nothing on auto, or before the design has been sized', () => {
    expect(gpuResidentWarning({ mode: 'auto', nAtoms: 32_566 })).toBeNull()
    expect(gpuResidentWarning({ mode: 'on', nAtoms: null })).toBeNull()
    expect(gpuResidentWarning({ mode: 'on' })).toBeNull()
    expect(gpuResidentWarning()).toBeNull()
  })

  it('uses the same crossover the backend gate uses', () => {
    expect(RESIDENT_MIN_ATOMS).toBe(100_000)
    expect(gpuResidentWarning({ mode: 'on', nAtoms: RESIDENT_MIN_ATOMS })).toBeNull()
    expect(gpuResidentWarning({ mode: 'on', nAtoms: RESIDENT_MIN_ATOMS - 1 })).toBeTruthy()
  })
})

describe('buildPlan', () => {
  it('diffs recommended against current and flags what changes', () => {
    const plan = buildPlan(
      { threads: 6, compute: 'gpu', water_shell_a: 12, fast: true },
      { threads: 16, compute: 'gpu', water_shell_a: 0, fast: true },
    )
    const by = Object.fromEntries(plan.map(r => [r.key, r]))
    expect(by.threads.changed).toBe(true)
    expect(by.threads.from).toBe('16')
    expect(by.threads.to).toBe('6')
    expect(by.water_shell_a.changed).toBe(true)
    expect(by.compute.changed).toBe(false)   // same value → not a change
    expect(by.fast.changed).toBe(false)
  })

  it('omits fields the backend has no opinion about (null/undefined)', () => {
    const plan = buildPlan({ threads: 6, water_shell_a: null }, { threads: 4, water_shell_a: 8 })
    expect(plan.map(r => r.key)).toEqual(['threads'])   // water_shell_a must be left alone
  })

  it('renders booleans as on/off rather than true/false', () => {
    const [row] = buildPlan({ fast: false }, { fast: true })
    expect(row.from).toBe('on')
    expect(row.to).toBe('off')
    expect(row.changed).toBe(true)
  })

  it('appends units so the table reads as physical quantities', () => {
    const [row] = buildPlan({ water_shell_a: 12 }, { water_shell_a: 0 })
    expect(row.to).toBe('12 Å')
  })

  it('carries the raw value through for apply()', () => {
    const [row] = buildPlan({ threads: 6 }, { threads: 1 })
    expect(row.value).toBe(6)               // not the formatted string
  })
})

describe('planHasChanges', () => {
  it('is false when the recommendation matches the form', () => {
    expect(planHasChanges(buildPlan({ threads: 6 }, { threads: 6 }))).toBe(false)
  })
  it('is true when anything differs', () => {
    expect(planHasChanges(buildPlan({ threads: 6 }, { threads: 8 }))).toBe(true)
  })
})

describe('buildCaveats', () => {
  it('keeps the backend warnings AND always adds the estimate/scope/machine caveats', () => {
    const caveats = buildCaveats({ warnings: ['carve disables GPU-resident'] })
    expect(caveats[0]).toMatch(/GPU-resident/)
    expect(caveats.join(' ')).toMatch(/ESTIMATES/)
    expect(caveats.join(' ')).toMatch(/does NOT.*force field/i)
    expect(caveats.join(' ')).toMatch(/another\s+computer/i)
  })

  it('still warns even when the backend sent no warnings', () => {
    expect(buildCaveats({}).length).toBeGreaterThan(0)
  })
})

describe('describeRunPath — the rule that a carve kills GPU-resident', () => {
  it('full box + fast on GPU is GPU-resident', () => {
    const p = describeRunPath({ compute: 'gpu', water_shell_a: 0, fast: true })
    expect(p.gpuResident).toBe(true)
    expect(p.label).toBe('GPU-resident')
    expect(p.tone).toBe('ok')
  })

  it('ANY water-shell carve disables GPU-resident', () => {
    const p = describeRunPath({ compute: 'gpu', water_shell_a: 12, fast: true })
    expect(p.gpuResident).toBe(false)
    expect(p.label).toBe('CUDA offload')
    expect(p.tone).toBe('warn')
    expect(p.detail).toMatch(/vacuum/)
  })

  it('fast off disables GPU-resident even on a full box', () => {
    expect(describeRunPath({ compute: 'gpu', water_shell_a: 0, fast: false }).gpuResident).toBe(false)
  })

  it('CPU compute is never GPU-resident', () => {
    const p = describeRunPath({ compute: 'cpu', water_shell_a: 0, fast: true })
    expect(p.gpuResident).toBe(false)
    expect(p.label).toMatch(/CPU/)
  })

  it('treats a string shell value from the DOM as a number', () => {
    expect(describeRunPath({ compute: 'gpu', water_shell_a: '12', fast: true }).gpuResident).toBe(false)
  })
})

describe('productionTimestepWarning — dt vs the fast relaxation ladder', () => {
  it('no warning when the fast ladder is on, at any timestep', () => {
    expect(productionTimestepWarning({ timestepFs: 4, fastLadder: true })).toBeNull()
    expect(productionTimestepWarning({ timestepFs: 2, fastLadder: true })).toBeNull()
    expect(productionTimestepWarning({ timestepFs: 1, fastLadder: true })).toBeNull()
  })

  it('4 fs without the fast ladder is an error (no HMR PSF → RATTLE)', () => {
    const w = productionTimestepWarning({ timestepFs: 4, fastLadder: false })
    expect(w.tone).toBe('error')
    expect(w.message).toMatch(/fast relaxation ladder/i)
  })

  it('2 fs without the fast ladder is a soft warning', () => {
    const w = productionTimestepWarning({ timestepFs: 2, fastLadder: false })
    expect(w.tone).toBe('warn')
  })

  it('1 fs conservative is always safe, ladder or not', () => {
    expect(productionTimestepWarning({ timestepFs: 1, fastLadder: false })).toBeNull()
  })

  it('coerces a string dropdown value and defaults to no warning', () => {
    expect(productionTimestepWarning({ timestepFs: '4', fastLadder: false }).tone).toBe('error')
    expect(productionTimestepWarning({})).toBeNull()   // defaults: 4 fs + ladder on
  })
})

describe('renderRunPath', () => {
  it('paints the label and detail into the element', () => {
    const el = document.createElement('div')
    renderRunPath(el, { compute: 'gpu', water_shell_a: 12, fast: true })
    expect(el.innerHTML).toMatch(/CUDA offload/)
    expect(el.title).toMatch(/vacuum/)
  })
  it('is a no-op on a missing element', () => {
    expect(() => renderRunPath(null, {})).not.toThrow()
  })
})

describe('progress', () => {
  it('stagePercent advances only at real stage boundaries', () => {
    expect(stagePercent(0, 3)).toBe(0)
    expect(stagePercent(1, 3)).toBe(33)
    expect(stagePercent(3, 3)).toBe(100)
  })

  it('stagePercent clamps rather than overflowing', () => {
    expect(stagePercent(9, 3)).toBe(100)
    expect(stagePercent(-1, 3)).toBe(0)
    expect(stagePercent(1, 0)).toBe(0)
  })

  it('formatStageLine names the step and shows real elapsed seconds', () => {
    const line = formatStageLine(1, 12)
    expect(line).toMatch(/^Step 2\/3/)
    expect(line).toMatch(/heavy-atom model/)
    expect(line).toMatch(/12s/)
  })

  it('formatStageLine omits the timer before a second has passed', () => {
    expect(formatStageLine(0, 0)).not.toMatch(/0s/)
  })

  it('formatStageLine is empty for an out-of-range stage', () => {
    expect(formatStageLine(99, 1)).toBe('')
  })

  it('createOptimizeProgress paints the bar + status and can be hidden', () => {
    const el = document.createElement('div')
    const p = createOptimizeProgress(el)
    p.stage(1)
    expect(el.style.display).toBe('block')
    expect(el.textContent).toMatch(/Step 2\/3/)
    p.done('Ready — RTX 2080')
    expect(el.textContent).toMatch(/Ready — RTX 2080/)
    p.hide()
    expect(el.style.display).toBe('none')
    expect(el.innerHTML).toBe('')
  })

  it('createOptimizeProgress tolerates a missing element', () => {
    const p = createOptimizeProgress(null)
    expect(() => { p.stage(0); p.done(); p.fail('x'); p.hide() }).not.toThrow()
  })
})

describe('buildPreflight — must not overclaim what Optimize does', () => {
  it('lists the real stages', () => {
    const pf = buildPreflight()
    expect(pf.steps).toEqual(OPTIMIZE_STAGES.map(s => s.label))
  })

  it('warns that it takes time and names the slow step', () => {
    const notes = buildPreflight().notes.join(' ')
    expect(notes).toMatch(/30 seconds|minutes/)
    expect(notes).toMatch(/heavy-atom model/)
  })

  it('explicitly says it does NOT run a simulation or benchmark', () => {
    // It doesn't — it reads hardware and measures the design.  Claiming otherwise
    // would be a lie the user could reasonably act on.
    const notes = buildPreflight().notes.join(' ')
    expect(notes).toMatch(/does NOT run a simulation|not.*benchmark/i)
    expect(notes).toMatch(/no job is created|Nothing is submitted/i)
  })

  it('promises nothing changes without approval', () => {
    expect(buildPreflight().notes.join(' ')).toMatch(/until you approve/i)
  })

  it('names the design when one is given', () => {
    expect(buildPreflight({ designName: '6hbx100_90deg' }).lead).toMatch(/6hbx100_90deg/)
  })
})

describe('initAdvancedOptimize', () => {
  let button, apply, notify, fetchRecommendation, fetchHardware, preflight

  const RESULT = {
    recommended: { threads: 6, water_shell_a: 12 },
    rationale: ['because'],
    warnings: ['carve disables GPU-resident'],
    facts: { est_ns_per_day: 18.8, chosen_atoms: 196606, gpu_resident: false },
  }

  beforeEach(() => {
    button = document.createElement('button')
    button.textContent = '⚡'
    apply = vi.fn()
    notify = vi.fn()
    fetchRecommendation = vi.fn(async () => RESULT)
    fetchHardware = vi.fn(async () => ({ summary: 'RTX 2080 SUPER · 8 GB VRAM · 6 cores' }))
    preflight = vi.fn(async () => true)          // default: user continues
  })

  it('shows the pre-flight BEFORE doing any work, and cancelling costs nothing', async () => {
    const decline = vi.fn(async () => false)
    const modal = vi.fn(async () => true)
    initAdvancedOptimize({
      button, fetchHardware, fetchRecommendation, apply, notify, modal, preflight: decline,
      getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    await vi.waitFor(() => expect(decline).toHaveBeenCalled())
    expect(fetchHardware).not.toHaveBeenCalled()      // no 30 s wait imposed on a user who said no
    expect(fetchRecommendation).not.toHaveBeenCalled()
    expect(modal).not.toHaveBeenCalled()
    expect(apply).not.toHaveBeenCalled()
  })

  it('drives the progress element through the real stages', async () => {
    const progressEl = document.createElement('div')
    initAdvancedOptimize({
      button, progressEl, fetchHardware, fetchRecommendation, apply, notify, preflight,
      modal: vi.fn(async () => true), getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    await vi.waitFor(() => expect(apply).toHaveBeenCalled())
    expect(fetchHardware).toHaveBeenCalled()
    expect(progressEl.style.display).toBe('block')
    expect(progressEl.textContent).toMatch(/Applied/)
  })

  it('still completes when the hardware probe fails (it is only cosmetic)', async () => {
    initAdvancedOptimize({
      button, apply, notify, preflight,
      fetchHardware: vi.fn(async () => { throw new Error('no nvidia-smi') }),
      fetchRecommendation, modal: vi.fn(async () => true),
      getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    await vi.waitFor(() => expect(apply).toHaveBeenCalled())
  })

  it('applies the recommendation only after the user proceeds', async () => {
    const modal = vi.fn(async () => true)
    initAdvancedOptimize({
      button, fetchHardware, fetchRecommendation, apply, notify, modal, preflight,
      getCurrent: () => ({ threads: 16, water_shell_a: 0 }),
    })
    button.click()
    await vi.waitFor(() => expect(apply).toHaveBeenCalled())
    expect(apply).toHaveBeenCalledWith({ threads: 6, water_shell_a: 12 })
  })

  it('changes NOTHING when the user cancels — the whole point of the gate', async () => {
    const modal = vi.fn(async () => false)
    initAdvancedOptimize({
      button, fetchHardware, fetchRecommendation, apply, notify, modal, preflight,
      getCurrent: () => ({ threads: 16, water_shell_a: 0 }),
    })
    button.click()
    await vi.waitFor(() => expect(notify).toHaveBeenCalled())
    expect(apply).not.toHaveBeenCalled()
  })

  it('shows the caveats to the user before they can proceed', async () => {
    const modal = vi.fn(async () => false)
    initAdvancedOptimize({
      button, fetchHardware, fetchRecommendation, apply, notify, modal, preflight,
      getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    await vi.waitFor(() => expect(modal).toHaveBeenCalled())
    const arg = modal.mock.calls[0][0]
    expect(arg.caveats.length).toBeGreaterThan(1)
    expect(arg.caveats[0]).toMatch(/GPU-resident/)
    expect(arg.plan.length).toBeGreaterThan(0)
  })

  it('reports a backend failure instead of applying junk', async () => {
    const modal = vi.fn(async () => true)
    initAdvancedOptimize({
      button, apply, notify, modal, preflight, fetchHardware,
      fetchRecommendation: vi.fn(async () => { throw new Error('boom') }),
      getCurrent: () => ({}),
    })
    button.click()
    await vi.waitFor(() => expect(notify).toHaveBeenCalledWith(
      expect.stringMatching(/Optimize failed: boom/), 'error'))
    expect(apply).not.toHaveBeenCalled()
    expect(modal).not.toHaveBeenCalled()
  })

  it('does not collapse the Advanced drawer it lives in (stops propagation)', async () => {
    const header = document.createElement('div')
    const onHeaderClick = vi.fn()
    header.addEventListener('click', onHeaderClick)
    header.appendChild(button)
    initAdvancedOptimize({
      button, fetchHardware, fetchRecommendation, apply, notify, preflight,
      modal: vi.fn(async () => false), getCurrent: () => ({}),
    })
    button.click()
    expect(onHeaderClick).not.toHaveBeenCalled()
  })

  it('ignores re-clicks while a request is in flight', async () => {
    let resolve
    const modal = vi.fn(async () => true)
    const slowFetch = vi.fn(() => new Promise(r => { resolve = r }))
    initAdvancedOptimize({
      button, apply, notify, modal, preflight, fetchHardware,
      fetchRecommendation: slowFetch,
      getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    await vi.waitFor(() => expect(slowFetch).toHaveBeenCalled())   // in flight now
    button.click()
    button.click()
    resolve(RESULT)
    await vi.waitFor(() => expect(apply).toHaveBeenCalled())
    expect(slowFetch).toHaveBeenCalledTimes(1)
    expect(apply).toHaveBeenCalledTimes(1)
  })

  it('rapid clicks cannot stack up multiple pre-flight popups', async () => {
    // The busy latch must be set BEFORE the first await, or every click during the
    // (async) pre-flight opens another one.
    let release
    const slowPreflight = vi.fn(() => new Promise(r => { release = r }))
    initAdvancedOptimize({
      button, apply, notify, fetchHardware, fetchRecommendation,
      modal: vi.fn(async () => false), preflight: slowPreflight,
      getCurrent: () => ({ threads: 16 }),
    })
    button.click()
    button.click()
    button.click()
    await vi.waitFor(() => expect(slowPreflight).toHaveBeenCalled())
    expect(slowPreflight).toHaveBeenCalledTimes(1)
    release(false)
  })

  it('re-arms after a cancelled pre-flight (the latch is released)', async () => {
    const pf = vi.fn(async () => false)
    initAdvancedOptimize({
      button, apply, notify, fetchHardware, fetchRecommendation,
      modal: vi.fn(async () => false), preflight: pf, getCurrent: () => ({}),
    })
    button.click()
    await vi.waitFor(() => expect(pf).toHaveBeenCalledTimes(1))
    button.click()
    await vi.waitFor(() => expect(pf).toHaveBeenCalledTimes(2))   // clickable again
  })

  it('tolerates a missing button', () => {
    expect(() => initAdvancedOptimize({ button: null })).not.toThrow()
  })
})
