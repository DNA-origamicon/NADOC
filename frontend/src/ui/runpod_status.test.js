import { describe, expect, it, vi } from 'vitest'
import {
  initRunpodStatus,
  podBillingSummary,
  renderPodRows,
  renderPreflightRows,
  renderRunpodJobCost,
  runpodBlockReason,
  runpodCanLaunch,
  runpodChipState,
  runpodGpuSummary,
  runpodJobCostView,
} from './runpod_status.js'

const check = (key, ok, label, detail = '') => ({ key, ok, label, detail })

const GREEN = {
  ok: true,
  checks: [
    check('api_key', true, 'RunPod API key', 'connected'),
    check('volume', true, 'Network volume', '77pnhye88p'),
    check('ssh_key', true, 'SSH key', '~/.ssh/id_ed25519 found'),
    check('namd_arch', true, 'NAMD build matches GPUs', 'binary is sm_89'),
    check('gpu_stock', true, 'GPU availability', 'RTX 4090 (Low)'),
  ],
  gpus: [
    { label: 'RTX 4090', stock: 'Low', usd_per_hour: 0.34, available: true },
    { label: 'RTX 6000 Ada', stock: null, usd_per_hour: 0.74, available: false },
  ],
  note: 'Stock is RunPod’s GLOBAL figure…',
}

const DISCONNECTED = {
  ok: false,
  checks: [
    check('api_key', false, 'RunPod API key', 'not connected — enter your API key'),
    check('volume', false, 'Network volume', 'none set'),
  ],
  gpus: [],
  note: '',
}

const NO_GPU = {
  ok: false,
  checks: [
    check('api_key', true, 'RunPod API key', 'connected'),
    check('gpu_stock', false, 'GPU availability', 'no allowed card in stock'),
  ],
  gpus: [],
  note: '',
}

describe('runpodChipState', () => {
  it('reports disconnected when the API key check fails', () => {
    expect(runpodChipState(DISCONNECTED)).toEqual({
      state: 'disconnected',
      label: 'runpod: disconnected',
    })
  })

  it('reports "not ready" when connected but a check fails', () => {
    // Connected is NOT the same as launchable — the card can be out of stock.
    expect(runpodChipState(NO_GPU).state).toBe('warn')
    expect(runpodChipState(NO_GPU).label).toBe('runpod: not ready')
  })

  it('reports ready only when everything passes', () => {
    expect(runpodChipState(GREEN)).toEqual({ state: 'connected', label: 'runpod: ready' })
  })

  it('has a defined state before any pre-flight has run', () => {
    expect(runpodChipState(null).state).toBe('unknown')
  })
})

describe('runpodCanLaunch — the gate on renting a GPU', () => {
  it('blocks until every check is green', () => {
    // A pod bills from creation. Launching into a known-failing pre-flight rents a GPU
    // that CANNOT run the job — that is money for nothing.
    expect(runpodCanLaunch(GREEN)).toBe(true)
    expect(runpodCanLaunch(NO_GPU)).toBe(false)
    expect(runpodCanLaunch(DISCONNECTED)).toBe(false)
    expect(runpodCanLaunch(null)).toBe(false)
  })

  it('blocks before pre-flight has even run', () => {
    expect(runpodCanLaunch(undefined)).toBe(false)
  })
})

describe('runpodBlockReason', () => {
  it('names every failing check so the user is not left guessing', () => {
    const why = runpodBlockReason(DISCONNECTED)
    expect(why).toContain('RunPod API key')
    expect(why).toContain('Network volume')
  })

  it('is empty when everything passes', () => {
    expect(runpodBlockReason(GREEN)).toBe('')
  })

  it('never leaves the tooltip blank when nothing has run', () => {
    expect(runpodBlockReason(null)).toMatch(/pre-flight/i)
  })
})

describe('runpodGpuSummary', () => {
  it('shows stock and price per card, and marks the ones with none', () => {
    const s = runpodGpuSummary(GREEN)
    expect(s).toContain('RTX 4090 (Low) $0.34/hr')
    expect(s).toContain('RTX 6000 Ada (none) $0.74/hr')
  })

  it('is empty when there is nothing to say', () => {
    expect(runpodGpuSummary(NO_GPU)).toBe('')
  })
})

describe('renderPreflightRows', () => {
  it('marks failures in red and passes in green', () => {
    const html = renderPreflightRows(DISCONNECTED)
    expect(html).toContain('#f85149') // red
    expect(html).toContain('RunPod API key')
    expect(renderPreflightRows(GREEN)).toContain('#3fb950') // green
  })

  it('does not blow up with no pre-flight', () => {
    expect(renderPreflightRows(null)).toContain('No pre-flight')
  })
})

