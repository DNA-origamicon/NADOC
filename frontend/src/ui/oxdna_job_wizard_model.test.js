// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardPayload, validateOxdnaWizard,
  oxdnaProductionDefaults, oxdnaProductionPayload, oxdnaProductionParents, oxdnaProductionStagePlan, validateOxdnaProductionWizard,
  oxdnaThermostatDefaults,
} from './oxdna_job_wizard_model.js'
import { initOxdnaJobWizard } from './oxdna_job_wizard.js'

describe('oxDNA job wizard model', () => {
  it('resolves the documented three-stage relaxation protocol', () => {
    const stages = oxdnaStagePlan({ backend: 'CUDA', md_relax_steps: 2_000_000 })
    expect(stages.map(s => s.name)).toEqual(['1_mc_relax', '2_md_relax', '3_equil'])
    expect(stages[0]).toMatchObject({ sim_type: 'MC', backend: 'CPU', external_forces: true })
    expect(stages[1]).toMatchObject({ sim_type: 'MD', backend: 'CUDA', steps: 2_000_000, dt: .002 })
    expect(stages[2]).toMatchObject({ max_backbone_force: 50, dt: .003, external_forces: false })
  })

  it('merges the selected hardware into the create payload', () => {
    expect(oxdnaWizardPayload({ salt_concentration: .25, engine_variant: 'adaptive-memory' }, {
      execution_target: 'runpod', runpod_gpu_key: 'NVIDIA H200', runpod_budget_usd: 5,
    })).toMatchObject({ salt_concentration: .25, engine_variant: 'adaptive-memory', execution_target: 'runpod', runpod_gpu_key: 'NVIDIA H200', runpod_budget_usd: 5 })
  })

  it('prints every stage and resolved control in the final document', () => {
    const text = oxdnaConfigDocument({ max_relax_retries: 2, seed: 246802468 }, { execution_target: 'alpine', partition: 'aa100' })
    expect(text).toContain('execution_target = alpine')
    expect(text).toContain('partition = aa100')
    expect(text).toContain('# 1_mc_relax:')
    expect(text).toContain('# 3_equil:')
    expect(text).toContain('max_relax_retries = 2')
    expect(text).toContain('seed = 246802468')
    expect(text).toContain('print_conf_interval = 10000')
    expect(oxdnaWizardPayload({ seed: 246802468 })).toHaveProperty('seed', 246802468)
  })

  it('prices all scheduled steps in the Runpod preview shape', () => {
    expect(oxdnaRunpodPlanShape().relax_steps).toBe(1_101_000)
  })

  it('applies and submits per-stage overrides without changing sibling stages', () => {
    const values = { stage_overrides: { '2_md_relax': { dt: 0.001, steps: 2_000_000 } } }
    const stages = oxdnaStagePlan(values)
    expect(stages[1]).toMatchObject({ dt: 0.001, steps: 2_000_000 })
    expect(stages[2].dt).toBe(0.003)
    expect(oxdnaWizardPayload(values).stage_overrides).toEqual(values.stage_overrides)
  })

  it('rejects malformed protocol values and unknown engine builds', () => {
    const result = validateOxdnaWizard({ engine_variant: 'mystery', salt_concentration: 0,
      mc_steps: 99, min_bp_retained: 1.1, max_relax_retries: 4 })
    expect(result.valid).toBe(false)
    expect(Object.keys(result.errors)).toEqual(expect.arrayContaining([
      'engine_variant', 'salt_concentration', 'mc_steps', 'min_bp_retained', 'max_relax_retries',
    ]))
  })

  it('accepts every supported engine build with the default protocol', () => {
    for (const engine_variant of ['auto', 'adaptive-memory', 'dnanm', 'upstream'])
      expect(validateOxdnaWizard({ engine_variant })).toEqual({ valid: true, errors: {} })
  })
})

