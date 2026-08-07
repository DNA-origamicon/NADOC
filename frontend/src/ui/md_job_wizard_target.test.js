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

  it('runpod is selectable but never ready — it is not wired up', () => {
    const { mount, step } = setup()
    clickTarget(mount, 'runpod')
    expect(step.isReady()).toBe(false)
    expect(step.readiness().reason).toMatch(/Clusters card/)
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
