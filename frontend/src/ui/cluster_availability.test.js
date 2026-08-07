// @vitest-environment jsdom
/**
 * Factory contract for cluster_availability.js — the button's gating and, more
 * importantly, the refresh policy. Alpine login nodes are shared infrastructure, so
 * "does it poll when nobody is looking" is a real correctness question, not a nicety.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { initClusterAvailability } from './cluster_availability.js'

const RESP = {
  cluster: 'alpine',
  checked_at: '2026-08-06T12:00:00',
  history_days: 30,
  history_scope: 'cluster-wide',
  partitions: [
    { partition: 'ah200', gpu_model: 'NVIDIA H200', gpus_total: 8, gpus_free: 7,
      pending_jobs: 0, pending_gpus: 0, wait_min: 0, wait_basis: 'free now' },
  ],
  warnings: [],
}

function setup(over = {}) {
  document.body.innerHTML = '<div id="mount"></div>'
  const mount = document.getElementById('mount')
  const timers = { set: vi.fn(() => 't1'), clear: vi.fn() }
  const fetchAvailability = vi.fn(async () => RESP)
  const api = initClusterAvailability({ mount, fetchAvailability, timers, ...over })
  return { api, mount, timers, fetchAvailability }
}

const connect = () => window.dispatchEvent(
  new CustomEvent('nadoc:cluster-state-change', { detail: { state: 'connected' } }))

beforeEach(() => { document.body.innerHTML = '' })

describe('the button', () => {
  it('is disabled until a cluster session is live', () => {
    const { api, mount } = setup()
    expect(mount.querySelector('#alpine-availability-btn').disabled).toBe(true)
    expect(mount.querySelector('#alpine-availability-btn').title).toMatch(/Connect to Alpine/)
    connect()
    expect(mount.querySelector('#alpine-availability-btn').disabled).toBe(false)
    api.dispose()
  })

  it('re-disables when the session drops', () => {
    const { api, mount } = setup()
    connect()
    window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change',
      { detail: { state: 'expired' } }))
    expect(mount.querySelector('#alpine-availability-btn').disabled).toBe(true)
    api.dispose()
  })
})

describe('refresh', () => {
  it('passes the selected job id so the estimate is sized for the real run', async () => {
    const { api, fetchAvailability } = setup({ getJobId: () => 'job-7' })
    await api.refresh()
    expect(fetchAvailability).toHaveBeenCalledWith({ jobId: 'job-7', force: false })
    api.dispose()
  })

  it('does not fire a second request while one is in flight', async () => {
    let release
    const fetchAvailability = vi.fn(() => new Promise(r => { release = () => r(RESP) }))
    const { api } = setup({ fetchAvailability })
    const first = api.refresh()
    await api.refresh()                       // must be dropped, not queued
    expect(fetchAvailability).toHaveBeenCalledTimes(1)
    release()
    await first
    api.dispose()
  })

  it('turns a 409 into an actionable message instead of a status code', async () => {
    const fetchAvailability = vi.fn(async () => { throw new Error('HTTP 409') })
    const { api } = setup({ fetchAvailability })
    await api.refresh()
    expect(api.response).toBe(null)
    api.dispose()
  })

  it('survives a rejected fetch without throwing', async () => {
    const fetchAvailability = vi.fn(async () => { throw new Error('network down') })
    const { api } = setup({ fetchAvailability })
    await expect(api.refresh()).resolves.toBe(null)
    api.dispose()
  })
})

describe('polling policy', () => {
  it('starts no timer until the popup is open', () => {
    const { api, timers } = setup()
    expect(timers.set).not.toHaveBeenCalled()
    api.dispose()
  })

  it('polls while the popup is open and stops when it closes', async () => {
    const { api, timers } = setup()
    await api.open()
    expect(timers.set).toHaveBeenCalledTimes(1)
    expect(timers.set.mock.calls[0][1]).toBe(60_000)
    api.dispose()
    expect(timers.clear).toHaveBeenCalled()
  })

  it('stops polling when the tab is hidden', async () => {
    const { api, timers } = setup()
    await api.open()
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(timers.clear).toHaveBeenCalled()
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    api.dispose()
  })

  it('dispose removes the listeners it added', async () => {
    const { api, mount } = setup()
    api.dispose()
    connect()
    // The button was rendered once at init and must not repaint after dispose.
    expect(mount.querySelector('#alpine-availability-btn').disabled).toBe(true)
  })
})