describe('oxDNA copied-job seed display', () => {
  const copiedJob = (over = {}) => ({
    job_id: 'copy-1', status: 'queued', execution_target: 'local',
    backend: 'CUDA', device: '0', salt_concentration: 0.5,
    random_seed: 246802468,
    run_config: {
      kind: 'relax', seed: 135791357, backend: 'CUDA', device: '0',
      salt_concentration: 0.5, mc_steps: 1000, md_relax_steps: 1_000_000,
      equil_steps: 100_000, min_bp_retained: 0.5, max_relax_retries: 3,
    },
    stages: [{ name: '1_mc_relax', kind: 'mc', steps: 1000, status: 'pending' }],
    ...over,
  })
  const makeWizard = () => initOxdnaJobWizard({
    api: {
      fetchHardware: async () => ({}),
      getOxdnaAvailable: async () => ({ available: false }),
      fetchAvailability: async () => ({}),
      getSlurmPreview: async () => ({}),
      getRunpodJobPreview: async () => ({}),
      getRunpodVolumes: async () => ({ volumes: [] }),
    },
  })

  it('shows the newly assigned seed, not the source request seed, while editing', () => {
    const wizard = makeWizard()
    wizard.openEditable(copiedJob())
    const input = document.querySelector('[data-oxdna-field="seed"]')
    expect(input.value).toBe('246802468')
    expect(input.readOnly).toBe(true)
    expect(wizard.currentValues().seed).toBe(246802468)
    wizard.close()
  })

  it('shows the newly assigned seed in the read-only settings snapshot', () => {
    const wizard = makeWizard()
    wizard.openReadOnly(copiedJob())
    const text = document.querySelector('.oxdna-job-settings-view').textContent
    expect(text).toContain('"seed": 246802468')
    expect(text).not.toContain('"seed": 135791357')
    wizard.close()
  })

  it('writes continuation thermostat controls into the saved configuration without losing other settings', () => {
    const wizard = makeWizard()
    wizard.openEditable(copiedJob({
      parent_job_id: 'parent',
      run_config: { kind: 'run', stage_overrides: { '1_production': { dt: 0.001 } } },
      stages: [{ name: '1_production', kind: 'md', steps: 10000 }],
    }))
    const select = document.querySelector('[aria-label="Thermostat on 1_production"]')
    expect([...select.options].filter(option => option.value).every(option => option.title.length > 20)).toBe(true)
    expect(select.title).toContain('Langevin:')
    select.value = 'langevin'
    select.dispatchEvent(new Event('change'))
    const diffusion = document.querySelector('[aria-label="Diffusion coefficient on 1_production"]')
    expect(diffusion.value).toBe('2.5')
    diffusion.value = '0.5'
    diffusion.dispatchEvent(new Event('change'))
    select.value = 'brownian'
    select.dispatchEvent(new Event('change'))
    expect(diffusion.value).toBe('0.5')
    select.value = 'langevin'
    select.dispatchEvent(new Event('change'))
    const config = JSON.parse(document.querySelector('[aria-label="Editable oxDNA job configuration"]').value)
    expect(config.stages[0]).toMatchObject({ thermostat: 'langevin', diff_coeff: 0.5, steps: 10000 })
    expect(config.stage_overrides['1_production'].dt).toBe(0.001)
    wizard.close()
  })
})

it('requires explicit diffusion when changing a stage to a local bath', () => {
  const stage_overrides = { '3_equil': { thermostat: 'john', refresh_vel: false } }
  expect(validateOxdnaWizard({ stage_overrides }).valid).toBe(false)
  stage_overrides['3_equil'].diff_coeff = 0.1
  expect(validateOxdnaWizard({ stage_overrides }).valid).toBe(true)
  expect(oxdnaStagePlan({ stage_overrides })[2]).toMatchObject({ thermostat: 'john', diff_coeff: 0.1, refresh_vel: false })
})

it('previews the fixed-gold hybrid with GPU MD and persistent model forces', () => {
  const stages = oxdnaStagePlan({ protein_present: true, fixed_core_present: true })
  expect(stages[0].backend).toBe('CPU')
  for (const stage of stages.slice(1)) expect(stage).toMatchObject({ backend: 'CUDA', interaction_type: 'DNANM', dt: 0.0001, external_forces: true, fix_diffusion: false })
  expect(stages[2].forces_file).toBe('equil_forces.txt')
  expect(stages[2].seq_dep_file).toBeUndefined()
})

