// @vitest-environment jsdom
/**
 * The Job Wizard opened READ-ONLY on a job that already exists ("View settings").
 *
 * The whole value of reusing the wizard is that it is the same three steps, the same
 * stage table and the same conditions the run was set up in — so the thing worth pinning
 * is not that it renders, but that nothing in it can be changed and that it does not
 * reach back out into the app. Every escape hatch checked here has a real consequence if
 * it leaks: `onTargetChange` moves the panel's run-target radios for the NEXT job, the
 * run-directory picker is an app-wide preference, the cluster chip starts a second status
 * poller, and a stage-cell edit would re-plan a run that has already been built.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fieldAppliesToTarget, initJobWizard } from './md_job_wizard.js'

/** A plan in the shape POST /md/protocol-plan returns, trimmed to what the wizard reads. */
const PLAN = {
  param_groups: ['Integrator'],
  stages: [
    {
      index: 0, name: 'demo_00_min', stage: 'Energy minimisation', role: 'minimization',
      steps: 4800, timestep_fs: 0, ns: 0,
      params: { minimize: '4800', rigidbonds: 'none' },
      diff_vs_previous: {}, conditional_params: {},
    },
    {
      index: 1, name: 'demo_01_k0p5', stage: '300K NPT ENM k=0.5', role: 'ladder',
      steps: 120000, timestep_fs: 2, ns: 0.24,
      params: { timestep: '2', rigidbonds: 'all' },
      diff_vs_previous: { timestep: ['(absent)', '2'] }, conditional_params: {},
    },
  ],
  request: {
    padding_nm: { value: 1.2, provenance: 'preset', reason: 'set by the literature preset' },
    fast: { value: false, provenance: 'user', reason: '' },
    threads: { value: 8, provenance: 'user', reason: '' },
    minimize_steps: { value: 4800, provenance: 'default', reason: '' },
  },
  totals: { n_stages: 2, total_steps: 124800, total_ns: 0.24 },
  preset: { id: 'literature', label: 'Literature protocol' },
  inherited: { parent_job_id: 'parent1', parent_run_kind: 'relaxation',
               design_name: 'parent-design', created_at: 1_785_000_000, rows: [] },
  conditions: [], deferred: [], retries: [], warnings: [],
}

const JOB = {
  job_id: 'abc123', design_name: '6hb_demo', created_at: 1_785_000_000,
  execution_target: 'local', partition: null, resources: null, requested_resources: null,
  prep_params: {
    relax_preset: 'literature', autostart: false, fast: false, threads: 8,
    padding_nm: 1.2, minimize_steps: 4800, salt_mode: 'screening',
  },
  prep_params_set: ['relax_preset', 'autostart', 'fast', 'threads'],
}

function setup(over = {}) {
  document.body.innerHTML = ''
  const fetchProtocolPlan = vi.fn(async () => PLAN)
  const onTargetChange = vi.fn()
  const launch = vi.fn(async () => ({ job_id: 'new' }))
  const spawnProduction = vi.fn(async () => ({ job_id: 'new' }))
  const updateJob = vi.fn(async (id) => ({ job_id: id }))
  const api = {
    fetchProtocolPlan,
    getRelaxPresets: vi.fn(async () => ({
      presets: [
        { id: 'literature', label: 'Literature protocol', summary: 'as published' },
        { id: 'design_speed', label: 'Design speed', summary: 'faster' },
      ],
    })),
    // Every live probe step 1 can make. None of them may fire in read-only.
    fetchHardware: vi.fn(async () => ({ gpu_name: 'RTX 3090', summary: 'RTX 3090' })),
    fetchAvailability: vi.fn(async () => ({ partitions: [] })),
    getSlurmPreview: vi.fn(async () => ({ resources: {} })),
    lastErrorMessage: () => '',
  }
  const wiz = initJobWizard({
    api, launch, spawnProduction, updateJob, onTargetChange,
    getJobs: () => [], getPartPath: () => null, ...over,
  })
  return { wiz, api, onTargetChange, launch, spawnProduction, updateJob }
}

const modalRoot = () => document.querySelector('.modal--wizard') || document.body
const footerButtons = () => [...document.querySelectorAll('.modal__actions button, .modal__footer button')]
const buttonLabels = () => footerButtons()
  .filter(b => b.style.display !== 'none')
  .map(b => b.textContent.trim())
const fieldControl = label => {
  const field = [...modalRoot().querySelectorAll('.wizard-field')]
    .find(el => el.querySelector('.wizard-field__label')?.textContent.includes(label))
  return field?.querySelector('.wizard-field__control input, .wizard-field__control select')
}

