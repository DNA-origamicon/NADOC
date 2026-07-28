import { afterEach, describe, expect, it, vi } from 'vitest'

// The picker imports getRunpodGpuOptions from client.js; tests inject fetchOptions so the real
// client is never called — but mock the module so client.js's heavy deps don't load.
vi.mock('../api/client.js', () => ({ getRunpodGpuOptions: vi.fn() }))

import { initRunpodGpuPicker } from './runpod_gpu_picker.js'

const RESP = {
  ok: true, n_atoms: 1_000_000, relax_ns: 19.2,
  gpus: [
    { key: 'a', label: 'RTX 4090', vram_gb: 24, usd_per_hour: 0.69, live_price: true,
      ns_day: 24, relax_hours: 19.2, est_cost: 13, available: true },
    { key: 'b', label: 'H100 SXM', vram_gb: 80, usd_per_hour: 2.99, live_price: true,
      ns_day: 40, relax_hours: 11.5, est_cost: 34, available: true },
  ],
  note: '',
}

function mount() {
  const el = document.createElement('div')
  document.body.appendChild(el)
  return el
}
afterEach(() => { document.body.innerHTML = '' })

describe('initRunpodGpuPicker', () => {
  it('renders the button and a prompt before any check', () => {
    const el = mount()
    initRunpodGpuPicker({ mount: el, fetchOptions: vi.fn() })
    expect(el.querySelector('#runpod-check-gpus-btn')).toBeTruthy()
    expect(el.textContent).toMatch(/Check RunPod GPUs/)
    expect(el.querySelectorAll('.runpod-gpu-row').length).toBe(0)
  })

  it('clicking Check fetches and lists GPUs with price, time, and cost', async () => {
    const el = mount()
    const fetchOptions = vi.fn().mockResolvedValue(RESP)
    const p = initRunpodGpuPicker({ mount: el, fetchOptions })
    await p.check()
    expect(fetchOptions).toHaveBeenCalledTimes(1)
    expect(el.querySelectorAll('.runpod-gpu-row').length).toBe(2)
    expect(el.textContent).toContain('RTX 4090')
    expect(el.textContent).toContain('$0.69/hr')
    expect(el.textContent).toContain('19.2 h')
    expect(el.textContent).toContain('$13')
  })

  it('the button element actually triggers a fetch on click', async () => {
    const el = mount()
    const fetchOptions = vi.fn().mockResolvedValue(RESP)
    initRunpodGpuPicker({ mount: el, fetchOptions })
    el.querySelector('#runpod-check-gpus-btn').click()
    await Promise.resolve(); await Promise.resolve()
    expect(fetchOptions).toHaveBeenCalled()
  })

  it('selecting a row highlights it and reports it via onSelect', async () => {
    const el = mount()
    const onSelect = vi.fn()
    const p = initRunpodGpuPicker({ mount: el, fetchOptions: vi.fn().mockResolvedValue(RESP), onSelect })
    await p.check()
    el.querySelector('.runpod-gpu-row[data-key="b"]').click()
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ key: 'b', label: 'H100 SXM' }))
    expect(p.selected).toBe('b')
    // still rendered after selection (re-render didn't drop the rows)
    expect(el.querySelectorAll('.runpod-gpu-row').length).toBe(2)
  })

  it('a fetch failure renders a message instead of throwing', async () => {
    const el = mount()
    const p = initRunpodGpuPicker({ mount: el, fetchOptions: vi.fn().mockRejectedValue(new Error('down')) })
    await expect(p.check()).resolves.toBeTruthy()
    expect(el.textContent).toMatch(/unreachable/i)
  })

  it('clear() drops the results and selection', async () => {
    const el = mount()
    const p = initRunpodGpuPicker({ mount: el, fetchOptions: vi.fn().mockResolvedValue(RESP) })
    await p.check()
    p.clear()
    expect(p.options).toBe(null)
    expect(p.selected).toBe(null)
    expect(el.querySelectorAll('.runpod-gpu-row').length).toBe(0)
  })
})
