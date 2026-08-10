// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ATOMISTIC_LOADING_CALL_EVENT,
  ATOMISTIC_LOADING_PING_EVENT,
  ATOMISTIC_LOADING_TEXT,
  installAtomisticLoadingProbe,
} from './atomistic_loading_probe.js'

const settleObserver = () => new Promise(resolve => setTimeout(resolve, 0))

describe('atomistic loading probe', () => {
  let probe = null

  afterEach(() => {
    probe?.stop()
    probe = null
    document.body.replaceChildren()
  })

  it('pings when a reused persistent-toast slot transitions into atomistic loading', async () => {
    const snapshots = []
    const domEvents = []
    document.addEventListener(ATOMISTIC_LOADING_PING_EVENT, event => domEvents.push(event.detail), {
      once: true,
    })
    probe = installAtomisticLoadingProbe({
      logger: null,
      snapshot: () => ({ position: snapshots.length }),
      onPing: event => snapshots.push(event.snapshot),
    })

    const toast = document.createElement('div')
    toast.className = 'toast'
    const message = document.createElement('span')
    message.className = 'toast-message'
    message.textContent = 'Saving design…'
    toast.appendChild(message)
    document.body.appendChild(toast)
    await settleObserver()
    expect(probe.count()).toBe(0)

    message.textContent = ATOMISTIC_LOADING_TEXT
    await settleObserver()
    expect(probe.count()).toBe(1)
    expect(probe.events()[0].snapshot).toEqual({ position: 0 })
    expect(domEvents).toHaveLength(1)

    // Unrelated mutations while the same loading state remains visible do not
    // manufacture extra pings.
    toast.classList.add('toast--visible')
    await settleObserver()
    expect(probe.count()).toBe(1)

    message.textContent = 'Saving design…'
    await settleObserver()
    message.textContent = ATOMISTIC_LOADING_TEXT
    await settleObserver()
    expect(probe.count()).toBe(2)
  })

  it('reset keeps an already-visible loading toast from being counted again', async () => {
    document.body.innerHTML = `<span class="toast-message">${ATOMISTIC_LOADING_TEXT}</span>`
    probe = installAtomisticLoadingProbe({ logger: null })
    expect(probe.count()).toBe(1)

    probe.reset()
    document.body.appendChild(document.createElement('div'))
    await settleObserver()
    expect(probe.count()).toBe(0)
  })

  it('stops observing', async () => {
    probe = installAtomisticLoadingProbe({ logger: null })
    probe.stop()
    document.body.innerHTML = `<span class="toast-message">${ATOMISTIC_LOADING_TEXT}</span>`
    await settleObserver()
    expect(probe.count()).toBe(0)
  })

  it('prints a paste-ready five-second report with calls, appearances, and context', async () => {
    const logger = { warn: vi.fn(), error: vi.fn(), info: vi.fn() }
    probe = installAtomisticLoadingProbe({
      logger,
      reportWindowMs: 20,
      context: () => ({ atomLoadGeneration: 7 }),
    })
    window.dispatchEvent(new CustomEvent(ATOMISTIC_LOADING_CALL_EVENT, {
      detail: {
        atMs: performance.now(),
        wallTime: '2026-08-09T00:00:00.000Z',
        stack: 'at applyAtomisticMode (atom_surface_display.js:1:1)',
        diagnostic: { owner: 'atom_surface_display.applyAtomisticMode' },
      },
    }))
    document.body.innerHTML = `<span class="toast-message">${ATOMISTIC_LOADING_TEXT}</span>`
    await settleObserver()
    await new Promise(resolve => setTimeout(resolve, 30))

    const report = probe.latestReport()
    expect(report?.showCallCount).toBe(1)
    expect(report?.appearanceCount).toBe(1)
    expect(report?.showCalls[0].stack).toContain('applyAtomisticMode')
    expect(report?.contextAtReport).toEqual({ atomLoadGeneration: 7 })
    expect(logger.error).toHaveBeenCalledWith(expect.stringMatching(
      /^NADOC_ATOMISTIC_LOADING_DIAGNOSTIC=\{"schema":"nadoc-atomistic-loading-diagnostic-v1"/,
    ))
  })
})
