import { describe, it, expect } from 'vitest'
import {
  formatCost,
  formatRelaxTime,
  gpuOptionView,
  gpuOptionsHeader,
  gpuOptionsMessage,
  jobOptionsHeader,
  jobOptionView,
  renderGpuOptionRows,
  renderJobOptionRows,
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

// ── the Job Wizard's whole-plan table ────────────────────────────────────────────
const JOB_ROW = {
  key: 'NVIDIA GeForce RTX 4090', label: 'RTX 4090', vram_gb: 24, usd_per_hour: 0.69,
  live_price: true, available: true, ns_day: 24.0, ns_day_relax: 12.0,
  relax_hours: 4.0, relax_cost: 2.76, production_hours: 5.0, production_cost: 3.45,
  total_hours: 9.0, total_cost: 6.21,
}

describe('jobOptionView', () => {
  it('carries relaxation, production and the total separately', () => {
    const v = jobOptionView(JOB_ROW)
    expect(v.time).toBe('4.0 h')
    expect(v.relaxCost).toBe('$2.76')
    expect(v.production).toBe('5.0 h')
    expect(v.productionCost).toBe('$3.45')
    expect(v.total).toBe('9.0 h')
    expect(v.totalCost).toBe('$6.21')
  })

  it('quotes the relaxation rate as well as the production one', () => {
    // The ladder runs at a slower timestep, so one ns/day number would misdescribe half the run.
    expect(jobOptionView(JOB_ROW).nsdayRelax).toMatch(/12 ns\/day relaxing/)
  })

  it('flags a card whose total exceeds the cap', () => {
    expect(jobOptionView(JOB_ROW, { budgetUsd: 5 }).overBudget).toBe(true)
    expect(jobOptionView(JOB_ROW, { budgetUsd: 20 }).overBudget).toBe(false)
    expect(jobOptionView(JOB_ROW).overBudget).toBe(false)   // no cap => no claim
  })
})

describe('renderJobOptionRows', () => {
  it('uses exactly the same fixed grid tracks as its header', () => {
    const header = jobOptionsHeader()
    const row = renderJobOptionRows([JOB_ROW], null)
    const columns = /grid-template-columns:([^;]+)/.exec(header)?.[1]
    expect(columns).toBeTruthy()
    expect(/grid-template-columns:([^;]+)/.exec(row)?.[1]).toBe(columns)
    expect(columns).not.toContain('auto')
  })

  it('keeps the selectable-row contract the click wiring depends on', () => {
    const html = renderJobOptionRows([JOB_ROW], null)
    expect(html).toContain('class="runpod-gpu-row"')
    expect(html).toContain('data-key="NVIDIA GeForce RTX 4090"')
    expect(html).toContain('role="button"')
    expect(html).toContain('tabindex="0"')
  })

  it('badges only the first row as best value', () => {
    const html = renderJobOptionRows([JOB_ROW, { ...JOB_ROW, key: 'b', label: 'L40S' }], null)
    expect(html.match(/best value/g)).toHaveLength(1)
  })

  it('leaves an over-budget row selectable — raising the cap is a valid answer', () => {
    const html = renderJobOptionRows([JOB_ROW], null, { budgetUsd: 1 })
    expect(html).toContain('runpod-gpu-row')
    expect(html).toMatch(/over your cap/)
  })

  it('renders nothing for an empty list', () => {
    expect(renderJobOptionRows([], null)).toBe('')
  })

  it('keeps an insufficient GPU visible, red, and explains why it cannot be selected', () => {
    const bad = { ...JOB_ROW, eligible: false,
      insufficient_reason: 'needs about 40.0 GB VRAM; only 20.4 GB is usable' }
    const html = renderJobOptionRows([bad], null)
    expect(html).toContain('data-eligible="false"')
    expect(html).toContain('rgba(248,81,73')
    expect(html).toContain('⚠ needs about 40.0 GB VRAM')
    expect(html).toContain('tabindex="-1"')
  })
})

describe('the Clusters card is untouched', () => {
  it('still renders its original four-column header', () => {
    // The wizard's six-column table is a SEPARATE renderer. If this ever picks up the
    // production columns, the Clusters card silently changed shape.
    const h = gpuOptionsHeader()
    expect(h).toContain('<span>relax</span>')
    expect(h).not.toContain('<span>production</span>')
    expect(h).not.toContain('<span>total</span>')
  })

  it('still renders its original rows, with no best-value badge', () => {
    const html = renderGpuOptionRows([{ ...JOB_ROW, relax_hours: 4.0, est_cost: 2.76 }], null)
    expect(html).toContain('runpod-gpu-row')
    expect(html).not.toMatch(/best value/)
  })
})