// ── the leak check ───────────────────────────────────────────────────────────────
//
// `GET /runpod/pods` documented itself as the place a lost pod id surfaces, and said the
// UI showed it with a terminate button. Nothing in the frontend called it, so the wizard's
// "N pods already billing" warning pointed at a card with no list and no kill switch.

describe('podBillingSummary', () => {
  it('null when nothing is billing', () => {
    expect(podBillingSummary([])).toBe(null)
    expect(podBillingSummary(null)).toBe(null)
    expect(podBillingSummary([{ cost_per_hr: 2 }])).toBe(null)   // no id → not a real pod
  })
  it('counts pods and totals the hourly rate', () => {
    const s = podBillingSummary([
      { id: 'a', cost_per_hr: 0.34 }, { id: 'b', cost_per_hr: 2.39 },
    ])
    expect(s).toMatchObject({ count: 2, usdPerHour: 2.73 })
    expect(s.text).toBe('2 pods billing · $2.73/hr')
  })
  it('singular, and copes with an unpriced pod', () => {
    expect(podBillingSummary([{ id: 'a' }]).text).toBe('1 pod billing')
  })
})

describe('renderPodRows', () => {
  it('one row per pod, each with its id and a Terminate button', () => {
    const html = renderPodRows([{ id: 'hpp8jm3bzy9z13', status: 'RUNNING', cost_per_hr: 0.34 }])
    expect(html).toContain('hpp8jm3bzy9z13')
    expect(html).toContain('RUNNING')
    expect(html).toContain('$0.34/hr')
    expect(html).toContain('data-terminate="hpp8jm3bzy9z13"')
  })
  it('empty for no pods', () => {
    expect(renderPodRows([])).toBe('')
    expect(renderPodRows(null)).toBe('')
  })
})

describe('selected RunPod job cost', () => {
  const running = {
    job_id: 'j1', execution_target: 'runpod', status: 'running', runpod_pod_id: 'pod1',
    runpod_estimated_cost_usd: 8.75,
    runpod_billing_sessions: [{ pod_id: 'pod1', started_at: 1000, usd_per_hour: 0.72 }],
  }

  it('shows balance, estimate, actual rented rate and accrued spend while active', () => {
    const view = runpodJobCostView(running, {
      balance: { available: true, balance: 42.5 },
      pods: [{ id: 'pod1', cost_per_hr: 0.74 }], nowMs: 4_601_000,
    })
    expect(view.rows).toEqual([
      ['Current balance', '$42.50'],
      ['Estimated total cost', '$8.75'],
      ['Rented GPU rate', '$0.74/hr'],
      ['Spent on this job', '$0.72'],
    ])
  })

  it('clears for deselection/non-RunPod and reduces completed jobs to final cost', () => {
    expect(runpodJobCostView(null)).toBeNull()
    expect(runpodJobCostView({ execution_target: 'local' })).toBeNull()
    const done = runpodJobCostView({
      ...running, status: 'completed', runpod_final_cost_usd: 6.21,
    })
    expect(done).toEqual({ completed: true, rows: [['Actual final cost', '$6.21']] })
    const html = renderRunpodJobCost({ ...running, status: 'completed', runpod_final_cost_usd: 6.21 })
    expect(html).toContain('Actual final cost')
    expect(html).not.toContain('Current balance')
  })

  it('does not misreport missing money fields as zero', () => {
    const view = runpodJobCostView({ execution_target: 'runpod', status: 'queued' })
    expect(view.rows).toContainEqual(['Estimated total cost', '—'])
    expect(view.rows).toContainEqual(['Rented GPU rate', 'Not rented'])
  })
})

