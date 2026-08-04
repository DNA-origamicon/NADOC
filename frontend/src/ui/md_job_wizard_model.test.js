import { describe, expect, it, vi } from 'vitest'

import {
  blockingConditions,
  clearStageOverrides,
  normaliseOverrideInput,
  overrideSummary,
  setStageOverride,
  conditionBadges,
  conditionsByStage,
  deferredNotes,
  formatCreatedAt,
  formatValue,
  makeDebounce,
  paramLabel,
  paramRows,
  partNameFor,
  planPayload,
  presetSummary,
  productionComparison,
  productionPayload,
  relaxRunLabel,
  relaxationChoices,
  stageColumns,
  stageDiff,
  wizardPayload,
} from './md_job_wizard_model.js'

/** A miniature plan in the exact shape POST /md/protocol-plan returns. */
function plan(overrides = {}) {
  return {
    param_groups: ['Integrator', 'Thermostat & barostat', 'Restraints & fixed atoms'],
    stages: [
      {
        index: 0, name: 'demo_00_min', stage: 'Energy minimisation', role: 'minimization',
        steps: 4800, timestep_fs: 0, ns: 0,
        params: { minimize: '4800', rigidbonds: 'none', langevinpiston: 'off',
                  outputname: 'output/demo_00_min' },
        diff_vs_previous: {}, conditional_params: {},
      },
      {
        index: 1, name: 'demo_0S_settle', stage: '300K NPT settle (DNA fixed)', role: 'settle',
        steps: 125000, timestep_fs: 4, ns: 0.5,
        params: { timestep: '4', rigidbonds: 'all', langevinpiston: 'on',
                  fixedatoms: 'on', gpuresident: 'on', outputname: 'output/demo_0S_settle' },
        diff_vs_previous: { timestep: ['(absent)', '4'], rigidbonds: ['none', 'all'],
                            langevinpiston: ['off', 'on'], fixedatoms: ['(absent)', 'on'] },
        conditional_params: { gpuresident: 'depends on the solvated atom count' },
      },
      {
        index: 2, name: 'demo_01_k0p5', stage: '300K NPT ENM k=0.5', role: 'ladder',
        steps: 120000, timestep_fs: 2, ns: 0.24,
        params: { timestep: '2', rigidbonds: 'all', langevinpiston: 'on',
                  extrabondsfile: ['mgh_extrabonds.txt', 'demo_k0.5.enm.extra'],
                  outputname: 'output/demo_01_k0p5' },
        diff_vs_previous: { timestep: ['4', '2'], fixedatoms: ['on', '(absent)'],
                            extrabondsfile: ['(absent)', 'mgh_extrabonds.txt,demo_k0.5.enm.extra'] },
        conditional_params: {},
      },
    ],
    request: {
      padding_nm: { value: 2.0, provenance: 'preset', reason: 'set by the X preset' },
      fast: { value: false, provenance: 'preset', reason: 'set by the X preset' },
      minimize_steps: { value: 9000, provenance: 'user', reason: '' },
      threads: { value: 16, provenance: 'default', reason: '' },
    },
    conditions: [
      { id: 'settle_stage', kind: 'stage', title: 'Settle stage', detail: '…',
        applies_to: ['demo_0S_settle'], source: 'x' },
      { id: 'carve_refused', kind: 'blocking', title: 'No carve allowed', detail: '…',
        applies_to: 'all', source: 'y' },
      { id: 'gpu', kind: 'conditional', title: 'GPU-resident', detail: '…',
        applies_to: 'all', source: 'z' },
    ],
    deferred: [{ key: 'minimize', title: 'At least 9,000', detail: 'scales with atoms' }],
    ...overrides,
  }
}

describe('paramRows', () => {
  it('unions every stage, so a directive only one stage carries still gets a row', () => {
    // fixedatoms exists ONLY on the settle stage and extrabondsfile only on the ladder —
    // those are precisely the rows a reader is hunting for.
    const keys = paramRows(plan()).map(r => r.key)
    expect(keys).toContain('fixedatoms')
    expect(keys).toContain('extrabondsfile')
    expect(keys).toContain('minimize')
  })

  it('drops per-stage output bookkeeping', () => {
    expect(paramRows(plan()).map(r => r.key)).not.toContain('outputname')
  })

  it('orders rows by the group order the backend declares', () => {
    const groups = paramRows(plan()).map(r => r.group)
    const firstBarostat = groups.indexOf('Thermostat & barostat')
    const lastIntegrator = groups.lastIndexOf('Integrator')
    expect(lastIntegrator).toBeLessThan(firstBarostat)
  })

  it('is empty for an absent plan rather than throwing', () => {
    expect(paramRows(null)).toEqual([])
  })
})

