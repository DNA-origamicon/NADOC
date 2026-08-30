// @vitest-environment jsdom
/**
 * Factory contract for the wizard's "Where it runs" step.
 *
 * The load-bearing behaviours are the gate (you cannot leave this step with an Alpine
 * target and no node) and the payload it contributes — both decide whether a job is
 * submittable at all.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { initWizardTargetStep } from './md_job_wizard_target.js'

const HW = { gpu_name: 'NVIDIA GeForce RTX 3090', vram_mb: 24576, host_ram_mb: 65536,
             physical_cores: 16, atom_cap: 1_800_000, summary: 'RTX 3090 · 24 GB VRAM' }

const AVAIL = {
  partitions: [
    { partition: 'ah200', gpu_model: 'NVIDIA H200', gpus_free: 6, gpus_total: 16,
      mig_free: 25, mig_total: 40, wait_label: '~0 min', wait_basis: 'free now', speed_factor: 2.5 },
    { partition: 'aa100', gpu_model: 'NVIDIA A100', gpus_free: 0, gpus_total: 30,
      wait_label: '13 d 16 h', wait_basis: 'SLURM backfill estimate', speed_factor: 1.0 },
  ],
}

function setup(over = {}) {
  document.body.innerHTML = '<div id="mount"></div>'
  const mount = document.getElementById('mount')
  const onChange = vi.fn()
  const fetchHardware = vi.fn(async () => HW)
  const fetchAvailability = vi.fn(async () => AVAIL)
  // Stub the login chip so the test never touches the real /api/cluster/status poller.
  const connect = vi.fn(() => ({ getState: () => 'disconnected', dispose: vi.fn() }))
  const step = initWizardTargetStep({
    mount, fetchHardware, fetchAvailability, connect, onChange, ...over,
  })
  step.render()
  return { step, mount, onChange, fetchHardware, fetchAvailability, connect }
}

const clickTarget = (mount, id) =>
  mount.querySelector(`.wiz-target-card[data-target="${id}"] div`).click()

const connectCluster = () => window.dispatchEvent(
  new CustomEvent('nadoc:cluster-state-change', { detail: { state: 'connected' } }))

beforeEach(() => { document.body.innerHTML = '' })

describe('render', () => {
  it('offers all three targets with local preselected', () => {
    const { mount, step } = setup()
    expect(mount.querySelectorAll('.wiz-target-card')).toHaveLength(3)
    expect(step.target).toBe('local')
    step.dispose()
  })

  it('probes local hardware and shows it', async () => {
    const { mount, fetchHardware, step } = setup()
    await vi.waitFor(() => expect(fetchHardware).toHaveBeenCalled())
    await vi.waitFor(() => expect(mount.textContent).toContain('RTX 3090'))
    expect(mount.textContent).toContain('1.8M atoms')
    step.dispose()
  })

  it('does not open a cluster session for a user who never picks Alpine', () => {
    // A second /api/cluster/status poller for an untouched target is pure waste.
    const { connect, step } = setup()
    expect(connect).not.toHaveBeenCalled()
    step.dispose()
  })
})

describe('the gate', () => {
  it('local is immediately ready', () => {
    const { step } = setup()
    expect(step.isReady()).toBe(true)
    step.dispose()
  })

  it('alpine is NOT ready while signed out', () => {
    const { mount, step } = setup()
    clickTarget(mount, 'alpine')
    expect(step.target).toBe('alpine')
    expect(step.isReady()).toBe(false)
    expect(step.readiness().reason).toMatch(/Sign in/)
    step.dispose()
  })

  it('runpod preview is advisory and does not block the first tab', () => {
    // No preview has come back yet. The final protocol and solvated package do not exist at
    // this point, so the paid-resource gate belongs to the prepared job's Rent & Run action.
    const { mount, step } = setup()
    clickTarget(mount, 'runpod')
    expect(step.isReady()).toBe(true)
    expect(step.readiness().reason).toBe('')
    step.dispose()
  })

  it('becomes ready once signed in and a node is auto-picked', async () => {
    const { mount, step, fetchAvailability } = setup()
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(fetchAvailability).toHaveBeenCalled())
    await vi.waitFor(() => expect(step.partition).toBe('ah200'))
    expect(step.isReady()).toBe(true)
    step.dispose()
  })
})

describe('partition selection', () => {
  it('renders one clickable row per partition with wait and relative speed', async () => {
    const { mount, step } = setup()
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(mount.querySelectorAll('.wiz-part-row').length).toBe(2))
    const html = mount.innerHTML
    expect(html).toContain('ah200')
    expect(html).toContain('13 d 16 h')
    expect(html).toContain('this computer')       // speed relative to the local RTX 3090
    step.dispose()
  })

  it('lets the user override the auto-pick', async () => {
    const { mount, step } = setup()
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(step.partition).toBe('ah200'))
    mount.querySelector('.wiz-part-row[data-partition="aa100"]').click()
    expect(step.partition).toBe('aa100')
    step.dispose()
  })

  it('shows Alpine maintenance and the next start after connecting', async () => {
    const fetchAvailability = vi.fn(async () => ({
      ...AVAIL,
      maintenance: [{
        name: 'alpine-maint', start: '2026-08-31T06:00:00',
        end: '2026-09-03T06:30:00', active: false,
      }],
      partitions: AVAIL.partitions.map((r, i) => ({
        ...r,
        slurm_start: i === 0 ? '2026-09-03T06:30:00' : r.slurm_start,
        wait_min: i === 0 ? 7080 : r.wait_min,
      })),
    }))
    const { mount, step } = setup({ fetchAvailability })
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(mount.textContent).toContain('Alpine maintenance affects scheduling'))
    expect(mount.textContent).toContain("SLURM's next available start for ah200")
    expect(mount.textContent).toContain('2026-09-03 06:30')
    step.dispose()
  })

  it('selects an available MIG slice when the whole RTX cards are unavailable', async () => {
    const migAvailability = { partitions: [{
      partition: 'artxpro6000', gpu_model: 'NVIDIA RTX Pro 6000',
      gpu_resources: [
        { gres_type: 'rtx_pro_6000', label: 'RTX Pro 6000', mig: false,
          gpus_total: 0, gpus_free: 0, speed_factor: 2.5 },
        { gres_type: 'rtx_pro_6000_2g.48gb', label: 'RTX Pro 6000 MIG 2g.48gb',
          mig: true, gpus_total: 16, gpus_free: 7, speed_factor: 1.25 },
      ],
    }] }
    const fetchAvailability = vi.fn(async () => migAvailability)
    const { mount, step } = setup({ fetchAvailability })
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(step.gresType).toBe('rtx_pro_6000_2g.48gb'))
    expect(mount.textContent).toContain('MIG')
    expect(step.payloadFields().slurm_resources).toEqual({
      gres_type: 'rtx_pro_6000_2g.48gb',
    })
    step.dispose()
  })

  it('drops the partition when the user leaves Alpine', async () => {
    const { mount, step } = setup()
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(step.partition).toBe('ah200'))
    clickTarget(mount, 'local')
    expect(step.partition).toBeNull()
    expect(step.payloadFields().partition).toBeNull()
    step.dispose()
  })
})

describe('payload + notification', () => {
  it('contributes the API fields for the chosen target', async () => {
    const { mount, step } = setup()
    expect(step.payloadFields()).toMatchObject({ execution_target: 'local', cluster_name: null })
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(step.partition).toBe('ah200'))
    expect(step.payloadFields()).toMatchObject({
      execution_target: 'alpine', cluster_name: 'alpine', partition: 'ah200',
    })
    step.dispose()
  })

  it('notifies the wizard on every change so the footer gate repaints', () => {
    const { mount, onChange, step } = setup()
    clickTarget(mount, 'alpine')
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ target: 'alpine', ready: false }))
    step.dispose()
  })
})

describe('failures', () => {
  it('survives a hardware probe that throws', async () => {
    const fetchHardware = vi.fn(async () => { throw new Error('no nvidia-smi') })
    const { mount, step } = setup({ fetchHardware })
    await vi.waitFor(() => expect(mount.textContent).toMatch(/Could not detect/))
    expect(step.isReady()).toBe(true)        // local does not depend on the probe
    step.dispose()
  })

  it('surfaces an availability failure instead of showing an empty table', async () => {
    const fetchAvailability = vi.fn(async () => { throw new Error('boom') })
    const { mount, step } = setup({ fetchAvailability })
    clickTarget(mount, 'alpine')
    connectCluster()
    await vi.waitFor(() => expect(mount.textContent).toMatch(/Could not read cluster availability/))
    expect(step.isReady()).toBe(false)
    step.dispose()
  })

  it('dispose unsubscribes from the cluster-state broadcast', async () => {
    const { mount, step, fetchAvailability } = setup()
    clickTarget(mount, 'alpine')
    step.dispose()
    connectCluster()
    expect(fetchAvailability).not.toHaveBeenCalled()
  })
})

describe('the RunPod block follows the run being designed', () => {
  const PREVIEW = {
    sized: true, connected: false, n_atoms: 100000, n_atoms_source: 'estimated',
    gpus: [{ key: 'k', label: 'RTX 4090', vram_gb: 24, usd_per_hour: 0.69, available: null,
      ns_day: 24, ns_day_relax: 12, relax_hours: 4, relax_cost: 2.76,
      production_hours: null, production_cost: null, total_hours: 4, total_cost: 2.76 }],
    storage: { output_bytes: 1, package_bytes: 0, needed_bytes: 1, used_known: false,
      staging: {}, warn: false, reason: '' },
    volume: null, balance: { available: false }, live_pods: [],
    preflight: { ok: true, checks: [] },
    budget: { budget_usd: 15, estimated_usd: 2.76, over_budget: false },
  }

  function runpodSetup(planRef) {
    const getJobPreview = vi.fn(async () => structuredClone(PREVIEW))
    const { step, mount } = setup({
      getJobPreview,
      getVolumes: vi.fn(async () => ({ volumes: [] })),
      setVolume: vi.fn(),
      getPlanShape: () => planRef.value,
    })
    return { step, mount, getJobPreview }
  }

  it('re-prices when the plan changes and the card is re-opened', async () => {
    // The failure this pins: pick RunPod, switch to Local, change the run length, switch
    // back — `refreshSizing` only touches the SELECTED target, so the RunPod card was left
    // showing a price for the old run.
    const plan = { value: { relax_steps: 100, production_steps: 0, stages: [] } }
    const { step, mount, getJobPreview } = runpodSetup(plan)

    clickTarget(mount, 'runpod')
    await vi.waitFor(() => expect(getJobPreview).toHaveBeenCalledTimes(1))

    clickTarget(mount, 'local')
    plan.value = { relax_steps: 100, production_steps: 999_999, stages: [] }
    clickTarget(mount, 'runpod')
    await vi.waitFor(() => expect(getJobPreview).toHaveBeenCalledTimes(2))
    step.dispose()
  })

  it('re-fetches live RunPod rates when the card is re-opened', async () => {
    const plan = { value: { relax_steps: 100, production_steps: 0, stages: [] } }
    const { step, mount, getJobPreview } = runpodSetup(plan)

    clickTarget(mount, 'runpod')
    await vi.waitFor(() => expect(getJobPreview).toHaveBeenCalledTimes(1))
    clickTarget(mount, 'local')
    clickTarget(mount, 'runpod')
    await vi.waitFor(() => expect(getJobPreview).toHaveBeenCalledTimes(2))
    step.dispose()
  })

  it('fetches nothing until RunPod is actually chosen', async () => {
    const plan = { value: { relax_steps: 100, production_steps: 0, stages: [] } }
    const { step, getJobPreview } = runpodSetup(plan)
    await new Promise(r => setTimeout(r, 20))
    expect(getJobPreview).not.toHaveBeenCalled()
    step.dispose()
  })

  it('carries the RunPod choices into the create payload', async () => {
    const plan = { value: { relax_steps: 100, production_steps: 0, stages: [] } }
    const { step, mount, getJobPreview } = runpodSetup(plan)
    clickTarget(mount, 'runpod')
    await vi.waitFor(() => expect(getJobPreview).toHaveBeenCalled())
    const p = step.payloadFields()
    expect(p.execution_target).toBe('runpod')
    expect(p.runpod_gpu_key).toBe('k')          // the backend's best-value row, preselected
    expect(p.runpod_budget_usd).toBe(15)
    step.dispose()
  })
})
