import { describe, expect, it, vi } from 'vitest'

import {
  allStageConditions,
  applySnapshot,
  blockingConditions,
  clearStageOverrides,
  normaliseOverrideInput,
  overrideSummary,
  setStageOverride,
  conditionBadges,
  conditionsByField,
  conditionsByStage,
  conditionTooltip,
  deferredNotes,
  fieldAlert,
  fieldScope,
  formatCreatedAt,
  formatValue,
  inheritedRows,
  isProductionParent,
  jobSettingsState,
  productionSteps,
  makeDebounce,
  paramLabel,
  paramRows,
  partNameFor,
  planPayload,
  presetSummary,
  productionColumns,
  productionComparison,
  productionField,
  productionPayload,
  pushUndo,
  relaxRunLabel,
  productionParents,
  snapshotState,
  stageColumns,
  stageDiff,
  wizardPayload,
  WIZARD_FIELDS,
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
        index: 1, name: 'demo_0S_settle', stage: '300K NPT settle (DNA restrained)', role: 'settle',
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
    // An explicitly requested restrained run must be visibly different from the normal
    // unrestrained production default.
    const { rows } = productionComparison(
      { extrabondsfile: 'mgh_extrabonds.txt' },
      { extrabondsfile: ['mgh_extrabonds.txt', 'd_prod_k0.1.enm.extra'] }, [])
    const row = rows.find(r => r.key === 'extrabondsfile')
    expect(row).toMatchObject({ changed: true, label: 'Extra bonds (restraints)' })
    expect(row.production).toContain('d_prod_k0.1.enm.extra')
  })
})

/** A miniature PRODUCTION plan, in the shape `_production_plan` returns: the relaxation
 *  stage being continued, then the two confs the replica package really contains. */
function prodPlan(overrides = {}) {
  return {
    kind: 'production',
    param_groups: ['Integrator', 'Thermostat & barostat', 'Restraints & fixed atoms'],
    source_stage: {
      kind: 'relaxation',
      name: 'demo_04_k0', stage: '300K NPT MgHH only',
      params: { timestep: '2', rigidbonds: 'all', langevindamping: '5',
                extrabondsfile: 'mgh_extrabonds.txt', stepspercycle: '20',
                fixedatoms: 'on', outputname: 'output/demo_04_k0' },
    },
    stages: [
      {
        index: 0, name: 'demo_00_reseed', stage: 'Velocity reseed', role: 'reseed',
        steps: 0, timestep_fs: 4, ns: 0, accepts_overrides: false,
        params: { timestep: '2', reinitvels: '300', langevindamping: '5',
                  outputname: 'output/demo_00_reseed' },
        diff_vs_previous: {}, conditional_params: {}, overridden: {},
      },
      {
        index: 1, name: 'demo_01_production_100ns_k0', stage: '100 ns production replica',
        role: 'production', steps: 25000000, timestep_fs: 4, ns: 100,
        accepts_overrides: true,
        params: { timestep: '4', rigidbonds: 'all', langevindamping: '1',
                  extrabondsfile: 'mgh_extrabonds.txt', stepspercycle: '10',
                  parameters: 'forcefield/par_all36_na.prm',
                  outputname: 'output/demo_01_production_100ns_k0' },
        diff_vs_previous: {}, conditional_params: {}, overridden: {},
      },
    ],
    asymmetries: [{ key: 'stepspercycle', relaxation: '20', production: '10',
                    note: 'why it differs' }],
    inherited: {
      seed_stage: '300K NPT MgHH only', seed_checkpoint: 'demo_04_k0',
      relax_preset: 'literature', n_atoms: 224000, box_ang: [180.5, 190.25, 210.0],
      padding_nm: 2.0, carved: false, mg_conc_mM: 12.5, ion_conc_mM: 0,
      ladder_timestep_fs: 2.0, anchors: false, field: null,
    },
    production_request: {
      length_ns: { value: 100, provenance: 'default', reason: 'the wizard default' },
      production_timestep_fs: { value: 4, provenance: 'inherited', reason: 'from prep' },
    },
    request: { production_timestep_fs: { value: 2, provenance: 'preset', reason: '' },
               padding_nm: { value: 2, provenance: 'preset', reason: '' } },
    ...overrides,
  }
}

