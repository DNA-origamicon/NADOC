import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'

let showOpProgress, hideOpProgress, buildOpProgressReport, formatElapsed

function mount() {
  return mountIds({
    'op-progress': 'div',
    'op-progress-header': 'div',
    'op-progress-label': 'div',
    'op-progress-meta': 'div',
    'op-progress-track': 'div',
    'op-progress-fill': 'div',
    'op-progress-cancel': 'button',
    'op-progress-copy': 'button',
  })
}

describe('op_progress elapsed + copy details', () => {
  beforeEach(async () => {
    clearDom(); vi.useFakeTimers()
    // The module caches its DOM refs and ref-count; take a fresh instance per test.
    vi.resetModules()
    ;({ showOpProgress, hideOpProgress, buildOpProgressReport, formatElapsed } = await import('./op_progress.js'))
  })
  afterEach(() => { vi.useRealTimers() })

  it('formats durations', () => {
    expect(formatElapsed(4200)).toBe('4.2s')
    expect(formatElapsed(65000)).toBe('1m 05s')
    expect(formatElapsed(3720000)).toBe('1h 02m')
  })

  it('shows process detail and a ticking elapsed time', () => {
    const els = mount()
    const t = showOpProgress('Auto Break', '', { detail: 'POST /design/auto-break (request #7)' })
    expect(els['op-progress-meta'].textContent).toContain('POST /design/auto-break (request #7)')
    expect(els['op-progress-meta'].textContent).toContain('elapsed 0.0s')
    vi.advanceTimersByTime(3000)
    expect(els['op-progress-meta'].textContent).toContain('elapsed 3.0s')
    hideOpProgress(t)
    expect(els['op-progress-meta'].textContent).toBe('')
  })

  it('honours startedAt from before the popup appeared', () => {
    const els = mount()
    const t = showOpProgress('Slow', '', { startedAt: performance.now() - 5000 })
    expect(els['op-progress-meta'].textContent).toContain('elapsed 5.0s')
    hideOpProgress(t)
  })

  it('report lists every active operation and releases by token', () => {
    mount()
    const a = showOpProgress('Op A', 'first', { detail: 'GET /a' })
    const b = showOpProgress('Op B', 'second', { detail: 'GET /b' })
    const report = buildOpProgressReport()
    expect(report).toContain('Active operations: 2')
    expect(report).toContain('Operation: Op A')
    expect(report).toContain('Status: second')
    expect(report).toContain('Process: GET /b')
    hideOpProgress(a)   // out of order: B must remain
    const after = buildOpProgressReport()
    expect(after).toContain('Active operations: 1')
    expect(after).toContain('Operation: Op B')
    hideOpProgress(b)
  })

  it('copy button writes the report to the clipboard', async () => {
    const els = mount()
    const writeText = vi.fn().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const t = showOpProgress('Auto Break', 'Running', { detail: 'POST /design/auto-break' })
    els['op-progress-copy'].click()
    await vi.advanceTimersByTimeAsync(0)
    expect(writeText).toHaveBeenCalledOnce()
    expect(writeText.mock.calls[0][0]).toContain('Process: POST /design/auto-break')
    expect(els['op-progress-copy'].textContent).toBe('Copied')
    hideOpProgress(t)
    vi.unstubAllGlobals()
  })
})