beforeEach(() => { document.body.innerHTML = '' })

describe('read-only wizard', () => {
  it('shows the job\'s own settings, not the protocol defaults', async () => {
    const { wiz, api } = setup()
    await wiz.openReadOnly(JOB)
    // The replayed request carries exactly the keys the user chose. Sending the dense
    // prep_params dump instead would mark every default as an explicit choice.
    const body = api.fetchProtocolPlan.mock.calls[0][0]
    expect(body).toMatchObject({ relax_preset: 'literature', fast: false, threads: 8 })
    expect(body).not.toHaveProperty('padding_nm')
    expect(body).not.toHaveProperty('minimize_steps')
  })

  it('disables every settings control', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const controls = [...modalRoot().querySelectorAll('.wizard-field__control input, '
      + '.wizard-field__control select')]
    expect(controls.length).toBeGreaterThan(0)
    for (const c of controls) expect(c.disabled).toBe(true)
  })

  it('offers Close / Previous / Next and no Create', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const labels = buttonLabels()
    expect(labels).toContain('Close')
    expect(labels).not.toContain('Cancel')
    expect(labels).not.toContain('Create job')
    expect(labels.some(l => l.includes('Next'))).toBe(true)
  })

  it('still pages through all three steps', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const tabs = [...modalRoot().querySelectorAll('.wizard-tab')]
    expect(tabs).toHaveLength(3)
    // The live gate refuses to leave step 1 until it is answered; a finished job answered
    // it long ago, so Next must not be blocked here.
    const next = footerButtons().find(b => b.textContent.includes('Next'))
    expect(next.disabled).toBe(false)
    next.click()
    expect(modalRoot().querySelectorAll('.wizard-tab')[1].classList.contains('is-selected'))
      .toBe(true)
  })

  it('renders the stage table with every cell locked', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const cells = [...modalRoot().querySelectorAll('.wizard-cell')]
    expect(cells.length).toBeGreaterThan(0)
    for (const c of cells) expect(c.classList.contains('wizard-cell--locked')).toBe(true)
    // A locked cell must not turn into an input when clicked.
    cells[0].click()
    expect(cells[0].querySelector('input')).toBeNull()
  })

  it('drops the set-for-every-stage and Undo affordances', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    expect(modalRoot().querySelectorAll('.wizard-row-all')).toHaveLength(0)
    const undo = [...modalRoot().querySelectorAll('.wizard-tabbar button')]
      .find(b => b.textContent.includes('Undo'))
    expect(undo.style.display).toBe('none')
  })

  it('shows only the protocol the run used', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const cards = [...modalRoot().querySelectorAll('.wizard-preset')]
    expect(cards).toHaveLength(1)
    expect(cards[0].textContent).toContain('Literature protocol')
  })

  it('never mirrors the viewed job\'s target onto the panel', async () => {
    // onTargetChange writes the panel's run-target radios, which decide where the NEXT
    // job goes. Looking at an old Alpine run must not move them.
    const { wiz, onTargetChange } = setup()
    await wiz.openReadOnly({ ...JOB, execution_target: 'alpine', partition: 'ah200' })
    expect(onTargetChange).not.toHaveBeenCalled()
  })

  it('makes none of step 1\'s live probes', async () => {
    const { wiz, api } = setup()
    await wiz.openReadOnly({ ...JOB, execution_target: 'alpine', partition: 'ah200' })
    expect(api.fetchHardware).not.toHaveBeenCalled()
    expect(api.fetchAvailability).not.toHaveBeenCalled()
    expect(api.getSlurmPreview).not.toHaveBeenCalled()
  })

  it('names the job by part and creation time, never by job id', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const title = document.querySelector('.modal__title').textContent
    expect(title).toContain('6hb_demo')
    expect(title).not.toContain('abc123')
  })

  it('says so when the job cannot report which values were chosen', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly({ ...JOB, prep_params_set: null })
    expect(modalRoot().querySelector('.wizard-readonly-banner').textContent)
      .toMatch(/cannot tell a choice apart/)
  })

  it('drops the preset note when provenance is unknown — it would be a lie', async () => {
    // The note counts settings still coming from the protocol. The replay sends every
    // stored value explicitly, so the plan reports none as the preset's and the note reads
    // "every setting has been overridden" about a run that overrode nothing.
    const { wiz } = setup()
    await wiz.openReadOnly({ ...JOB, prep_params_set: null })
    const card = modalRoot().querySelector('.wizard-preset')
    expect(card.querySelector('.wizard-preset__note')).toBeNull()
  })

  it('keeps the preset note when the job DOES record its provenance', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    expect(modalRoot().querySelector('.wizard-preset .wizard-preset__note')).not.toBeNull()
  })

  it('omits that caveat when the job does record it', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    const banner = modalRoot().querySelector('.wizard-readonly-banner')
    expect(banner.textContent).toMatch(/Read-only/)
    expect(banner.textContent).not.toMatch(/cannot tell a choice apart/)
  })
})