describe('productionColumns', () => {
  it('leads with the relaxation stage the run continues from, read-only', () => {
    const { columns } = productionColumns(prodPlan())
    expect(columns.map(c => c.name)).toEqual(
      ['demo_04_k0', 'demo_00_reseed', 'demo_01_production_100ns_k0'])
    expect(columns[0].reference).toBe(true)
    expect(Object.values(columns[0].cells).every(c => !c.editable)).toBe(true)
  })

  it('highlights against the RELAXATION column, not against the previous stage', () => {
    // The question this table answers is "what is different about production". The
    // zero-step reseed bridge sitting in between is not what anyone is comparing to.
    const prod = productionColumns(prodPlan()).columns[2]
    expect(prod.cells.timestep).toMatchObject({ changed: true, was: '2' })
    expect(prod.cells.langevindamping).toMatchObject({ changed: true, was: '5' })
    expect(prod.cells.extrabondsfile.changed).toBe(false)
  })

  it('shows a directive that exists ONLY on the relaxation side', () => {
    // The ladder's fixed atoms disappear in production. Building the row list from the
    // plan's `stages` alone dropped exactly the rows worth looking at.
    const { rows, columns } = productionColumns(prodPlan())
    expect(rows.map(r => r.key)).toContain('fixedatoms')
    expect(columns[2].cells.fixedatoms).toMatchObject({ present: false, changed: true })
  })

  it('locks the reseed bridge — the runner writes it without an overrides pass', () => {
    const reseed = productionColumns(prodPlan()).columns[1]
    expect(reseed.acceptsOverrides).toBe(false)
    expect(reseed.cells.timestep.editable).toBe(false)
  })

  it('leaves the production stage editable, except the directives that name its files', () => {
    const prod = productionColumns(prodPlan()).columns[2]
    expect(prod.cells.timestep.editable).toBe(true)
    // Protected: rewriting it detaches the stage from its package rather than changing
    // what it simulates, so the cell is rendered read-only instead of failing at submit.
    expect(prod.cells.parameters.editable).toBe(false)
    // A NOISE key gets no row at all — 22 per-stage output paths would bury the physics.
    expect(prod.cells.outputname).toBeUndefined()
  })

  it('is empty when there is no relaxation to compare against', () => {
    expect(productionColumns({ stages: [] })).toEqual({ rows: [], columns: [] })
  })

  it('carries a hand edit through as its own highlight', () => {
    const p = prodPlan()
    p.stages[1].overridden = { langevindamping: ['1', '2'] }
    const cell = productionColumns(p).columns[2].cells.langevindamping
    expect(cell).toMatchObject({ overridden: true, protocolValue: '1' })
  })
})

/** The same plan for a CHAINED run: the parent is a production, so the reference column
 *  is a production stage and the reseed carries velocities instead of redrawing them. */
function chainPlan(overrides = {}) {
  const p = prodPlan()
  p.continuation = true
  p.source_stage = {
    kind: 'production', name: 'demo_01_production_200ns_k0',
    stage: '200 ns production replica',
    params: { timestep: '4', rigidbonds: 'all', langevindamping: '1',
              extrabondsfile: 'mgh_extrabonds.txt', stepspercycle: '10',
              run: '50000000', outputname: 'output/demo_01_production_200ns_k0' },
  }
  p.stages[0].stage = 'Velocity continuation'
  p.stages[0].params = { timestep: '2', binvelocities: 'equilibrated.vel',
                         langevindamping: '1', outputname: 'output/demo_00_reseed' }
  p.asymmetries = []
  p.inherited = { ...p.inherited, continuation: true, chain_position: 3,
                  parent_length_ns: 200.0, seed_stage: '200 ns production replica' }
  return { ...p, ...overrides }
}

describe('productionColumns — chaining off a finished production', () => {
  it('names the reference column by what it IS, not "Relaxation"', () => {
    const ref = productionColumns(chainPlan()).columns[0]
    expect(ref).toMatchObject({ reference: true, sourceKind: 'production',
                                role: 'production' })
    expect(ref.name).toBe('demo_01_production_200ns_k0')
  })

  it('still diffs the new run against the run it continues', () => {
    // Both columns are productions now, so the ladder-vs-production asymmetries are gone
    // and what is left is the real change: the run length.
    const prod = productionColumns(chainPlan()).columns[2]
    expect(prod.cells.run).toMatchObject({ changed: true, was: '50000000' })
    expect(prod.cells.langevindamping.changed).toBe(false)
    expect(prod.cells.stepspercycle.changed).toBe(false)
  })

  it('keeps the continuation bridge locked, same as the reseed', () => {
    expect(productionColumns(chainPlan()).columns[1].acceptsOverrides).toBe(false)
  })
})

describe('inheritedRows — chaining', () => {
  it('says where in the chain this run sits and how much is already simulated', () => {
    const rows = Object.fromEntries(inheritedRows(chainPlan()).map(r => [r.label, r.value]))
    expect(rows['Position in the chain']).toBe('run 3 off this relaxation')
    expect(rows['Already simulated']).toBe('200 ns')
  })

  it('says that VELOCITIES carry over — the thing that makes it not a new sample', () => {
    const row = inheritedRows(chainPlan()).find(r => r.label === 'Continuing from')
    expect(row.note).toMatch(/velocities/i)
    expect(row.value).toBe('200 ns production replica')
  })

  it('does not claim a chain position for a run seeded off a relaxation', () => {
    const labels = inheritedRows(prodPlan()).map(r => r.label)
    expect(labels).not.toContain('Position in the chain')
    expect(labels).not.toContain('Already simulated')
    expect(inheritedRows(prodPlan()).find(r => r.label === 'Continuing from').note)
      .not.toMatch(/velocities/i)
  })
})