describe('oxDNA production wizard model', () => {
  it('previews the selected parent parameters and preserves explicit wizard edits', () => {
    const first = { job_id: 'first', status: 'completed', created_at: 2,
      continuation_parameters: { thermostat: 'langevin', diff_coeff: 0.7, dt: 0.001, temperature: '310K', refresh_vel: false } }
    const second = { job_id: 'second', status: 'completed', created_at: 1,
      continuation_parameters: { thermostat: 'brownian', diff_coeff: 1.2, dt: 0.002, temperature: '300K', refresh_vel: true } }
    const wizard = initOxdnaJobWizard({ getJobs: () => [first, second] })
    wizard.open('production')
    expect(oxdnaProductionStagePlan(wizard.currentValues())[0]).toMatchObject(first.continuation_parameters)
    const picker = document.querySelector('[aria-label="Continue from"]')
    picker.value = 'second'
    picker.dispatchEvent(new Event('change'))
    expect(oxdnaProductionStagePlan(wizard.currentValues())[0]).toMatchObject(second.continuation_parameters)
    expect(validateOxdnaProductionWizard(wizard.currentValues()).valid).toBe(true)
    expect(oxdnaProductionStagePlan({ ...wizard.currentValues(), stage_overrides: {
      '1_production': { diff_coeff: 0.1, dt: 0.0005 },
    } })[0]).toMatchObject({ thermostat: 'brownian', diff_coeff: 0.1, dt: 0.0005 })
    // Inheritance is resolved by the backend, not copied back as explicit edits.
    expect(oxdnaProductionPayload(wizard.currentValues())).not.toHaveProperty('stage_overrides')
    wizard.close()
  })

  it('defaults blank local-bath diffusion without overwriting explicit choices', () => {
    for (const thermostat of ['langevin', 'brownian', 'john']) {
      expect(oxdnaThermostatDefaults(thermostat, null)).toEqual({ diff_coeff: 2.5 })
      expect(oxdnaThermostatDefaults(thermostat, '')).toEqual({ diff_coeff: 2.5 })
      expect(oxdnaThermostatDefaults(thermostat, 0.1)).toEqual({})
      expect(oxdnaThermostatDefaults(thermostat, 0)).toEqual({})
    }
    expect(oxdnaThermostatDefaults('bussi', null)).toEqual({})
    expect(oxdnaThermostatDefaults('no', null)).toEqual({})
  })
  it('creates a new continuation with thermostat settings and a matching summary', async () => {
    let submitted
    const wizard = initOxdnaJobWizard({
      estimateRunSize: (steps, interval) => ({ frames: Math.floor(steps / interval), bytes: Math.floor(steps / interval) * 130080 }),
      getJobs: () => [{ job_id: 'parent', status: 'completed', backend: 'CUDA', device: '0', salt_concentration: 0.5 }],
      spawnProduction: async (id, payload) => { submitted = { id, payload }; return { job_id: 'created' } },
    })
    wizard.open('production')
    const modal = document.querySelector('.modal--oxdna-wizard')
    const settings = [...modal.querySelectorAll('.wizard-tabpanel')].find(panel => !panel.hidden)
    const estimate = settings.querySelector('[data-oxdna-output-estimate]')
    expect(estimate.textContent).toContain('500 saved frames')
    expect(estimate.textContent).not.toContain('size unknown')
    const cadence = settings.querySelector('[data-oxdna-field="steps_per_frame"]')
    cadence.value = '20000'
    cadence.dispatchEvent(new Event('input'))
    expect(estimate.textContent).toContain('250 saved frames')
    const thermostat = settings.querySelector('[aria-label="Thermostat on 1_production"]')
    expect(thermostat).not.toBeNull()
    thermostat.value = 'langevin'
    thermostat.dispatchEvent(new Event('change'))
    expect(validateOxdnaProductionWizard(wizard.currentValues()).valid).toBe(true)
    expect(wizard.currentValues().stage_overrides['1_production'].diff_coeff).toBe(2.5)
    const row = [...settings.querySelectorAll('tr')].find(row => row.textContent.includes('Diffusion coefficient'))
    row.querySelector('td').click()
    const input = row.querySelector('input')
    input.value = '0.5'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    const changedThermostat = settings.querySelector('[aria-label="Thermostat on 1_production"]')
    changedThermostat.value = 'brownian'
    changedThermostat.dispatchEvent(new Event('change'))
    expect(wizard.currentValues().stage_overrides['1_production'].diff_coeff).toBe(0.5)
    const finalThermostat = settings.querySelector('[aria-label="Thermostat on 1_production"]')
    finalThermostat.value = 'langevin'
    finalThermostat.dispatchEvent(new Event('change'))
    ;[...modal.querySelectorAll('.wizard-tab')].find(tab => tab.textContent === 'Summary').click()
    expect(modal.querySelector('.oxdna-wizard-config').textContent).toContain('thermostat = langevin')
    expect(modal.querySelector('.oxdna-wizard-config').textContent).toContain('diff_coeff = 0.5')
    const create = [...modal.querySelectorAll('button')].find(button => button.textContent === 'Create job')
    expect(create.disabled).toBe(false)
    create.click()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(submitted).toMatchObject({ id: 'parent', payload: { stage_overrides: { '1_production': { thermostat: 'langevin', diff_coeff: 0.5 } } } })
    wizard.close()
  })

  it('defaults match the prior Full Sim UI (5,000,000 steps / 10,000 per frame)', () => {
    expect(oxdnaProductionDefaults()).toEqual({ steps: 5_000_000, steps_per_frame: 10_000 })
    expect(oxdnaProductionDefaults({ steps: 1_000_000 })).toMatchObject({ steps: 1_000_000, steps_per_frame: 10_000 })
  })

  it('requires a parent job and bounds steps/steps_per_frame like RunRequest', () => {
    expect(validateOxdnaProductionWizard({}).valid).toBe(false)
    expect(validateOxdnaProductionWizard({}).errors).toHaveProperty('parentJobId')
    expect(validateOxdnaProductionWizard({ parentJobId: 'p1', steps: 500 }).errors).toHaveProperty('steps')
    expect(validateOxdnaProductionWizard({ parentJobId: 'p1', steps_per_frame: 0 }).errors).toHaveProperty('steps_per_frame')
    expect(validateOxdnaProductionWizard({ parentJobId: 'p1' })).toEqual({ valid: true, errors: {} })
  })

  it('inherits backend/device/salt from the parent and maps steps_per_frame to print_conf_interval', () => {
    const parent = { backend: 'CUDA', device: '1', salt_concentration: 0.3 }
    const [stage] = oxdnaProductionStagePlan({ steps: 2_000_000, steps_per_frame: 5000 }, parent)
    expect(stage).toMatchObject({
      name: '1_production', sim_type: 'MD', backend: 'CUDA', device: '1',
      salt_concentration: 0.3, steps: 2_000_000, print_conf_interval: 5000,
    })
  })

  it('payload excludes field/surface/anchors — those stay sourced from the shared run-elements panel', () => {
    expect(oxdnaProductionPayload({ steps: 3_000_000, steps_per_frame: 20_000 }))
      .toEqual({ steps: 3_000_000, steps_per_frame: 20_000 })
  })

  it('lists only completed jobs for the current design, newest first, with an includeId escape hatch', () => {
    const jobs = [
      { job_id: 'a', status: 'completed', design_source_path: 'X.nadoc', created_at: 1 },
      { job_id: 'b', status: 'running', design_source_path: 'X.nadoc', created_at: 2 },
      { job_id: 'c', status: 'completed', design_source_path: 'X.nadoc', created_at: 3,
        parent_job_id: 'a', run_config: { kind: 'surface_deposition' } },
      { job_id: 'd', status: 'completed', design_source_path: 'Other.nadoc', created_at: 4 },
    ]
    expect(oxdnaProductionParents(jobs, 'X.nadoc').map(j => j.job_id)).toEqual(['c', 'a'])
    // A chosen parent from another design's path still survives via includeJobId.
    expect(oxdnaProductionParents(jobs, 'X.nadoc', { includeJobId: 'd' }).map(j => j.job_id)).toEqual(['d', 'c', 'a'])
  })
})