describe('live wizard commit', () => {
  it('shows Creating job for RunPod and stays open until the panel has a job id', async () => {
    let finishLaunch
    const launch = vi.fn(() => new Promise(resolve => { finishLaunch = resolve }))
    const onJobCreated = vi.fn()
    const { wiz } = setup({ launch, onJobCreated })
    await wiz.open('relaxation')

    modalRoot().querySelector('[data-target="runpod"] > div').click()

    // Creation is offered on the final plan step.
    const tabs = [...modalRoot().querySelectorAll('.wizard-tab')]
    tabs.at(-1).click()
    const create = footerButtons().find(b => b.textContent.includes('Create job'))
    await vi.waitFor(() => expect(create.disabled).toBe(false))

    create.click()
    expect(launch).toHaveBeenCalledOnce()
    expect(launch.mock.calls[0][0].execution_target).toBe('runpod')
    expect(wiz.isOpen()).toBe(true)
    expect(create.disabled).toBe(true)
    expect(create.textContent).toContain('Creating job…')
    expect(onJobCreated).not.toHaveBeenCalled()

    finishLaunch({ job_id: 'new' })
    await vi.waitFor(() => expect(onJobCreated).toHaveBeenCalledWith('new'))
    expect(wiz.isOpen()).toBe(false)
  })

  it('keeps the wizard open and restores Create job when creation fails', async () => {
    const launch = vi.fn(async () => null)
    const { wiz } = setup({ launch })
    await wiz.open('relaxation')
    ;[...modalRoot().querySelectorAll('.wizard-tab')].at(-1).click()
    const create = footerButtons().find(b => b.textContent.includes('Create job'))
    await vi.waitFor(() => expect(create.disabled).toBe(false))

    create.click()
    await vi.waitFor(() => expect(launch).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(create.textContent).toContain('Create job'))
    expect(wiz.isOpen()).toBe(true)
    expect(create.disabled).toBe(false)
  })
})

describe('editable existing job', () => {
  it('populates controls from every stored job value, including inherited defaults', async () => {
    const { wiz } = setup()
    await wiz.openEditable({
      ...JOB,
      status: 'queued',
      prep_params: { ...JOB.prep_params, padding_nm: 3.7, minimize_steps: 9900 },
    })

    // The mocked current plan still advertises 1.2 / 4800. Edit must display the values
    // frozen into this job, even though those keys were not explicit user choices when
    // it was originally created and therefore are absent from prep_params_set.
    const tabs = [...modalRoot().querySelectorAll('.wizard-tab')]
    tabs[1].click()
    expect(fieldControl('Water padding')?.value).toBe('3.7')
    expect(fieldControl('Minimisation steps')?.value).toBe('9900')
  })

  it('replays settings and saves into the same job instead of creating another', async () => {
    const { wiz, updateJob, launch, spawnProduction } = setup()
    await wiz.openEditable({ ...JOB, status: 'queued' })
    const controls = [...modalRoot().querySelectorAll('.wizard-field__control input, '
      + '.wizard-field__control select')]
    expect(controls.some(c => !c.disabled)).toBe(true)

    const tabs = [...modalRoot().querySelectorAll('.wizard-tab')]
    tabs.at(-1).click()
    const save = footerButtons().find(b => b.textContent.includes('Save changes'))
    await vi.waitFor(() => expect(save.disabled).toBe(false))
    save.click()

    expect(updateJob).toHaveBeenCalledWith('abc123', expect.any(Object))
    expect(launch).not.toHaveBeenCalled()
    expect(spawnProduction).not.toHaveBeenCalled()
  })
})

