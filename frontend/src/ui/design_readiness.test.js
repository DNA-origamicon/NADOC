import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { designReadinessSummary, initDesignReadiness } from './design_readiness.js'

const report = (overrides = {}) => ({
  available: true,
  state: 'incomplete',
  completed_steps: 1,
  total_steps: 3,
  steps: [
    { id: 'scaffold_routing', label: 'Scaffold routing', complete: true, applicable: true, detail: 'Scaffold routed.', action: 'scaffold_routing', hotkey: '1' },
    { id: 'staple_routing', label: 'Staple routing', complete: false, applicable: true, detail: 'Staples are missing.', action: 'staple_routing', hotkey: '2' },
    { id: 'topology', label: 'Topology checks', complete: false, applicable: true, detail: 'Review the topology.', action: 'validation' },
  ],
  simulation: { complete: false, detail: 'No matching completed fine or production simulation.', action: 'simulation' },
  limitations: ['These checks do not predict folding yield.'],
  ...overrides,
})

describe('designReadinessSummary', () => {
  it('counts standard steps without including optional simulation', () => {
    expect(designReadinessSummary(report())).toEqual({
      state: 'incomplete', completed: 1, total: 3, fraction: 1 / 3, label: '1/3 complete', caption: '',
    })
    expect(designReadinessSummary(report({ completed_steps: 3, state: 'simulation_recommended' }))).toMatchObject({
      state: 'simulation_recommended', label: '3/3 complete', fraction: 1, caption: 'Sim recommended',
    })
  })

  it('requires complete standard steps and a qualifying simulation for green', () => {
    const simulated = report({ state: 'ready', completed_steps: 3, simulation: { complete: true } })
    expect(designReadinessSummary(simulated)).toMatchObject({ state: 'ready', caption: 'Simulation complete' })
    expect(designReadinessSummary({ ...simulated, completed_steps: 2 }).state).toBe('incomplete')
    expect(designReadinessSummary({ ...simulated, simulation: { complete: false } }).state).toBe('simulation_recommended')
    expect(designReadinessSummary({ ...simulated, state: 'incomplete' }).state).toBe('simulation_recommended')
  })

  it('does not show empty or malformed counts as complete', () => {
    expect(designReadinessSummary(null)).toMatchObject({ state: 'incomplete', fraction: 0, label: '0/0 complete' })
    expect(designReadinessSummary(report({ completed_steps: -3, total_steps: 5 }))).toMatchObject({ completed: 0, fraction: 0 })
    expect(designReadinessSummary(report({ completed_steps: 8, total_steps: 5 }))).toMatchObject({ completed: 5, fraction: 1 })
  })
})