describe('paramLabel', () => {
  it('names the directives a user is likely looking for', () => {
    expect(paramLabel('langevinpistonperiod')).toBe('Piston period (fs)')
  })

  it('falls back to the raw NAMD directive, which is the honest default', () => {
    expect(paramLabel('someNewKnob')).toBe('someNewKnob')
  })
})

describe('formatValue', () => {
  it('joins a repeated directive so both restraint files show', () => {
    expect(formatValue(['mgh_extrabonds.txt', 'demo_k0.5.enm.extra']))
      .toBe('mgh_extrabonds.txt\ndemo_k0.5.enm.extra')
  })

  it('renders a missing directive as an em dash, not as "undefined"', () => {
    expect(formatValue(undefined)).toBe('—')
  })
})

describe('stageColumns', () => {
  it('builds one column per stage with a cell for every row', () => {
    const cols = stageColumns(plan())
    const rows = paramRows(plan())
    expect(cols).toHaveLength(3)
    for (const col of cols) expect(Object.keys(col.cells).sort()).toEqual(rows.map(r => r.key).sort())
  })

  it('marks a cell changed and remembers what it changed FROM', () => {
    const settle = stageColumns(plan())[1]
    expect(settle.cells.rigidbonds).toMatchObject({ value: 'all', changed: true, was: 'none' })
    expect(settle.cells.langevinpiston).toMatchObject({ value: 'on', changed: true, was: 'off' })
  })

  it('marks a cell conditional and carries the reason', () => {
    const settle = stageColumns(plan())[1]
    expect(settle.cells.gpuresident.conditional).toBe(true)
    expect(settle.cells.gpuresident.reason).toMatch(/atom count/)
  })

  it('flags a directive that is absent from this stage', () => {
    const ladder = stageColumns(plan())[2]
    expect(ladder.cells.fixedatoms).toMatchObject({ present: false, value: '—' })
  })

  it('does not count output bookkeeping toward the changed-cell badge', () => {
    const noisy = plan()
    noisy.stages[1].diff_vs_previous.outputname = ['a', 'b']
    const before = stageColumns(plan())[1].changedCount
    expect(stageColumns(noisy)[1].changedCount).toBe(before)
  })

  it('carries the simulated time each stage really runs', () => {
    expect(stageColumns(plan()).map(c => c.ns)).toEqual([0, 0.5, 0.24])
  })
})

describe('stageDiff', () => {
  it('is empty for the first column — there is nothing to differ from', () => {
    expect(stageDiff(null, { timestep: '4' })).toEqual({})
  })

  it('reports a directive appearing and a directive disappearing', () => {
    // The most important kind of difference: the barostat block vanishing, or the
    // elastic network appearing. Dropping these would be the worst possible omission.
    expect(stageDiff({ margin: '3' }, { timestep: '4' }))
      .toEqual({ margin: ['3', '(absent)'], timestep: ['(absent)', '4'] })
  })

  it('ignores output bookkeeping', () => {
    expect(stageDiff({ outputname: 'a', timestep: '2' }, { outputname: 'b', timestep: '2' }))
      .toEqual({})
  })

  it('compares a repeated directive by its rendered value', () => {
    expect(stageDiff({ extrabondsfile: ['a', 'b'] }, { extrabondsfile: ['a', 'c'] }))
      .toEqual({ extrabondsfile: ['a\nb', 'a\nc'] })
  })
})