describe('productionField', () => {
  it('prefers the production-resolved value over the create-request merge', () => {
    // The four settings that exist in both resolve differently: the create merge reports
    // the PRESET's value, while a production child inherits what its package recorded.
    expect(productionField(prodPlan(), 'production_timestep_fs'))
      .toMatchObject({ value: 4, provenance: 'inherited' })
  })

  it('falls back to the create request for a field production does not resolve', () => {
    expect(productionField(prodPlan(), 'padding_nm')).toMatchObject({ value: 2 })
  })

  it('is null for a field neither block carries', () => {
    expect(productionField(prodPlan(), 'nonesuch')).toBe(null)
  })
})

describe('inheritedRows', () => {
  it('states what the run takes from the relaxation rather than choosing', () => {
    const labels = inheritedRows(prodPlan()).map(r => r.label)
    expect(labels).toEqual(expect.arrayContaining(
      ['Continuing from', 'Relaxation protocol', 'Solvated atoms', 'Cell',
       'Water padding', 'Magnesium', 'Ladder base timestep']))
  })

  it('formats the cell and the atom count for reading, not for parsing', () => {
    const rows = inheritedRows(prodPlan())
    expect(rows.find(r => r.label === 'Cell').value).toBe('180.5 × 190.25 × 210 Å')
    expect(rows.find(r => r.label === 'Solvated atoms').value).toMatch(/224[,.\s]000/)
  })

  it('omits what the package does not record, rather than showing a blank', () => {
    const labels = inheritedRows(prodPlan()).map(r => r.label)
    expect(labels).not.toContain('Water shell carve')     // not carved
    expect(labels).not.toContain('Anchors')               // none
    expect(labels).not.toContain('Electric field')
  })

  it('is empty for a relaxation plan, which inherits nothing', () => {
    expect(inheritedRows(plan())).toEqual([])
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
    const body = wizardPayload({ presetId: 'x', touched: {
      fast: false, early_stop_relax: false, adaptive_minimization: false,
    } })
    expect(body).toMatchObject({
      fast: false, early_stop_relax: false, adaptive_minimization: false,
    })
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
    expect(planPayload({ presetId: 'x', mode: 'production', parentJobId: 'abc',
                         touched: { length_ns: 100 } }))
      .toMatchObject({ kind: 'production', parent_job_id: 'abc', length_ns: 100,
                       allow_undersized_cell: false })
  })

  it('carries the production restraint and damping choices into the preview', () => {
    expect(planPayload({ presetId: 'x', mode: 'production', parentJobId: 'a',
                         touched: { enm_restraints: 'off', langevin_damping: 5 } }))
      .toMatchObject({ enm_restraints: 'off', langevin_damping: 5 })
  })

  it('omits an untouched production setting, so the package keeps deciding it', () => {
    // The preview has to resolve the same way the run will. A length or a restraint
    // choice sent because the form displayed it would mark itself explicit and beat the
    // prep-time value a production child is supposed to inherit.
    const body = planPayload({ presetId: 'x', mode: 'production', parentJobId: 'a' })
    expect(body).not.toHaveProperty('length_ns')
    expect(body).not.toHaveProperty('enm_restraints')
    expect(body).not.toHaveProperty('langevin_damping')
    expect(body).not.toHaveProperty('seed')
  })

  it('sends the auto restraint choice when explicitly selected', () => {
    expect(planPayload({ presetId: 'x', mode: 'production', parentJobId: 'a',
                         touched: { enm_restraints: 'auto' } }))
      .toMatchObject({ enm_restraints: 'auto' })
  })

  it('passes an atom-count hint so deferred values resolve exactly', () => {
    expect(planPayload({ presetId: 'x', nAtomsHint: 224000 }).n_atoms_hint).toBe(224000)
  })
})

describe('productionPayload', () => {
  it('sends the opt-in overall-orientation restraint and its quaternion strength', () => {
    expect(productionPayload({
      lengthNs: 10,
      touched: { orientation_restraint: true, orientation_force_constant: 750 },
    })).toMatchObject({
      orientation_restraint: true,
      orientation_force_constant: 750,
    })
  })

  it('builds the spawn body', () => {
    expect(productionPayload({ touched: { length_ns: 100, dcd_freq: 5000 }, autostart: true }))
      .toEqual({ length_ns: 100, autostart: true, allow_undersized_cell: false,
                 execution_target: 'local', dcd_freq: 5000 })
  })

  it('omits optional fields it was not given', () => {
    const body = productionPayload({ lengthNs: 10 })
    expect(body).not.toHaveProperty('dcd_freq')
    expect(body).not.toHaveProperty('cluster_name')
  })

  it('always sends a run length, from the plan when the user did not type one', () => {
    // The one production setting with no server-side inheritance: omitted, it would fall
    // to the API's 1 ns default rather than to the 100 ns the form was showing.
    expect(productionPayload({ lengthNs: 100 }).length_ns).toBe(100)
    expect(productionPayload({ touched: { length_ns: 25 }, lengthNs: 100 }).length_ns).toBe(25)
  })

  it('carries the restraint choice and the thermostat coupling', () => {
    // Both differ from the ladder, and both change what the trajectory can be compared
    // with: an enabled network is a deliberately restrained production, and the thermostat
    // coupling also differs from the equilibration run.
    const body = productionPayload({
      touched: { length_ns: 10, enm_restraints: 'on', langevin_damping: 1 } })
    expect(body).toMatchObject({ enm_restraints: 'on', langevin_damping: 1 })
  })

  it('uses the server unrestrained default when not set', () => {
    expect(productionPayload({ lengthNs: 10 })).not.toHaveProperty('enm_restraints')
    expect(productionPayload({ touched: { enm_restraints: 'auto' }, lengthNs: 10 }))
      .toMatchObject({ enm_restraints: 'auto' })
  })

  it('renames the two integrator axes to the spawn request’s own field names', () => {
    // ProductionRunRequest is already about production, so `rigid_bonds` there is what
    // `production_rigid_bonds` is on a create request. Sending the create-request name
    // would be silently dropped by pydantic and the run would use the auto value.
    const body = productionPayload({
      touched: { production_rigid_bonds: 'none', production_hmr: false,
                 production_timestep_fs: 2 }, lengthNs: 10 })
    expect(body).toMatchObject({ rigid_bonds: 'none', hmr: false,
                                 production_timestep_fs: 2 })
    expect(body).not.toHaveProperty('production_rigid_bonds')
  })

  it('sends GPU-resident, the seed and the undersized-cell override', () => {
    const body = productionPayload({
      touched: { gpu_resident: 'off', seed: 4242, allow_undersized_cell: true },
      lengthNs: 10 })
    expect(body).toMatchObject({ gpu_resident: 'off', seed: 4242,
                                 allow_undersized_cell: true })
  })

  it('sends nothing the user did not touch, so the package keeps deciding', () => {
    const body = productionPayload({ lengthNs: 10 })
    for (const key of ['gpu_resident', 'seed', 'rigid_bonds', 'hmr',
                       'production_timestep_fs', 'langevin_damping']) {
      expect(body).not.toHaveProperty(key)
    }
  })
})