describe('initRunpodStatus — live pods and terminate', () => {
  const mount = () => document.createElement('div')
  const POD = { id: 'pod1', status: 'RUNNING', cost_per_hr: 0.34 }

  /** Routes by URL: the pre-flight POST and the pods GET are different endpoints. */
  const routed = (pods = [POD]) => vi.fn(async (url) => {
    if (String(url).includes('/pods')) {
      return { ok: true, json: async () => ({ pods }) }
    }
    return { ok: true, json: async () => GREEN }
  })

  it('lists a billing pod after a refresh, with its rate and a Terminate button', async () => {
    const el = mount()
    const panel = initRunpodStatus({ mount: el, fetchImpl: routed() })
    await panel.refresh()
    expect(panel.billing()).toMatchObject({ count: 1, usdPerHour: 0.34 })
    expect(el.innerHTML).toContain('1 pod billing')
    expect(el.innerHTML).toContain('spending money right now')
    expect(el.querySelector('[data-terminate="pod1"]')).toBeTruthy()
  })

  it('shows nothing when no pod is up', async () => {
    const el = mount()
    const panel = initRunpodStatus({ mount: el, fetchImpl: routed([]) })
    await panel.refresh()
    expect(panel.billing()).toBe(null)
    expect(el.innerHTML).not.toContain('billing')
  })

  it('does not ask for pods with no session — that 400s, and the commit gate is zero console errors', async () => {
    const fetchImpl = vi.fn(async (url) => {
      if (String(url).includes('/pods')) return { ok: true, json: async () => ({ pods: [POD] }) }
      return { ok: true, json: async () => DISCONNECTED }   // api_key check fails
    })
    const panel = initRunpodStatus({ mount: mount(), fetchImpl })
    await panel.refresh()
    expect(fetchImpl.mock.calls.some(c => String(c[0]).includes('/pods'))).toBe(false)
    expect(panel.billing()).toBe(null)
  })

  it('a pods call that fails leaves the pre-flight intact — a blank leak check beats a crash', async () => {
    const fetchImpl = vi.fn(async (url) => {
      if (String(url).includes('/pods')) throw new Error('not connected')
      return { ok: true, json: async () => GREEN }
    })
    const panel = initRunpodStatus({ mount: mount(), fetchImpl })
    await panel.refresh()
    expect(panel.canLaunch()).toBe(true)
    expect(panel.billing()).toBe(null)
  })

  it('Terminate asks first, and does nothing when declined', async () => {
    const fetchImpl = routed()
    const panel = initRunpodStatus({
      mount: mount(), fetchImpl, confirmImpl: async () => false })
    await panel.refresh()
    await panel.terminate('pod1')
    expect(fetchImpl.mock.calls.some(c => String(c[0]).includes('/terminate'))).toBe(false)
  })

  it('Terminate POSTs to the pod, then re-reads the list', async () => {
    let pods = [POD]
    const fetchImpl = vi.fn(async (url, opts) => {
      const u = String(url)
      if (u.includes('/terminate')) { pods = []; return { ok: true, json: async () => ({ ok: true }) } }
      if (u.includes('/pods')) return { ok: true, json: async () => ({ pods }) }
      return { ok: true, json: async () => GREEN }
    })
    const el = mount()
    const panel = initRunpodStatus({ mount: el, fetchImpl, confirmImpl: async () => true })
    await panel.refresh()
    await panel.terminate('pod1')

    const kill = fetchImpl.mock.calls.find(c => String(c[0]).includes('/terminate'))
    expect(kill[0]).toBe('/api/runpod/pods/pod1/terminate')
    expect(kill[1]).toMatchObject({ method: 'POST' })
    expect(panel.billing()).toBe(null)          // list re-read, pod gone
    expect(el.innerHTML).not.toContain('data-terminate')
  })

  it('the confirmation names the rate and says finished steps survive on the volume', async () => {
    const seen = []
    const panel = initRunpodStatus({
      mount: mount(), fetchImpl: routed(),
      confirmImpl: async (m) => { seen.push(m); return false } })
    await panel.refresh()
    await panel.terminate('pod1')
    expect(seen[0]).toContain('pod1')
    expect(seen[0]).toContain('$0.34/hr')
    expect(seen[0]).toMatch(/network volume/)
  })
})

describe('initRunpodStatus', () => {
  const mount = () => document.createElement('div')

  it('renders the checks and reports canLaunch', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ json: async () => GREEN })
    const el = mount()
    const panel = initRunpodStatus({ mount: el, fetchImpl })

    await panel.refresh()

    expect(fetchImpl).toHaveBeenCalledWith('/api/runpod/preflight', expect.objectContaining({
      method: 'POST',
    }))
    expect(panel.canLaunch()).toBe(true)
    expect(el.innerHTML).toContain('runpod: ready')
    expect(el.innerHTML).toContain('RTX 4090')
  })

  it('passes the atom count so the sizing check can run', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ json: async () => GREEN })
    const panel = initRunpodStatus({ mount: mount(), fetchImpl })
    await panel.refresh(5_656_632)
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ n_atoms: 5_656_632 })
  })

  it('a network failure is a FAILED pre-flight, not an exception', async () => {
    // If this threw, the Run button would keep whatever state it had — which could be
    // ENABLED, and the user would rent a GPU against an unknown backend.
    const fetchImpl = vi.fn().mockRejectedValue(new Error('offline'))
    const panel = initRunpodStatus({ mount: mount(), fetchImpl })

    await expect(panel.refresh()).resolves.toBeTruthy()
    expect(panel.canLaunch()).toBe(false)
    expect(panel.blockReason()).toContain('backend unreachable')
  })

  it('notifies onChange so the Run button can be repainted', async () => {
    const onChange = vi.fn()
    const panel = initRunpodStatus({
      mount: mount(),
      fetchImpl: vi.fn().mockResolvedValue({ json: async () => GREEN }),
      onChange,
    })
    await panel.refresh()
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ ok: true }))
  })
})