describe('productionComparison', () => {
  const last = { timestep: '2', stepspercycle: '20', langevinpistonperiod: '1000.0', cutoff: '10.0' }
  const prod = { timestep: '4', stepspercycle: '10', langevinpistonperiod: '200.0', cutoff: '10.0' }
  const asym = [{ key: 'stepspercycle', relaxation: '20', production: '10', note: 'why it differs' }]

  it('puts the differences first, so the reader sees them without scrolling', () => {
    const { rows } = productionComparison(last, prod, asym)
    expect(rows.filter(r => r.changed).map(r => r.key))
      .toEqual(['langevinpistonperiod', 'stepspercycle', 'timestep'])
    expect(rows[rows.length - 1].key).toBe('cutoff')
  })

  it('attaches the backend note to the annotated asymmetry', () => {
    const { rows } = productionComparison(last, prod, asym)
    expect(rows.find(r => r.key === 'stepspercycle').note).toBe('why it differs')
  })

  it('still lists directives that agree, so the reader can confirm nothing else moved', () => {
    const { rows } = productionComparison(last, prod, asym)
    const same = rows.find(r => r.key === 'cutoff')
    expect(same).toMatchObject({ changed: false, relaxation: '10.0', production: '10.0' })
  })

  it('counts the differences', () => {
    expect(productionComparison(last, prod, asym).changedCount).toBe(3)
  })

  it('shows the restraint row, which is where an elastic network appears', () => {
    // The single most consequential row in this table: the published productions keep a
    // network and NADOC's did not, so it has to be visible and marked changed.
    const { rows } = productionComparison(
      { extrabondsfile: 'mgh_extrabonds.txt' },
      { extrabondsfile: ['mgh_extrabonds.txt', 'd_prod_k0.1.enm.extra'] }, [])
    const row = rows.find(r => r.key === 'extrabondsfile')
    expect(row).toMatchObject({ changed: true, label: 'Extra bonds (restraints)' })
    expect(row.production).toContain('d_prod_k0.1.enm.extra')
  })
})

describe('presetSummary', () => {
  it('counts what the preset is actually still supplying, not what it declares', () => {
    const s = presetSummary({ id: 'literature', label: 'Lit', summary: 's', reference: 'r' }, plan())
    expect(s.fromPreset.sort()).toEqual(['fast', 'padding_nm'])
    expect(s.overridden).toEqual(['minimize_steps'])
    expect(s.note).toBe('2 settings come from this protocol')
  })

  it('says so when the user has overridden everything', () => {
    const p = plan({ request: { padding_nm: { value: 1, provenance: 'user' } } })
    expect(presetSummary({ id: 'x' }, p).note).toBe('every setting has been overridden')
  })

  it('carries the unavailable reason rather than hiding the option', () => {
    const s = presetSummary({ id: 'gbis', available: false, unavailable_reason: 'needs a CPU build' }, plan())
    expect(s).toMatchObject({ available: false, unavailableReason: 'needs a CPU build' })
  })
})

describe('wizardPayload', () => {
  it('sends only the fields the user touched, plus the preset', () => {
    // A field sent unconditionally marks itself explicit on the server and DEFEATS the
    // preset it was meant to follow — which is exactly what the old panel did.
    expect(wizardPayload({ presetId: 'literature', touched: { padding_nm: 3 } }))
      .toEqual({ relax_preset: 'literature', autostart: false, padding_nm: 3 })
  })

  it('never sends protocol, which the preset derives', () => {
    const body = wizardPayload({ presetId: 'literature', touched: { protocol: 'whatever' } })
    expect(body).not.toHaveProperty('protocol')
  })

  it('passes a falsy touched value through rather than dropping it', () => {
    const body = wizardPayload({ presetId: 'x', touched: { fast: false, water_shell_nm: 0 } })
    expect(body).toMatchObject({ fast: false, water_shell_nm: 0 })
  })

  it('carries autostart so Create and Create-and-run are one code path', () => {
    expect(wizardPayload({ presetId: 'x', autostart: true }).autostart).toBe(true)
  })
})

describe('planPayload', () => {
  it('drops autostart — a preview starts nothing', () => {
    expect(planPayload({ presetId: 'x', autostart: true })).not.toHaveProperty('autostart')
  })

  it('defaults to a relaxation plan', () => {
    expect(planPayload({ presetId: 'x' }).kind).toBe('relaxation')
  })

  it('carries the parent and length for a production plan', () => {
    expect(planPayload({ presetId: 'x', mode: 'production', parentJobId: 'abc', lengthNs: 100 }))
      .toMatchObject({ kind: 'production', parent_job_id: 'abc', length_ns: 100,
                       allow_undersized_cell: false })
  })

  it('carries the production restraint and damping choices into the preview', () => {
    expect(planPayload({ presetId: 'x', mode: 'production', parentJobId: 'a',
                         enmRestraints: 'off', langevinDamping: 5 }))
      .toMatchObject({ enm_restraints: 'off', langevin_damping: 5 })
  })

  it('passes an atom-count hint so deferred values resolve exactly', () => {
    expect(planPayload({ presetId: 'x', nAtomsHint: 224000 }).n_atoms_hint).toBe(224000)
  })
})

