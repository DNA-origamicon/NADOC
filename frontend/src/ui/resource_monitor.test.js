/**
 * Factory test for the live "System monitor" sub-section (`initResourceMonitor`).
 *
 * Asserts the observable contract: the monitor is closed and NOT polling until its
 * toggle is clicked; opening it starts a poll and populates the three value labels
 * from the sample; the buffers roll (capped) and `n/a` shows when a resource is
 * absent; `stop()` halts polling.  Canvas stroking is a no-op under jsdom (no 2-D
 * context) — the value labels are the assertable output.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mountIds, clearDom } from '../test-helpers/factory_dom.js'
import { initResourceMonitor } from './resource_monitor.js'

const IDS = {
  'oxdna-metrics-resources-toggle': 'div',
  'oxdna-metrics-resources-arrow': 'span',
  'oxdna-metrics-resources-body': 'div',
}
for (const tok of ['cpu', 'gpu', 'ram']) {
  IDS[`oxdna-metrics-res-${tok}-spark`] = 'canvas'
  IDS[`oxdna-metrics-res-${tok}-val`] = 'span'
}

const sampleWithGpu = {
  cpu_pct: 52.2, ram_pct: 67, ram_used_mb: 20987, ram_total_mb: 31239,
  gpu_present: true, gpu_pct: 100, vram_pct: 52, vram_used_mb: 6425, vram_total_mb: 12288,
}
const sampleNoGpu = {
  cpu_pct: 8, ram_pct: 40, ram_used_mb: 4096, ram_total_mb: 16384,
  gpu_present: false, gpu_pct: null, vram_pct: null, vram_used_mb: null, vram_total_mb: null,
}

const val = tok => document.getElementById(`oxdna-metrics-res-${tok}-val`).textContent

beforeEach(() => { clearDom(); mountIds(IDS); vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('initResourceMonitor', () => {
  it('does not poll until the toggle is opened; opening starts a poll', async () => {
    const poll = vi.fn().mockResolvedValue(sampleWithGpu)
    const mon = initResourceMonitor({ idPrefix: 'oxdna-metrics', poll })
    expect(document.getElementById('oxdna-metrics-resources-body').style.display).toBe('none')
    expect(poll).not.toHaveBeenCalled()

    document.getElementById('oxdna-metrics-resources-toggle').click()
    expect(document.getElementById('oxdna-metrics-resources-body').style.display).toBe('')
    expect(poll).toHaveBeenCalledTimes(1)         // immediate first tick, no wait
    mon.stop()
  })

  it('labels reflect a GPU sample; n/a when the GPU is absent', () => {
    const mon = initResourceMonitor({ idPrefix: 'oxdna-metrics', poll: vi.fn() })
    mon._apply(sampleWithGpu)
    expect(val('cpu')).toBe('52%')
    expect(val('gpu')).toBe('100% · 6.3/12.0 GB')
    expect(val('ram')).toBe('67% · 20.5/30.5 GB')

    mon._apply(sampleNoGpu)
    expect(val('cpu')).toBe('8%')
    expect(val('gpu')).toBe('n/a')
    mon.stop()
  })

  it('polls on the interval while open and stops after stop()', async () => {
    const poll = vi.fn().mockResolvedValue(sampleWithGpu)
    const mon = initResourceMonitor({ idPrefix: 'oxdna-metrics', poll })
    document.getElementById('oxdna-metrics-resources-toggle').click()  // tick #1
    await vi.advanceTimersByTimeAsync(1500)                            // tick #2
    await vi.advanceTimersByTimeAsync(1500)                            // tick #3
    expect(poll).toHaveBeenCalledTimes(3)
    mon.stop()
    await vi.advanceTimersByTimeAsync(5000)
    expect(poll).toHaveBeenCalledTimes(3)                              // no more after stop
  })

  it('buffer rolls and is capped', () => {
    const mon = initResourceMonitor({ idPrefix: 'oxdna-metrics', poll: vi.fn() })
    for (let i = 0; i < 200; i++) mon._apply({ ...sampleWithGpu, cpu_pct: i })
    const cpu = mon._lines.find(l => l.key === 'cpu')
    expect(cpu.buf.length).toBeLessThanOrEqual(90)
    expect(cpu.buf[cpu.buf.length - 1]).toBe(199)   // newest retained
  })

  it('closing the toggle stops polling', async () => {
    const poll = vi.fn().mockResolvedValue(sampleWithGpu)
    const mon = initResourceMonitor({ idPrefix: 'oxdna-metrics', poll })
    const toggle = document.getElementById('oxdna-metrics-resources-toggle')
    toggle.click()                                  // open → tick #1
    expect(poll).toHaveBeenCalledTimes(1)
    toggle.click()                                  // close
    await vi.advanceTimersByTimeAsync(5000)
    expect(poll).toHaveBeenCalledTimes(1)           // no ticks while closed
    mon.stop()
  })
})
