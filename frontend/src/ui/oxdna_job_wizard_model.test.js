import { describe, expect, it } from 'vitest'
import { oxdnaConfigDocument, oxdnaRunpodPlanShape, oxdnaStagePlan, oxdnaWizardPayload } from './oxdna_job_wizard_model.js'

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
    const text = oxdnaConfigDocument({ max_relax_retries: 2 }, { execution_target: 'alpine', partition: 'aa100' })
    expect(text).toContain('execution_target = alpine')
    expect(text).toContain('partition = aa100')
    expect(text).toContain('# 1_mc_relax:')
    expect(text).toContain('# 3_equil:')
    expect(text).toContain('max_relax_retries = 2')
    expect(text).toContain('print_conf_interval = 10000')
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
})