describe('productionPayload', () => {
  it('builds the spawn body', () => {
    expect(productionPayload({ lengthNs: 100, dcdFreq: 5000, autostart: true }))
      .toEqual({ length_ns: 100, autostart: true, allow_undersized_cell: false,
                 execution_target: 'local', dcd_freq: 5000 })
  })

  it('omits optional fields it was not given', () => {
    const body = productionPayload({ lengthNs: 10 })
    expect(body).not.toHaveProperty('dcd_freq')
    expect(body).not.toHaveProperty('cluster_name')
  })

  it('carries the restraint choice and the thermostat coupling', () => {
    // Both differ from the ladder, and both change what the trajectory can be compared
    // with: the published "unrestrained" productions keep a network, and their thermostat
    // couples an order of magnitude more weakly than an equilibration run.
    const body = productionPayload({ lengthNs: 10, enmRestraints: 'on', langevinDamping: 1 })
    expect(body).toMatchObject({ enm_restraints: 'on', langevin_damping: 1 })
  })

  it('leaves the restraint choice to the server when not set', () => {
    // Absent means "follow the parent protocol" — the backend's 'auto'.
    expect(productionPayload({ lengthNs: 10 })).not.toHaveProperty('enm_restraints')
  })
})

describe('partNameFor', () => {
  it('is the file stem of the design path', () => {
    expect(partNameFor({ design_source_path: 'workspace/parts/26hb_platform_v3.nadoc' }))
      .toBe('26hb_platform_v3')
  })

  it('handles windows separators and a missing path', () => {
    expect(partNameFor({ design_source_path: 'C:\\work\\belt.nadoc' })).toBe('belt')
    expect(partNameFor({})).toBe('design')
  })
})

describe('relaxRunLabel', () => {
  const at = (y, mo, d, h, mi, s = 0) => new Date(y, mo - 1, d, h, mi, s).getTime() / 1000

  it('names a run by its part and creation time, never by a job id', () => {
    const job = { job_id: 'deadbeef', design_source_path: 'w/belt.nadoc',
                  created_at: at(2026, 8, 3, 14, 22) }
    expect(relaxRunLabel(job)).toBe('belt run created 2026-08-03 14:22')
  })

  it('adds seconds when a sibling shares the part and the minute', () => {
    // Part-and-minute is not always unique, and two identical choices is worse than
    // no label at all.
    const a = { job_id: 'a', design_source_path: 'w/belt.nadoc', created_at: at(2026, 8, 3, 14, 22, 5) }
    const b = { job_id: 'b', design_source_path: 'w/belt.nadoc', created_at: at(2026, 8, 3, 14, 22, 41) }
    expect(relaxRunLabel(a, [a, b])).toBe('belt run created 2026-08-03 14:22:05')
    expect(relaxRunLabel(b, [a, b])).toBe('belt run created 2026-08-03 14:22:41')
  })

  it('does not add seconds when the sibling is a different part', () => {
    const a = { job_id: 'a', design_source_path: 'w/belt.nadoc', created_at: at(2026, 8, 3, 14, 22) }
    const b = { job_id: 'b', design_source_path: 'w/gear.nadoc', created_at: at(2026, 8, 3, 14, 22) }
    expect(relaxRunLabel(a, [a, b])).toBe('belt run created 2026-08-03 14:22')
  })
})

describe('formatCreatedAt', () => {
  it('says so rather than rendering the epoch when the time is missing', () => {
    expect(formatCreatedAt(0)).toBe('unknown time')
    expect(formatCreatedAt(undefined)).toBe('unknown time')
  })
})

