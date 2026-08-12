// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initWizardRunpod } from './md_job_wizard_runpod.js'
import { runpodPlanShape } from './md_job_wizard_runpod_model.js'

const ROW = {
  key: 'NVIDIA GeForce RTX 4090', label: 'RTX 4090', sm: 'sm_89', vram_gb: 24,
  usd_per_hour: 0.69, live_price: true, available: true,
  ns_day: 24.0, ns_day_relax: 12.0,
  relax_hours: 4.0, relax_cost: 2.76,
  production_hours: 5.0, production_cost: 3.45,
  total_hours: 9.0, total_cost: 6.21,
}
// Better $/ns but glacially slow — the backend ranks it BELOW the 4090 and the client must
// never reorder it to the top (the A6000 trap: a fallback 4x worse in value).
const SLOW_BUT_CHEAP = {
  ...ROW, key: 'NVIDIA L4', label: 'L4', usd_per_hour: 0.39,
  ns_day: 2.6, ns_day_relax: 1.3,
  relax_hours: 40.0, relax_cost: 15.6, production_hours: 46.0, production_cost: 17.9,
  total_hours: 86.0, total_cost: 33.5,
}
const TOO_SMALL = {
  ...ROW, key: 'small', label: 'RTX 3090', vram_gb: 24, eligible: false,
  insufficient_reason: 'needs about 40.0 GB VRAM; only 20.4 GB is usable',
}

const PREVIEW = {
  sized: true, connected: true, n_atoms: 1_310_154, n_atoms_source: 'estimated',
  gpus: [ROW, SLOW_BUT_CHEAP],
  storage: {
    output_bytes: 5 * 1024 ** 3, package_bytes: 1024 ** 3, needed_bytes: 6 * 1024 ** 3,
    volume_size_gb: 50, used_known: false, free_bytes: 50 * 1024 ** 3,
    free_after_bytes: 44 * 1024 ** 3,
    staging: { bytes: 1024 ** 3, minutes: 13.2, usd: 0.18 }, warn: false, reason: '',
  },
  volume: { id: 'vol1', name: 'nadoc', size_gb: 50, data_center_id: 'EU-RO-1' },
  balance: { available: true, balance: 100 },
  live_pods: [],
  preflight: { ok: true, checks: [], gpus: [], note: '' },
  budget: { budget_usd: 15, estimated_usd: 6.39, over_budget: false },
  note: null,
}

const PLAN = {
  stages: [
    { role: 'ladder', steps: 240_000, ns: 0.96, params: { dcdfreq: 5000 } },
    { role: 'production', steps: 1_250_000, ns: 5.0, params: { dcdfreq: 2500 } },
  ],
}

function setup({ preview = PREVIEW, plan = PLAN, readOnly = false, recorded = null } = {}) {
  const mount = document.createElement('div')
  document.body.appendChild(mount)
  const getJobPreview = vi.fn().mockResolvedValue(structuredClone(preview))
  const getVolumes = vi.fn().mockResolvedValue({ volumes: [preview.volume] })
  const setVolume = vi.fn().mockResolvedValue({ ok: true })
  const onChange = vi.fn()
  let _plan = plan
  const block = initWizardRunpod({
    mount,
    getJobPreview,
    getVolumes,
    setVolume,
    getPlanShape: () => runpodPlanShape(_plan),
    onChange,
    readOnly: () => readOnly,
    getRecorded: () => recorded,
    setup: vi.fn(),                      // the RunPod setup modal is its own tested factory
  })
  return {
    mount, block, getJobPreview, getVolumes, setVolume, onChange,
    setPlan: p => { _plan = p },
  }
}

const rows = mount => [...mount.querySelectorAll('.runpod-gpu-row')]

beforeEach(() => { document.body.innerHTML = '' })