describe('a child rebuilt from its parent', () => {
  // An Alpine ensemble replica as it exists on disk: a parent, a seed, an index, and no
  // recorded request of any kind. Reporting these as unviewable is what made every Alpine
  // fan-out say "settings were not recorded for this run".
  const REPLICA = {
    job_id: 'rep0', design_name: '6hbx100_1xT', created_at: 1_785_100_000,
    execution_target: 'alpine', partition: 'ah200',
    parent_job_id: 'parent1', ensemble_seed: 54321, ensemble_index: 0,
    run_kind: null, prep_params: null, spawn_params: null,
    segments: [{ name: 'x_01_production_0p5ns_k0', stage: '0.5 ns production replica', steps: 500000 }],
  }

  it('opens, and plans against the parent with the recovered steps and seed', async () => {
    const { wiz, api } = setup({ getJobs: () => [] })
    await wiz.openReadOnly(REPLICA)
    const body = api.fetchProtocolPlan.mock.calls[0][0]
    expect(body).toMatchObject({ kind: 'production', parent_job_id: 'parent1',
                                 steps: 500000, seed: 54321 })
  })

  it('says its request was not recorded — NOT that the chips are untrustworthy', async () => {
    const { wiz } = setup({ getJobs: () => [] })
    await wiz.openReadOnly(REPLICA)
    const banner = modalRoot().querySelector('.wizard-readonly-banner').textContent
    expect(banner).toMatch(/reconstructed from the run it continued/)
    expect(banner).not.toMatch(/predates settings-provenance recording/)
  })

  it('states the parent from the plan, never from a picker over the current list', async () => {
    // A <select> whose value matches no option displays its FIRST one, so a parent the
    // panel is not listing (archived, another part, deleted) captioned the run with a
    // completely different one. There is no select here at all.
    const { wiz } = setup({ getJobs: () => [] })
    await wiz.openReadOnly(REPLICA)
    const parent = modalRoot().querySelector('.wizard-scope--parent')
    expect(parent.querySelector('select')).toBeNull()
    expect(parent.textContent).toContain('parent-design')
  })
})

describe('returning to the live wizard', () => {
  it('does not leave the viewed job\'s settings in the next new job', async () => {
    // One `state` object and one modal serve both. Without parking the live state, looking
    // at a finished run would silently pre-load its protocol and settings into the next
    // job the user creates.
    const { wiz, api } = setup()
    await wiz.open('relaxation')
    api.fetchProtocolPlan.mockClear()
    await wiz.openReadOnly(JOB)
    api.fetchProtocolPlan.mockClear()
    await wiz.open('relaxation')
    const body = api.fetchProtocolPlan.mock.calls[0][0]
    expect(body.relax_preset).not.toBe('literature')
    expect(body).not.toHaveProperty('threads')
    expect(body).not.toHaveProperty('fast')
  })

  it('re-enables the controls', async () => {
    const { wiz } = setup()
    await wiz.openReadOnly(JOB)
    await wiz.open('relaxation')
    const controls = [...modalRoot().querySelectorAll('.wizard-field__control input')]
    // `disabled` survives only where the plan itself forces the field; nothing in this
    // fixture is forced, so a still-disabled control would mean the lock leaked.
    expect(controls.some(c => !c.disabled)).toBe(true)
    expect(buttonLabels()).toContain('Cancel')
  })
})

describe('a production child', () => {
  const CHILD = {
    job_id: 'child9', design_name: '6hb_demo', created_at: 1_785_000_900,
    run_kind: 'production', parent_job_id: 'parent1', execution_target: 'local',
    spawn_params: { length_ns: 200, autostart: true, allow_undersized_cell: false, seed: 7 },
    spawn_params_set: ['length_ns', 'autostart', 'allow_undersized_cell', 'seed'],
  }

  it('keeps the parent it actually continued, even when the list cannot see it', () => {
    // `ensureParent` re-derives the parent from the panel's CURRENT job list. For a job
    // being viewed that is wrong twice: it would repoint the plan at the newest relaxation,
    // and with the list filtered to another part it nulls the parent out entirely — the
    // step then reads "no completed relaxation for this part yet" about a run that has one.
    const { wiz, api } = setup({ getJobs: () => [] })
    return wiz.openReadOnly(CHILD).then(() => {
      const body = api.fetchProtocolPlan.mock.calls[0][0]
      expect(body).toMatchObject({ kind: 'production', parent_job_id: 'parent1', length_ns: 200 })
    })
  })
})

// ── which settings a target may see ──────────────────────────────────────────────

describe('fieldAppliesToTarget', () => {
  const local = { key: 'threads', localOnly: true }
  const plain = { key: 'padding_nm' }

  it('local-only hardware is hidden on a cluster run', () => {
    expect(fieldAppliesToTarget(local, 'local')).toBe(true)
    expect(fieldAppliesToTarget(local, 'alpine')).toBe(false)
    expect(fieldAppliesToTarget(local, 'runpod')).toBe(false)
  })

  it('an ordinary setting applies everywhere', () => {
    for (const t of ['local', 'alpine', 'runpod']) {
      expect(fieldAppliesToTarget(plain, t)).toBe(true)
    }
  })

  it('copes with a missing descriptor — the submit filter looks keys up by map', () => {
    expect(fieldAppliesToTarget(undefined, 'alpine')).toBe(true)
  })
})
