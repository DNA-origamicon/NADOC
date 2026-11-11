// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { comparisonRows, initRuntimeComparison, quoteSummary } from './md_runtime_comparison.js'
import { selectedBudget } from './md_job_wizard_runpod_model.js'

const quote = { available: true, target: 'runpod', known_hours: 10, low_hours: 8, high_hours: 15,
  billed_hours: 9, cost: 5, low_cost: 4, high_cost: 8, cost_unit: 'USD', transfer_mode: 's3',
  unknown: ['GPU capacity wait before rental'], components: [] }

describe('runtime comparison', () => {
  it('shows unknown wait and keeps SU distinct from dollars', () => {
    expect(quoteSummary(quote).duration).toContain('+ gpu capacity wait')
    const q = quoteSummary({ ...quote, target: 'alpine', cost_unit: 'SU', submissions: 3 })
    expect(q.cost).toContain('SU')
    expect(q.cost).not.toContain('$')
    expect(q.note).toContain('3 submission')
  })
  it('uses the selected eligible GPU and its full bill for the budget', () => {
    const preview = { sized: true, runpod: [{ key: 'a', label: 'A', completion: quote },
      { key: 'b', label: 'B', completion: { ...quote, cost: 10, high_cost: 16 } }] }
    expect(comparisonRows(preview, 'b')[2].cost).toContain('$10')
    const budget = selectedBudget({ gpus: preview.runpod, storage: { staging: { minutes: 60, usd: 1 } } }, 'b', 15)
    expect(budget.estimated_usd).toBe(16) // transfer already included exactly once
    expect(budget.over_budget).toBe(true)
  })
  it('ignores a stale quote after a changed plan', async () => {
    let first, second
    const fetchPreview = vi.fn().mockImplementationOnce(() => new Promise(r => { first = r }))
      .mockImplementationOnce(() => new Promise(r => { second = r }))
    let steps = 100
    const mount = document.createElement('div')
    const ui = initRuntimeComparison({ mount, fetchPreview, getShape: () => ({ stages: [{ steps }] }) })
    const a = ui.refresh(); steps = 200; const b = ui.refresh()
    second({ sized: false, reason: 'new quote' }); await b
    first({ sized: false, reason: 'stale quote' }); await a
    expect(mount.textContent).toContain('new quote')
    expect(mount.textContent).not.toContain('stale quote')
    ui.dispose()
  })
  it('does not label unknown pricing as a free remote job', () => {
    expect(quoteSummary({ ...quote, cost: null }).cost).toBe('Unknown rate')
    expect(quoteSummary({ available: false, reason: 'unsupported hardware' }).note).toContain('unsupported')
  })
  it('shares edited transfer rates with the target budget previews', async () => {
    const mount = document.createElement('div')
    const onAssumptionsChange = vi.fn()
    const fetchPreview = vi.fn(async () => ({ sized: false, reason: 'quote' }))
    const ui = initRuntimeComparison({ mount, fetchPreview, onAssumptionsChange,
      getShape: () => ({ stages: [{ steps: 100 }], upload_mbps: 20, download_mbps: 80 }) })
    const input = mount.querySelector('input')
    expect(input.classList.contains('input--sm')).toBe(true)
    expect(input.value).toBe('20')
    expect(input.checkValidity()).toBe(true)
    input.value = '5'; input.dispatchEvent(new Event('change'))
    expect(onAssumptionsChange).toHaveBeenCalledWith({ upload_mbps: 5, download_mbps: 80 })
    expect(fetchPreview).toHaveBeenCalledWith(expect.objectContaining({ upload_mbps: 5 }))
    ui.dispose()
  })
})