describe('reactivity — the whole point of the card', () => {
  it('prices the run once and does not re-ask for an unchanged plan', async () => {
    const { block, getJobPreview } = setup()
    await block.refresh()
    await block.refresh()
    expect(getJobPreview).toHaveBeenCalledTimes(1)
  })

  it('re-prices when the production length changes on a later tab', async () => {
    const { block, getJobPreview, setPlan } = setup()
    await block.refresh()
    setPlan({
      stages: [
        { role: 'ladder', steps: 240_000, ns: 0.96, params: { dcdfreq: 5000 } },
        { role: 'production', steps: 12_500_000, ns: 50.0, params: { dcdfreq: 2500 } },
      ],
    })
    await block.refresh()
    expect(getJobPreview).toHaveBeenCalledTimes(2)
    expect(getJobPreview.mock.calls[1][0].production_ns).toBeCloseTo(50, 3)
  })

  it('re-prices when the trajectory cadence changes — that moves BYTES', async () => {
    const { block, getJobPreview, setPlan } = setup()
    await block.refresh()
    setPlan({
      stages: [
        { role: 'ladder', steps: 240_000, ns: 0.96, params: { dcdfreq: 5000 } },
        { role: 'production', steps: 1_250_000, ns: 5.0, params: { dcdfreq: 250 } },
      ],
    })
    await block.refresh()
    expect(getJobPreview).toHaveBeenCalledTimes(2)
  })

  it('always re-asks on an explicit re-check', async () => {
    const { block, getJobPreview } = setup()
    await block.refresh()
    await block.refresh({ force: true })
    expect(getJobPreview).toHaveBeenCalledTimes(2)
  })

  it('sends the whole plan, split into its two phases', async () => {
    const { block, getJobPreview } = setup()
    await block.refresh()
    const body = getJobPreview.mock.calls[0][0]
    expect(body.relax_ns).toBeCloseTo(0.96, 3)
    expect(body.production_ns).toBeCloseTo(5.0, 3)
    expect(body.stages).toHaveLength(2)
    expect(body.budget_usd).toBe(15)
  })
})

describe('picking a card', () => {
  it('preselects the backend’s best-value row', async () => {
    const { block } = setup()
    await block.refresh()
    expect(block.gpuKey()).toBe(ROW.key)
  })

  it('renders the backend’s order and never re-sorts a cheap-slow card to the top', async () => {
    // The L4 has the better $/ns of the two but does 2.6 ns/day — a 5 ns run takes 46 h.
    // Sorting on cost alone here is exactly the failure the two-axis rule exists to prevent.
    const { mount, block } = setup()
    await block.refresh()
    const order = rows(mount).map(r => r.dataset.key)
    expect(order).toEqual([ROW.key, SLOW_BUT_CHEAP.key])
    expect(rows(mount)[0].textContent).toMatch(/best value/)
  })

  it('selects on click without another round trip', async () => {
    const { mount, block, getJobPreview, onChange } = setup()
    await block.refresh()
    onChange.mockClear()
    rows(mount)[1].click()
    expect(block.gpuKey()).toBe(SLOW_BUT_CHEAP.key)
    expect(onChange).toHaveBeenCalled()
    expect(getJobPreview).toHaveBeenCalledTimes(1)
  })

  it('shows an insufficient card but cannot select it', async () => {
    const { mount, block } = setup({ preview: { ...PREVIEW, gpus: [ROW, TOO_SMALL] } })
    await block.refresh()
    const bad = rows(mount)[1]
    expect(bad.textContent).toMatch(/needs about 40.0 GB VRAM/)
    bad.click()
    expect(block.gpuKey()).toBe(ROW.key)
  })

  it('shows both value axes for every card', async () => {
    const { mount, block } = setup()
    await block.refresh()
    const text = rows(mount)[0].textContent
    expect(text).toMatch(/ns\/day/)
    expect(text).toMatch(/\$0\.69\/hr/)
  })
})

describe('the spend cap', () => {
  it('re-gates locally when the cap is typed, with no round trip', async () => {
    const { mount, block, getJobPreview } = setup()
    await block.refresh()
    expect(block.isReady()).toBe(true)

    const input = mount.querySelector('#wiz-runpod-budget')
    input.value = '2'
    input.dispatchEvent(new Event('input'))

    expect(block.budgetUsd()).toBe(2)
    expect(block.isReady()).toBe(false)
    expect(block.readiness().reason).toMatch(/Raise the cap or shorten the run/)
    expect(getJobPreview).toHaveBeenCalledTimes(1)
  })

  it('unblocks again when the cap is raised', async () => {
    const { mount, block } = setup()
    await block.refresh()
    const input = mount.querySelector('#wiz-runpod-budget')
    input.value = '2'
    input.dispatchEvent(new Event('input'))
    input.value = '50'
    input.dispatchEvent(new Event('input'))
    expect(block.isReady()).toBe(true)
  })

  it('says the cap is per-pod, not per-job', async () => {
    const { mount, block } = setup()
    await block.refresh()
    expect(mount.textContent).toMatch(/caps ONE pod/)
  })

  it('warns loudly when a pod is already billing', async () => {
    const { mount, block } = setup({
      preview: { ...PREVIEW, live_pods: [{ id: 'p1', status: 'RUNNING', cost_per_hr: 0.69 }] },
    })
    await block.refresh()
    expect(mount.textContent).toMatch(/1 pod already billing/)
    // A warning, not a gate — a second concurrent run is legitimate.
    expect(block.isReady()).toBe(true)
  })
})

