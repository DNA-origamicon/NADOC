import { describe, expect, it, vi } from 'vitest'
import {
  initRunpodStatus,
  renderPreflightRows,
  runpodBlockReason,
  runpodCanLaunch,
  runpodChipState,
  runpodGpuSummary,
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