describe('relaxationChoices', () => {
  const base = { design_source_path: 'w/belt.nadoc', status: 'completed' }
  const jobs = [
    { ...base, job_id: 'old', created_at: 100 },
    { ...base, job_id: 'new', created_at: 300 },
    { ...base, job_id: 'running', status: 'running', created_at: 400 },
    { ...base, job_id: 'child', run_kind: 'production', created_at: 500 },
    { ...base, job_id: 'other-part', design_source_path: 'w/gear.nadoc', created_at: 600 },
    { ...base, job_id: 'archived', archived: true, created_at: 700 },
  ]

  it('offers only completed relaxations for this part, newest first', () => {
    expect(relaxationChoices(jobs, 'w/belt.nadoc').map(c => c.job.job_id))
      .toEqual(['new', 'old'])
  })

  it('tolerates a trailing slash and backslashes in the part path', () => {
    expect(relaxationChoices(jobs, 'w\\belt.nadoc/').map(c => c.job.job_id))
      .toEqual(['new', 'old'])
  })

  it('is empty when nothing qualifies — the "run a relaxation first" signal', () => {
    expect(relaxationChoices(jobs, 'w/never-run.nadoc')).toEqual([])
    expect(relaxationChoices([], 'w/belt.nadoc')).toEqual([])
  })

  it('flags a stale relaxation rather than hiding it', () => {
    const stale = [{ ...base, job_id: 's', created_at: 1, out_of_date: true }]
    expect(relaxationChoices(stale, 'w/belt.nadoc')[0].stale).toBe(true)
  })

  it('labels each choice by part and time', () => {
    expect(relaxationChoices(jobs, 'w/belt.nadoc')[0].label).toMatch(/^belt run created /)
  })
})

describe('conditionBadges', () => {
  it('puts blocking conditions first', () => {
    expect(conditionBadges(plan()).map(c => c.kind))
      .toEqual(['blocking', 'conditional', 'stage'])
  })

  it('distinguishes an all-stages condition from a per-stage one', () => {
    const byId = Object.fromEntries(conditionBadges(plan()).map(c => [c.id, c]))
    expect(byId.carve_refused.allStages).toBe(true)
    expect(byId.settle_stage.stages).toEqual(['demo_0S_settle'])
  })

  it('is empty for a plan with no conditions', () => {
    expect(conditionBadges({ conditions: [] })).toEqual([])
  })
})

describe('blockingConditions', () => {
  it('finds the hard stops', () => {
    expect(blockingConditions(plan()).map(c => c.id)).toEqual(['carve_refused'])
  })

  it('does not treat a satisfied check as a stop', () => {
    // The production box-fit check reports itself blocking-shaped with ok:true when the
    // cell is fine; treating that as a stop would refuse every healthy production run.
    const p = { conditions: [{ id: 'box_fit', kind: 'blocking', ok: true }] }
    expect(blockingConditions(p)).toEqual([])
  })
})

describe('conditionsByStage', () => {
  it('maps a per-stage condition onto its column', () => {
    const map = conditionsByStage(plan())
    expect(map.get('demo_0S_settle').map(c => c.id)).toEqual(['settle_stage'])
    expect(map.has('demo_01_k0p5')).toBe(false)
  })
})

describe('deferredNotes', () => {
  it('passes through the "resolves after solvation" notes', () => {
    expect(deferredNotes(plan())).toEqual([
      { key: 'minimize', title: 'At least 9,000', detail: 'scales with atoms' },
    ])
  })

  it('is empty when nothing is deferred', () => {
    expect(deferredNotes({})).toEqual([])
  })
})