describe('isProductionParent', () => {
  const done = { job_id: 'a', status: 'completed', run_kind: null, archived: false }

  it('accepts a completed relaxation — the New-job gesture that means "carry on"', () => {
    expect(isProductionParent(done)).toBe(true)
  })

  it('refuses anything a production run cannot seed from', () => {
    expect(isProductionParent(null)).toBe(false)
    expect(isProductionParent({ ...done, status: 'running' })).toBe(false)
    expect(isProductionParent({ ...done, status: 'stopped' })).toBe(false)
    expect(isProductionParent({ ...done, status: 'failed' })).toBe(false)
  })

  it('accepts a completed PRODUCTION run — that is the chain gesture', () => {
    // The backend has always chained (`_production_seed_checkpoint` branches on
    // `run_kind`, and `build_replica_package` stages the parent's restart set and
    // preserves velocities). Only the UI had no way to ask for it.
    const child = { ...done, job_id: 'child', run_kind: 'production' }
    expect(isProductionParent(child)).toBe(true)
    const choice = productionParents([child], '')[0]
    expect(choice.continuation).toBe(true)
    expect(choice.label).toMatch(/production run created/)
  })

  it('marks a relaxation parent as NOT a continuation — it is an independent sample', () => {
    const choice = productionParents([done], '')[0]
    expect(choice.continuation).toBe(false)
    expect(choice.label).toMatch(/relaxation created/)
  })

  it('accepts an ARCHIVED relaxation — archiving is a disk decision, not a retirement', () => {
    // The job directory moves to the archive drive and `package_dir` follows it, so the
    // package is intact and the spawn route accepts it. Excluding them meant that on a
    // machine where every finished relaxation had been archived to reclaim space,
    // production mode could only ever say "no completed relaxation for this part yet".
    expect(isProductionParent({ ...done, archived: true })).toBe(true)
    const choice = productionParents([{ ...done, archived: true }], '')[0]
    expect(choice.archived).toBe(true)     // called out: the drive has to be mounted
  })

  it('agrees with the wizard’s own picker about what counts as a parent', () => {
    // The two must never disagree: the button would open a mode whose picker then
    // silently swapped in a different run.
    const jobs = [done, { ...done, job_id: 'b', run_kind: 'production' },
                  { ...done, job_id: 'c', status: 'failed' }]
    expect(productionParents(jobs, '').map(c => c.job.job_id))
      .toEqual(jobs.filter(isProductionParent).map(j => j.job_id))
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

describe('productionParents', () => {
  const base = { design_source_path: 'w/belt.nadoc', status: 'completed' }
  const jobs = [
    { ...base, job_id: 'old', created_at: 100 },
    { ...base, job_id: 'new', created_at: 300 },
    { ...base, job_id: 'running', status: 'running', created_at: 400 },
    { ...base, job_id: 'child', run_kind: 'production', created_at: 500 },
    { ...base, job_id: 'other-part', design_source_path: 'w/gear.nadoc', created_at: 600 },
    { ...base, job_id: 'archived', archived: true, created_at: 700 },
  ]

  it('offers every completed run for this part, newest first', () => {
    // 'archived' is in the list on purpose: archiving moves the package to the archive
    // drive to reclaim disk, and every path that reads it follows `archive_path`.
    // 'child' is in it because a completed production is a legal parent — picking it
    // EXTENDS that trajectory instead of sampling a new one.
    expect(productionParents(jobs, 'w/belt.nadoc').map(c => c.job.job_id))
      .toEqual(['archived', 'child', 'new', 'old'])
  })

  it('tolerates a trailing slash and backslashes in the part path', () => {
    expect(productionParents(jobs, 'w\\belt.nadoc/').map(c => c.job.job_id))
      .toEqual(['archived', 'child', 'new', 'old'])
  })

  it('is empty when nothing qualifies — the "run a relaxation first" signal', () => {
    expect(productionParents(jobs, 'w/never-run.nadoc')).toEqual([])
    expect(productionParents([], 'w/belt.nadoc')).toEqual([])
  })

  it('flags a stale relaxation rather than hiding it', () => {
    const stale = [{ ...base, job_id: 's', created_at: 1, out_of_date: true }]
    expect(productionParents(stale, 'w/belt.nadoc')[0].stale).toBe(true)
  })

  it('says WHICH KIND each choice is — the two mean different experiments', () => {
    // "<part> run created …" identified nothing once both kinds were in one picker: the
    // choice between them is an independent sample versus an extension of one trajectory.
    const byId = Object.fromEntries(
      productionParents(jobs, 'w/belt.nadoc').map(c => [c.job.job_id, c.label]))
    expect(byId.new).toMatch(/^belt relaxation created /)
    expect(byId.child).toMatch(/^belt production run created /)
  })

  it('keeps a deliberately chosen parent even when the part filter would drop it', () => {
    expect(productionParents(jobs, 'w/belt.nadoc', { includeJobId: 'other-part' })
      .map(c => c.job.job_id)).toContain('other-part')
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

describe('condition labels', () => {
  it('numbers the conditions in the order the panel lists them', () => {
    // The label is what every reference elsewhere in the wizard prints, so it has to be
    // assigned AFTER the sort — otherwise "(C1)" beside a field points at a different
    // condition from the C1 in the list.
    expect(conditionBadges(plan()).map(c => [c.label, c.id]))
      .toEqual([['C1', 'carve_refused'], ['C2', 'gpu'], ['C3', 'settle_stage']])
  })

  it('carries the label through to the per-stage map, so a column can reference it', () => {
    expect(conditionsByStage(plan()).get('demo_0S_settle')[0].label).toBe('C3')
  })

  it('puts the label, headline and whole explanation in the hover text', () => {
    const c = conditionBadges(plan())[0]
    expect(conditionTooltip(c)).toBe('C1 — No carve allowed\n\n…')
  })

  it('does not invent a separator when a condition has no detail', () => {
    expect(conditionTooltip({ label: 'C1', title: 'Only a headline' }))
      .toBe('C1 — Only a headline')
  })
})

describe('conditionsByField', () => {
  const sourced = () => plan({
    conditions: [
      { id: 'force_soft', kind: 'forced', title: 'Soft', detail: '…',
        applies_to: 'all', source: 'CreateJobRequest.force_soft' },
      { id: 'early_stop_off', kind: 'info', title: 'Full length', detail: '…',
        applies_to: 'all', source: 'CreateJobRequest.early_stop_relax' },
      { id: 'gpu', kind: 'conditional', title: 'GPU-resident', detail: '…',
        applies_to: 'all', source: 'md_protocols._segment_conf' },
    ],
  })

  it('links a condition to the request field the backend says raised it', () => {
    const map = conditionsByField(sourced())
    expect(map.get('force_soft').map(c => c.id)).toEqual(['force_soft'])
    // C3, not C2: the labels follow the LIST order (forced, then conditional, then info),
    // which is what the reader sees.
    expect(map.get('early_stop_relax').map(c => c.label)).toEqual(['C3'])
  })

  it('never guesses: a condition raised elsewhere belongs to no field', () => {
    // The ONLY link is the backend's own `source`. Matching on wording would attach
    // conditions to controls that do not govern them.
    expect([...conditionsByField(sourced()).keys()]).toEqual(['force_soft', 'early_stop_relax'])
  })

  it('links a production condition too — its controls live on the spawn request', () => {
    // A production run's controls are split across the two request models: its integrator
    // axes are create-request fields recorded at prep, while its length, restraints and
    // coupling belong to ProductionRunRequest. Matching only the first left every
    // production warning stranded in the list with no control beside it.
    const p = plan({ conditions: [
      { id: 'production_restraints', kind: 'warning', title: 'Unrestrained', detail: '…',
        applies_to: 'all', source: 'ProductionRunRequest.enm_restraints' },
      { id: 'box_fit', kind: 'blocking', title: 'Cell too small', detail: '…',
        applies_to: 'all', source: 'ProductionRunRequest.length_ns' },
    ] })
    const map = conditionsByField(p)
    expect(map.get('enm_restraints').map(c => c.id)).toEqual(['production_restraints'])
    expect(map.get('length_ns').map(c => c.id)).toEqual(['box_fit'])
  })
})

describe('allStageConditions', () => {
  it('is the set referenced once beside the totals, not on 22 columns', () => {
    expect(allStageConditions(plan()).map(c => c.id)).toEqual(['carve_refused', 'gpu'])
  })
})

describe('undo', () => {
  const state = () => ({
    mode: 'relaxation', presetId: 'literature', tab: 'plan',
    touched: { fast: true, threads: 8 },
    stageOverrides: { 3: { timestep: '2' } },
    parentJobId: null,
  })

  it('copies the nested values, so a later edit cannot reach into the snapshot', () => {
    const s = state()
    const snap = snapshotState(s)
    s.touched.threads = 32
    s.stageOverrides[3].timestep = '4'
    expect(snap.touched.threads).toBe(8)
    expect(snap.stageOverrides[3].timestep).toBe('2')
  })

  it('does not snapshot the open tab — moving between tabs changes nothing about the run', () => {
    expect(snapshotState(state())).not.toHaveProperty('tab')
  })

  it('restores every choice onto the live state object, in place', () => {
    const s = state()
    const snap = snapshotState(s)
    s.touched = {}
    s.presetId = 'design_speed'
    s.stageOverrides = {}
    s.mode = 'production'
    const same = applySnapshot(s, snap)
    expect(same).toBe(s)                       // the wizard holds one state reference
    expect(s).toMatchObject({ mode: 'relaxation', presetId: 'literature',
                              touched: { fast: true, threads: 8 },
                              stageOverrides: { 3: { timestep: '2' } } })
  })

  it('leaves the state alone when there is nothing to restore', () => {
    const s = state()
    applySnapshot(s, undefined)
    expect(s.presetId).toBe('literature')
  })

  it('stacks snapshots newest last', () => {
    const a = snapshotState(state())
    const b = snapshotState({ ...state(), presetId: 'design_speed' })
    expect(pushUndo(pushUndo([], a), b).map(s => s.presetId))
      .toEqual(['literature', 'design_speed'])
  })

  it('does not record a change that changed nothing', () => {
    // Snapshots are taken BEFORE a change, so an identical top means the previous edit
    // was a no-op — retyping a cell's own value. It must not cost an undo press.
    const a = snapshotState(state())
    const stack = pushUndo(pushUndo([], a), snapshotState(state()))
    expect(stack).toHaveLength(1)
  })

  it('drops the oldest once the stack is full', () => {
    let stack = []
    for (let i = 0; i < 6; i++) {
      stack = pushUndo(stack, snapshotState({ ...state(), parentJobId: `job${i}` }), 3)
    }
    expect(stack.map(s => s.parentJobId)).toEqual(['job3', 'job4', 'job5'])
  })

  it('covers a production setting, which now lives in `touched` like every other', () => {
    // They used to be five separate state slots, which is why moving them into `touched`
    // is what let them render through the same field machinery as the ladder's controls.
    const s = { ...state(), mode: 'production',
                touched: { length_ns: 100, enm_restraints: 'on' } }
    const snap = snapshotState(s)
    s.touched.length_ns = 25
    applySnapshot(s, snap)
    expect(s.touched).toEqual({ length_ns: 100, enm_restraints: 'on' })
  })
})

describe('field scope', () => {
  it('takes the backend’s declaration over the local table', () => {
    // The plan is the source of truth; the local table only exists so the FIRST render
    // groups correctly instead of reshuffling when the plan lands.
    expect(fieldScope('padding_nm', { field_scopes: { padding_nm: 'relaxation' } }))
      .toBe('relaxation')
  })

  it('falls back to the local table before the plan arrives', () => {
    expect(fieldScope('relax_hmr', null)).toBe('relaxation')
  })

  it('defaults an unknown field to both, not to one run', () => {
    // Solvation is inherited by construction: production reuses the cell and PSF built
    // for relaxation. Unknown future preparation fields stay with that group.
    expect(fieldScope('padding_nm', null)).toBe('both')
    expect(fieldScope('who_knows', null)).toBe('both')
  })

  it('keeps relaxation execution hardware out of inherited system preparation', () => {
    expect(fieldScope('gpu_resident', null)).toBe('relaxation')
    expect(fieldScope('threads', null)).toBe('relaxation')
    expect(fieldScope('devices', null)).toBe('relaxation')
  })

  it('keeps the relaxation timestep in the relaxation scope', () => {
    expect(fieldScope('relax_timestep_fs', null)).toBe('relaxation')
  })
})

describe('fieldAlert', () => {
  it('is null when the plan has no objection to this control', () => {
    expect(fieldAlert([])).toBeNull()
    expect(fieldAlert(undefined)).toBeNull()
    expect(fieldAlert([{ kind: 'info' }, { kind: 'stage' }])).toBeNull()
  })

  it('reports a warning', () => {
    expect(fieldAlert([{ kind: 'warning' }])).toBe('warning')
  })

  it('reports the WORST kind when a control has several', () => {
    expect(fieldAlert([{ kind: 'warning' }, { kind: 'blocking' }])).toBe('blocking')
  })
})

describe('WIZARD_FIELDS carries the relaxation axes', () => {
  it('sends each relaxation axis, so a deliberate combination is not silently dropped', () => {
    for (const key of ['relax_timestep_fs', 'relax_rigid_bonds', 'relax_hmr']) {
      expect(WIZARD_FIELDS).toContain(key)
    }
    expect(WIZARD_FIELDS).not.toContain('production_timestep_fs')
    expect(WIZARD_FIELDS).not.toContain('production_rigid_bonds')
    expect(WIZARD_FIELDS).not.toContain('production_hmr')
  })

  it('passes a false HMR through — false is a choice, not an absence', () => {
    // The tri-states are null=auto / true=on / false=off. A payload builder that treated
    // false as "unset" would silently re-enable HMR on the run the user turned it off for.
    expect(wizardPayload({ presetId: 'x', touched: { relax_hmr: false } }))
      .toMatchObject({ relax_hmr: false })
  })

  it('passes an explicit null (auto) through as well', () => {
    expect(wizardPayload({ presetId: 'x', touched: { relax_rigid_bonds: null } }))
      .toHaveProperty('relax_rigid_bonds', null)
  })
})

describe('jobSettingsState — a created job back into the wizard\'s own vocabulary', () => {
  /** A relaxation job as `GET /md/jobs` returns it: `prep_params` is a model_dump, so it
   *  is DENSE (every default materialised), and `prep_params_set` says which of those the
   *  user actually chose. */
  const relaxJob = (over = {}) => ({
    job_id: 'abc', design_name: '6hb', created_at: 1_700_000_000,
    execution_target: 'local', partition: null,
    prep_params: {
      relax_preset: 'literature', autostart: false,
      fast: false, padding_nm: 1.2, minimize_steps: 4800, threads: 8,
      salt_mode: 'screening', mg_conc_mM: 12.5, relax_hmr: null,
    },
    prep_params_set: ['relax_preset', 'autostart', 'fast', 'threads'],
    ...over,
  })

  it('restores only the keys the user explicitly set', () => {
    // The point of the whole exercise: replaying the dense dump would mark padding,
    // minimize_steps and the ion concentrations as user choices too, and the wizard's
    // provenance chips would then caption every protocol default as "you set this".
    const v = jobSettingsState(relaxJob())
    expect(v.touched).toEqual({ fast: false, threads: 8 })
    expect(v.provenanceKnown).toBe(true)
  })

  it('restores every stored value when editing instead of recalculating current defaults', () => {
    const v = jobSettingsState(relaxJob(), { forEdit: true })
    expect(v.touched).toMatchObject({
      fast: false, padding_nm: 1.2, minimize_steps: 4800,
      threads: 8, salt_mode: 'screening', mg_conc_mM: 12.5,
    })
    expect(v.touched).not.toHaveProperty('relax_hmr') // null still means automatic
  })

  it('keeps the protocol the job actually ran', () => {
    expect(jobSettingsState(relaxJob()).presetId).toBe('literature')
  })

  it('drops request fields the wizard does not own', () => {
    // `autostart` and `relax_preset` are in the explicit set but are not settings rows;
    // letting them into `touched` would put them in the plan request as bare fields.
    const v = jobSettingsState(relaxJob())
    expect(v.touched).not.toHaveProperty('autostart')
    expect(v.touched).not.toHaveProperty('relax_preset')
  })

  it('restores a false boolean — false is a choice, not an absence', () => {
    expect(jobSettingsState(relaxJob()).touched.fast).toBe(false)
  })

  it('falls back to every stored value when no explicit set was recorded', () => {
    const v = jobSettingsState(relaxJob({ prep_params_set: null }))
    // Values are still exact; only the provenance is unknowable, which the flag reports so
    // the view can say so instead of quietly captioning defaults as choices.
    expect(v.touched).toMatchObject({ fast: false, padding_nm: 1.2, threads: 8 })
    expect(v.provenanceKnown).toBe(false)
  })

  it('skips nulls in the fallback path — null means "auto", not a set value', () => {
    const v = jobSettingsState(relaxJob({ prep_params_set: null }))
    expect(v.touched).not.toHaveProperty('relax_hmr')
  })

  it('reads where the job ran off the job record, not the request', () => {
    // A job created locally and later submitted to Alpine has moved since its request.
    const v = jobSettingsState(relaxJob({ execution_target: 'alpine', partition: 'aa100' }))
    expect(v).toMatchObject({ target: 'alpine', partition: 'aa100' })
  })

  it('reports unavailable for a job with no recorded request', () => {
    expect(jobSettingsState(relaxJob({ prep_params: null })).available).toBe(false)
    expect(jobSettingsState(undefined).available).toBe(false)
  })

  it('carries stage overrides through, so a hand-edited ladder replays as edited', () => {
    const v = jobSettingsState(relaxJob({
      prep_params: { ...relaxJob().prep_params, stage_overrides: { 3: { timestep: '2.0' } } },
    }))
    expect(v.stageOverrides).toEqual({ 3: { timestep: '2.0' } })
  })

  describe('production children', () => {
    const prodJob = (over = {}) => ({
      job_id: 'def', design_name: '6hb', created_at: 1_700_000_500,
      run_kind: 'production', parent_job_id: 'abc', execution_target: 'local',
      spawn_params: {
        length_ns: 50, autostart: true, allow_undersized_cell: false,
        rigid_bonds: 'all', hmr: true, seed: 12345, execution_target: 'local',
      },
      spawn_params_set: ['length_ns', 'autostart', 'allow_undersized_cell',
                         'rigid_bonds', 'hmr', 'seed', 'execution_target'],
      ...over,
    })

    it('reads spawn_params, not prep_params', () => {
      const v = jobSettingsState(prodJob())
      expect(v.mode).toBe('production')
      expect(v.touched).toMatchObject({ length_ns: 50, seed: 12345 })
    })

    it('undoes the request-side rename of the two integrator axes', () => {
      // ProductionRunRequest is already about production, so it calls them `rigid_bonds`
      // and `hmr`; the wizard's own state prefixes both. Without the inverse mapping the
      // two controls would render empty on a child that pinned them.
      const v = jobSettingsState(prodJob())
      expect(v.touched.production_rigid_bonds).toBe('all')
      expect(v.touched.production_hmr).toBe(true)
      expect(v.touched).not.toHaveProperty('rigid_bonds')
    })

    it('names the parent it continues, so the plan resolves against the right package', () => {
      expect(jobSettingsState(prodJob()).parentJobId).toBe('abc')
    })

    it('stays viewable when spawn_params predates being recorded', () => {
      // The child inherits its chemistry, cell and ladder from the parent's package, and
      // the plan endpoint resolves all of that from the ROOT relaxation — so the parent id
      // is enough. Treating a missing request as "nothing to show" made every Alpine
      // fan-out report "settings were not recorded for this run".
      const v = jobSettingsState(prodJob({ spawn_params: null }))
      expect(v.available).toBe(true)
      expect(v.parentJobId).toBe('abc')
      expect(v.provenanceKnown).toBe(false)
    })
  })
})

describe('jobSettingsState — children created before spawn requests were recorded', () => {
  /** An ensemble replica as it exists on disk today: fanned out onto Alpine, so it has a
   *  parent, a velocity seed and an index — but `run_kind` is unset and there is no
   *  recorded request of any kind. */
  const replica = (over = {}) => ({
    job_id: 'r0', design_name: '6hbx100_1xT', created_at: 1_785_100_000,
    execution_target: 'alpine', partition: 'ah200',
    parent_job_id: 'a0e54cdbf20f', ensemble_seed: 54321, ensemble_index: 0,
    run_kind: null, prep_params: null, spawn_params: null,
    segments: [
      { name: '6hbx100_1xT_01_production_0p5ns_k0',
        stage: '0.5 ns production replica (seed 54321)', steps: 500000 },
    ],
    ...over,
  })

  it('treats an ensemble replica as a production run — run_kind is not the only marker', () => {
    // A replica leaves `run_kind` unset; keying only on that read every Alpine fan-out as a
    // relaxation with no recorded request, which is what made them unviewable.
    expect(jobSettingsState(replica()).mode).toBe('production')
  })

  it('is viewable — the parent rebuilds everything the child inherited', () => {
    const v = jobSettingsState(replica())
    expect(v.available).toBe(true)
    expect(v.parentJobId).toBe('a0e54cdbf20f')
    expect(v.provenanceKnown).toBe(false)
  })

  it('recovers the velocity seed, which IS this replica\'s own choice', () => {
    expect(jobSettingsState(replica()).touched.seed).toBe(54321)
  })

  it('recovers the run length by counting steps, not by parsing the stage label', () => {
    expect(jobSettingsState(replica()).touched.steps).toBe(500000)
  })

  it('a production CHILD with no spawn_params is viewable too', () => {
    const v = jobSettingsState(replica({
      run_kind: 'production', ensemble_index: null, ensemble_seed: null,
    }))
    expect(v).toMatchObject({ available: true, mode: 'production', parentJobId: 'a0e54cdbf20f' })
  })

  it('a ROOT relaxation with no request stays unviewable — nothing can rebuild it', () => {
    expect(jobSettingsState({ job_id: 'x', prep_params: null, parent_job_id: null }).available)
      .toBe(false)
  })

  it('sends the recovered steps in the plan request', () => {
    // Omitting them would plan the wizard's 1 ns default over a run that did 0.5 ns — the
    // stage table would then describe a run that never happened.
    const v = jobSettingsState(replica())
    const body = planPayload({ mode: v.mode, presetId: v.presetId, touched: v.touched,
                               parentJobId: v.parentJobId })
    expect(body).toMatchObject({ kind: 'production', parent_job_id: 'a0e54cdbf20f',
                                 steps: 500000, seed: 54321 })
  })
})

describe('productionSteps', () => {
  const seg = (name, steps, stage = '') => ({ name, steps, stage })

  it('sums every production segment', () => {
    expect(productionSteps({ segments: [seg('d_01_production_a', 100), seg('d_02_production_b', 250)] }))
      .toBe(350)
  })

  it('excludes the velocity-reseed bridge — it is not sampled time', () => {
    expect(productionSteps({ segments: [seg('d_0R_reseed', 500), seg('d_01_production', 100)] }))
      .toBe(100)
  })

  it('matches on the stage text too, mirroring the backend rule', () => {
    expect(productionSteps({ segments: [seg('d_01_run', 700, '200 ns production replica')] }))
      .toBe(700)
  })

  it('is 0 for a relaxation, so nothing is sent for one', () => {
    expect(productionSteps({ segments: [seg('d_01_k0p5', 1000)] })).toBe(0)
  })
})