describe('storage', () => {
  it('shows what the run writes against the volume', async () => {
    const { mount, block } = setup()
    await block.refresh()
    expect(mount.textContent).toMatch(/Trajectories \+ restarts/)
    expect(mount.textContent).toMatch(/Network volume/)
    expect(mount.textContent).toMatch(/13.2 min/)     // the billed staging upload
  })

  it('surfaces an overflowing volume as a warning', async () => {
    const { mount, block } = setup({
      preview: {
        ...PREVIEW,
        storage: { ...PREVIEW.storage, warn: true, reason: 'This run needs about 80.0 GB' },
      },
    })
    await block.refresh()
    expect(mount.textContent).toMatch(/This run needs about 80.0 GB/)
  })

  it('writes a volume pick through to the session, then re-prices', async () => {
    // The pre-flight's volume check reads the SESSION, so a pick that only lived in this
    // closure would leave the gate red with nothing to click.
    const { mount, block, setVolume, getJobPreview } = setup()
    await block.refresh()
    await block.activate()
    const sel = mount.querySelector('#wiz-runpod-volume')
    expect(sel).toBeTruthy()
    sel.value = 'vol1'
    sel.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(setVolume).toHaveBeenCalledWith('vol1'))
    await vi.waitFor(() => expect(getJobPreview.mock.calls.length).toBeGreaterThan(1))
  })
})

describe('the gate', () => {
  it('blocks while no volume has been chosen', async () => {
    const { block } = setup({ preview: { ...PREVIEW, volume: null } })
    await block.refresh()
    expect(block.isReady()).toBe(false)
    expect(block.readiness().reason).toMatch(/network volume/)
  })

  it('reports the pre-flight’s own failure rather than a generic one', async () => {
    const { block } = setup({
      preview: {
        ...PREVIEW,
        preflight: { ok: false, checks: [
          { key: 'ssh_key', ok: false, label: 'SSH key', detail: 'not registered' }] },
      },
    })
    await block.refresh()
    expect(block.readiness().reason).toMatch(/SSH key: not registered/)
  })

  it('blocks when the balance cannot cover the run', async () => {
    const { block } = setup({ preview: { ...PREVIEW, balance: { available: true, balance: 1 } } })
    await block.refresh()
    expect(block.readiness().reason).toMatch(/destroys every pod at \$0/)
  })
})

describe('failures degrade instead of crashing', () => {
  it('shows a message when the preview cannot be fetched', async () => {
    const mount = document.createElement('div')
    const block = initWizardRunpod({
      mount,
      getJobPreview: vi.fn().mockRejectedValue(new Error('backend down')),
      getPlanShape: () => runpodPlanShape(PLAN),
      setup: vi.fn(),
    })
    await block.refresh()
    expect(mount.textContent).toMatch(/Could not price this run/)
    expect(block.isReady()).toBe(false)
  })

  it('reports an unsizable design without inventing a cost', async () => {
    const { mount, block } = setup({
      preview: { sized: false, connected: false, reason: 'No design loaded' },
    })
    await block.refresh()
    expect(mount.textContent).toMatch(/No design loaded/)
    expect(block.isReady()).toBe(false)
  })
})

describe('read-only — an existing job', () => {
  const recorded = {
    gpuKey: 'NVIDIA GeForce RTX 4090', budgetUsd: 15, volumeId: 'vol1', podId: 'pod-abc',
  }

  it('never re-prices a run that already happened', async () => {
    const { block, getJobPreview } = setup({ readOnly: true, recorded })
    await block.refresh()
    expect(getJobPreview).not.toHaveBeenCalled()
  })

  it('shows what the job was actually set up to rent', async () => {
    const { mount, block } = setup({ readOnly: true, recorded })
    block.render()
    expect(mount.textContent).toMatch(/NVIDIA GeForce RTX 4090/)
    expect(mount.textContent).toMatch(/\$15/)
    expect(mount.textContent).toMatch(/pod-abc/)
    expect(mount.textContent).toMatch(/not recalculated here/)
  })

  it('offers no controls to change a finished job', async () => {
    const { mount, block } = setup({ readOnly: true, recorded })
    block.render()
    expect(mount.querySelector('#wiz-runpod-budget')).toBeNull()
    expect(mount.querySelector('#wiz-runpod-volume')).toBeNull()
    expect(rows(mount)).toHaveLength(0)
  })
})
