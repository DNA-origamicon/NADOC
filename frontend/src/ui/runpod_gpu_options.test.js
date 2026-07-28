import { describe, it, expect } from 'vitest'
import {
  formatCost,
  formatRelaxTime,
  gpuOptionView,
  gpuOptionsMessage,
  renderGpuOptionRows,
  stockBadge,
} from './runpod_gpu_options.js'

describe('formatRelaxTime', () => {
  it('minutes / hours / days by magnitude', () => {
    expect(formatRelaxTime(0.5)).toBe('30 min')
    expect(formatRelaxTime(5.4)).toBe('5.4 h')
    expect(formatRelaxTime(72)).toBe('3.0 d')
    expect(formatRelaxTime(null)).toBe('—')
    expect(formatRelaxTime(Infinity)).toBe('—')
  })
})

describe('formatCost', () => {
  it('cents under $10, whole dollars above', () => {
    expect(formatCost(5.2)).toBe('$5.20')
    expect(formatCost(21.6)).toBe('$22')
    expect(formatCost(null)).toBe('—')
  })
})

describe('stockBadge', () => {
  it('maps availability to text + colour', () => {
    expect(stockBadge(true).text).toBe('in stock')
    expect(stockBadge(false).text).toBe('out')
    expect(stockBadge(null).text).toBe('unknown')
  })
})

describe('gpuOptionsMessage', () => {
  it('prompt / busy / empty / error / indicative-note', () => {
    expect(gpuOptionsMessage(null)).toMatch(/Check RunPod GPUs/)
    expect(gpuOptionsMessage(null, { busy: true })).toMatch(/Checking/)
    expect(gpuOptionsMessage({ ok: true, gpus: [] })).toMatch(/No compatible/)
    expect(gpuOptionsMessage({ ok: false, note: 'Load a design' })).toBe('Load a design')
    expect(gpuOptionsMessage({ ok: true, gpus: [{}], note: 'indicative' })).toBe('indicative')
  })
})

describe('gpuOptionView', () => {
  const row = {
    key: 'k', label: 'RTX 4090', vram_gb: 24, usd_per_hour: 0.69, live_price: true,
    ns_day: 24, relax_hours: 19.2, est_cost: 13.2, available: true,
  }
  it('formats price / vram / time / cost', () => {
    const v = gpuOptionView(row)
    expect(v.label).toBe('RTX 4090')
    expect(v.vram).toBe('24 GB')
    expect(v.price).toBe('$0.69/hr')
    expect(v.time).toBe('19.2 h')
    expect(v.cost).toBe('$13')
    expect(v.stock.text).toBe('in stock')
  })
  it('marks an indicative (non-live) price with *', () => {
    expect(gpuOptionView({ ...row, live_price: false }).price).toBe('$0.69/hr*')
  })
})

describe('renderGpuOptionRows', () => {
  const row = {
    key: 'k', label: 'RTX 4090', vram_gb: 24, usd_per_hour: 0.69, live_price: true,
    ns_day: 24, relax_hours: 19.2, est_cost: 13.2, available: true,
  }
  it('emits a keyed, selectable row and highlights the selected one', () => {
    const html = renderGpuOptionRows([row], 'k')
    expect(html).toContain('data-key="k"')
    expect(html).toContain('runpod-gpu-row')
    expect(html).toContain('#1f6feb') // selected border colour
  })
  it('escapes label/key and returns empty for no rows', () => {
    const html = renderGpuOptionRows([{ ...row, label: '<x>', key: 'a"b' }], null)
    expect(html).toContain('&lt;x&gt;')
    expect(html).toContain('a&quot;b')
    expect(renderGpuOptionRows([], null)).toBe('')
  })
})