describe('makeDebounce', () => {
  it('fires once, after the delay, with the last arguments', () => {
    vi.useFakeTimers()
    const spy = vi.fn()
    const d = makeDebounce(spy, 250)
    d(1); d(2); d(3)
    expect(spy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(250)
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith(3)
    vi.useRealTimers()
  })

  it('can be cancelled, so a closing wizard fires nothing into a torn-down view', () => {
    vi.useFakeTimers()
    const spy = vi.fn()
    const d = makeDebounce(spy, 250)
    d('x')
    d.cancel()
    vi.advanceTimersByTime(1000)
    expect(spy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})

describe('setStageOverride', () => {
  it('records an edit on one stage without touching the others', () => {
    const o = setStageOverride({ 5: { run: '9' } }, 3, 'timestep', '2')
    expect(o).toEqual({ 3: { timestep: '2' }, 5: { run: '9' } })
  })

  it('accepts the wildcard for every stage at once', () => {
    // Editing one directive across 22 columns cell-by-cell is not a usable feature.
    expect(setStageOverride({}, '*', 'langevinDamping', '1'))
      .toEqual({ '*': { langevinDamping: '1' } })
  })

  it('distinguishes CLEARING an override from DELETING a directive', () => {
    // "stop overriding the barostat" and "run this stage with no barostat" are different
    // instructions and must not collapse into one.
    const set = setStageOverride({}, 2, 'langevinPiston', null)
    expect(set).toEqual({ 2: { langevinPiston: null } })       // delete the directive
    expect(setStageOverride(set, 2, 'langevinPiston', undefined)).toEqual({})  // clear
  })

  it('drops the stage entry when its last override is cleared', () => {
    expect(setStageOverride({ 3: { timestep: '2' } }, 3, 'timestep', undefined)).toEqual({})
  })

  it('never mutates its input', () => {
    const before = { 3: { timestep: '2' } }
    setStageOverride(before, 3, 'run', '5')
    expect(before).toEqual({ 3: { timestep: '2' } })
  })
})

describe('clearStageOverrides', () => {
  it('clears one stage, or everything', () => {
    const o = { 3: { a: '1' }, 4: { b: '2' } }
    expect(clearStageOverrides(o, 3)).toEqual({ 4: { b: '2' } })
    expect(clearStageOverrides(o)).toEqual({})
  })
})

describe('overrideSummary', () => {
  it('counts distinct directives and stages', () => {
    expect(overrideSummary({ 3: { a: '1', b: '2' }, 4: { a: '9' } }))
      .toMatchObject({ stages: 2, directives: 2, appliesToAll: false })
  })

  it('says "every stage" for a wildcard rather than counting it as one', () => {
    const s = overrideSummary({ '*': { a: '1' } })
    expect(s.appliesToAll).toBe(true)
    expect(s.text).toContain('every stage')
  })

  it('is empty when nothing is edited, so the warning stays hidden', () => {
    expect(overrideSummary({}).text).toBe('')
    expect(overrideSummary({ 3: {} }).directives).toBe(0)
  })
})

describe('normaliseOverrideInput', () => {
  it('blank clears the override, restoring the protocol', () => {
    expect(normaliseOverrideInput('   ')).toBeUndefined()
  })

  it('"(none)" deletes the directive', () => {
    expect(normaliseOverrideInput('(none)')).toBeNull()
    expect(normaliseOverrideInput('(NONE)')).toBeNull()
  })

  it('trims an ordinary value', () => {
    expect(normaliseOverrideInput('  4 ')).toBe('4')
  })
})

describe('stageColumns — the override highlight', () => {
  function edited() {
    const p = plan()
    p.stages[2].overridden = { timestep: ['4', '2'] }
    return p
  }

  it('marks an edited cell and keeps the protocol value for the tooltip', () => {
    // A SECOND, independent highlight from `changed`: that one is "differs from the stage
    // before", this one is "differs from the protocol you picked".
    const cell = stageColumns(edited())[2].cells.timestep
    expect(cell).toMatchObject({ overridden: true, protocolValue: '4', value: '2' })
  })

  it('leaves unedited cells alone', () => {
    expect(stageColumns(plan())[2].cells.timestep.overridden).toBe(false)
    expect(stageColumns(plan())[2].cells.timestep.protocolValue).toBeNull()
  })

  it('marks plumbing directives read-only so the edit cannot fail on submit', () => {
    const p = plan()
    p.stages[0].params.structure = 'demo.psf'
    const cells = stageColumns(p)[0].cells
    expect(cells.structure).toBeUndefined()      // filtered as noise from the table
    expect(stageColumns(plan())[0].cells.timestep.editable).toBe(true)
  })
})

describe('payloads carry the stage edits', () => {
  it('wizardPayload sends them, and omits the key when there are none', () => {
    expect(wizardPayload({ presetId: 'x', stageOverrides: { 3: { run: '9' } } }))
      .toMatchObject({ stage_overrides: { 3: { run: '9' } } })
    expect(wizardPayload({ presetId: 'x', stageOverrides: {} }))
      .not.toHaveProperty('stage_overrides')
  })

  it('planPayload sends them too — the preview must show the run as edited', () => {
    expect(planPayload({ presetId: 'x', stageOverrides: { '*': { run: '9' } } }))
      .toMatchObject({ stage_overrides: { '*': { run: '9' } } })
  })

  it('productionPayload sends them', () => {
    expect(productionPayload({ lengthNs: 1, stageOverrides: { 1: { run: '9' } } }))
      .toMatchObject({ stage_overrides: { 1: { run: '9' } } })
  })
})