describe('initDesignReadiness', () => {
  let host, widget, onAction
  const root = () => host.querySelector('[data-role="design-readiness"]')
  const trigger = () => host.querySelector('[data-role="readiness-trigger"]')
  const popover = () => host.querySelector('.design-readiness__popover')
  const action = id => host.querySelector(`button[data-action="${id}"]`)
  const hover = () => root().dispatchEvent(new Event('pointerenter'))
  const leave = () => root().dispatchEvent(new Event('pointerleave'))

  beforeEach(() => {
    vi.useFakeTimers()
    host = mountIds({ 'viewport-host': 'div' })['viewport-host']
    onAction = vi.fn()
    widget = initDesignReadiness({ host, onAction })
  })
  afterEach(() => {
    widget.dispose()
    vi.useRealTimers()
    vi.restoreAllMocks()
    clearDom()
  })

  it('renders a partial ring and all complete/missing steps with genuine command shortcuts', () => {
    widget.setReport(report())
    expect(trigger().textContent).toBe('1/3 complete')
    expect(root().dataset.state).toBe('incomplete')
    expect(Number.parseFloat(root().querySelector('.design-readiness__progress').getAttribute('stroke-dasharray'))).toBeCloseTo(100 / 3)
    hover()
    expect(popover().hidden).toBe(false)
    expect(trigger().getAttribute('aria-expanded')).toBe('true')
    expect(host.querySelectorAll('[data-step-id]')).toHaveLength(4)
    expect(host.querySelector('[data-step-id="scaffold_routing"]').textContent).toContain('Complete')
    expect(host.querySelector('[data-step-id="scaffold_routing"] kbd').textContent).toBe('1')
    expect(action('scaffold_routing')).toBeNull()
    expect(action('staple_routing').textContent).toContain('Missing')
    expect(action('staple_routing').querySelector('kbd').textContent).toBe('2')
    expect(action('validation').querySelector('kbd')).toBeNull()
    expect(popover().textContent).toContain('These checks do not predict folding yield.')
  })

  it('hides completed simulated designs and returns when readiness changes', () => {
    widget.setReport(report({ completed_steps: 3, state: 'simulation_recommended' }))
    expect(root().dataset.state).toBe('simulation_recommended')
    expect(trigger().textContent).toContain('Sim recommended')
    widget.setReport(report({ completed_steps: 3, state: 'ready', simulation: { complete: true, detail: 'Matching production job completed.' } }))
    expect(root().dataset.state).toBe('ready')
    expect(trigger().textContent).toContain('Simulation complete')
    expect(root().hidden).toBe(true)
    hover()
    expect(popover().hidden).toBe(true)
    widget.setReport(report())
    expect(root().hidden).toBe(false)
    expect(root().dataset.state).toBe('incomplete')
    expect(trigger().textContent).not.toContain('Simulation complete')
  })

  it('keeps N/A rows visible and disabled actions honest', () => {
    widget.setReport(report({ completed_steps: 0, total_steps: 1, steps: [
      { id: 'scaffold_routing', label: 'Scaffold routing', applicable: false, complete: false, action: 'scaffold_routing' },
      { id: 'staple_routing', label: 'Staple routing', applicable: true, complete: false, action: 'staple_routing', hotkey: '2', blocked: true, blocked_reason: 'Open this part in its editor.' },
    ] }))
    expect(trigger().textContent).toBe('0/1 complete')
    expect(host.querySelector('[data-step-id="scaffold_routing"]').textContent).toContain('Not required')
    expect(action('scaffold_routing')).toBeNull()
    expect(action('staple_routing').disabled).toBe(true)
    expect(action('staple_routing').textContent).toContain('Open this part in its editor.')
    expect(action('staple_routing').querySelector('kbd')).toBeNull()
    action('staple_routing').click()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('dispatches a missing command with its metadata and closes the popover', () => {
    const current = report()
    widget.setReport(current)
    hover()
    action('staple_routing').click()
    expect(onAction).toHaveBeenCalledWith('staple_routing', current.steps[1])
    expect(popover().hidden).toBe(true)
    expect(trigger().getAttribute('aria-expanded')).toBe('false')
  })

  it('lets the hover move into the popover before dismissal and preserves keyboard focus', () => {
    widget.setReport(report())
    hover()
    leave()
    vi.advanceTimersByTime(100)
    hover()
    vi.advanceTimersByTime(200)
    expect(popover().hidden).toBe(false)
    action('staple_routing').focus()
    leave()
    vi.advanceTimersByTime(200)
    expect(popover().hidden).toBe(false)
    action('staple_routing').blur()
    vi.advanceTimersByTime(200)
    expect(popover().hidden).toBe(true)
  })

  it('supports keyboard focus, Escape, refocusing, and touch click toggling', () => {
    widget.setReport(report())
    trigger().focus()
    expect(popover().hidden).toBe(false)
    action('staple_routing').focus()
    action('staple_routing').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(popover().hidden).toBe(true)
    expect(document.activeElement).toBe(trigger())
    trigger().blur()
    trigger().focus()
    expect(popover().hidden).toBe(false)
    trigger().click()
    leave()
    vi.advanceTimersByTime(200)
    expect(popover().hidden).toBe(false)
    trigger().click()
    expect(popover().hidden).toBe(true)
    trigger().click()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(popover().hidden).toBe(true)
  })

  it('can reveal a selected missing step without executing it and preserve focus on refresh', () => {
    widget.setReport(report())
    widget.focusStep('staple_routing')
    expect(popover().hidden).toBe(false)
    expect(document.activeElement).toBe(action('staple_routing'))
    expect(onAction).not.toHaveBeenCalled()
    widget.setReport(report())
    expect(document.activeElement).toBe(action('staple_routing'))
    widget.focusStep('scaffold_routing')
    expect(document.activeElement).toBe(trigger())
  })

  it('replaces stale green with explicit loading/error and hides for no design', () => {
    widget.setReport(report({ completed_steps: 3, state: 'ready', simulation: { complete: true } }))
    widget.setLoading()
    expect(root().dataset.state).toBe('loading')
    expect(root().getAttribute('aria-busy')).toBe('true')
    expect(trigger().textContent).toBe('Checking…')
    expect(host.querySelectorAll('[data-step-id]')).toHaveLength(0)
    widget.setError('Connection unavailable.')
    expect(root().dataset.state).toBe('unavailable')
    expect(root().hasAttribute('aria-busy')).toBe(false)
    expect(trigger().textContent).toBe('Check unavailable')
    expect(popover().textContent).toContain('Connection unavailable.')
    widget.setReport({ available: false })
    expect(root().hidden).toBe(true)
    expect(popover().hidden).toBe(true)
  })

  it('renders untrusted report text as text, including errors and limitations', () => {
    widget.setReport(report({ steps: [{ label: '<img src=x onerror=alert(1)>', detail: '<script>bad()</script>', complete: true, issues: ['Staple 4: 24/32 bases assigned.', { message: '<img src=x>' }] }], limitations: ['<b>Plain text</b>'] }))
    expect(popover().querySelector('img,script,b')).toBeNull()
    expect(popover().textContent).toContain('<script>bad()</script>')
    expect(popover().querySelector('details summary').textContent).toBe('2 issues')
    expect(popover().querySelector('details').textContent).toContain('Staple 4: 24/32 bases assigned.')
    widget.setError('<img src=x>')
    expect(popover().querySelector('img')).toBeNull()
  })

  it('shows command failures without unhandled rejection and ignores them after disposal', async () => {
    onAction.mockRejectedValueOnce(new Error('Could not open simulation.'))
    widget.setReport(report())
    action('simulation').click()
    await Promise.resolve()
    expect(popover().hidden).toBe(false)
    expect(popover().querySelector('[role="status"]').textContent).toBe('Could not open simulation.')
    let reject
    onAction.mockImplementationOnce(() => new Promise((resolve, rejectPromise) => { reject = rejectPromise }))
    action('simulation').click()
    widget.dispose()
    reject(new Error('Late action failure.'))
    await Promise.resolve()
    expect(host.children).toHaveLength(0)
  })

  it('disposes DOM, timers, and global events and permits a fresh instance', () => {
    widget.setReport(report())
    hover()
    leave()
    widget.dispose()
    widget.dispose()
    vi.advanceTimersByTime(200)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(host.children).toHaveLength(0)
    widget = initDesignReadiness({ host, onAction })
    widget.setReport(report())
    widget.open()
    expect(popover().hidden).toBe(false)
    expect(host.children).toHaveLength(1)
  })
})
