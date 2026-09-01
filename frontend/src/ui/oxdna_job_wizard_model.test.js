// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardPayload, validateOxdnaWizard } from './oxdna_job_wizard_model.js'
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
})
