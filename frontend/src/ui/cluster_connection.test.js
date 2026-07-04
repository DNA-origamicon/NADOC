/**
 * Unit tests for the pure helpers + factory contract of cluster_connection.js.
 * Pure helpers need no DOM; the factory smoke-test uses jsdom + a fake fetch.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { chipStyleForState, whoLabel, connectPayload, expiryMessage, initClusterConnection } from './cluster_connection.js'

describe('chipStyleForState', () => {
  it('maps each known state to a distinct label', () => {
    expect(chipStyleForState('disconnected').label).toMatch(/Disconnected/)
    expect(chipStyleForState('connecting').clickable).toBe(false)
    expect(chipStyleForState('connected').color).toBe('#3fb950')
    expect(chipStyleForState('expired').label).toMatch(/Reconnect/)
  })
  it('falls back to disconnected for unknown state', () => {
    expect(chipStyleForState('garbage')).toBe(chipStyleForState('disconnected'))
  })
})

describe('whoLabel', () => {
  it('returns the who string when present', () => {
    expect(whoLabel({ who: 'jojo@login.rc.colorado.edu' })).toBe('jojo@login.rc.colorado.edu')
  })
  it('returns empty when missing', () => {
    expect(whoLabel(null)).toBe('')
    expect(whoLabel({ who: null })).toBe('')
  })
})

describe('connectPayload', () => {
  it('trims user, keeps password verbatim, defaults duo to push', () => {
    const p = connectPayload({ user: '  jojo ', password: ' pw ' })
    expect(p).toEqual({ cluster_name: 'alpine', user: 'jojo', password: ' pw ', duo_method: 'push' })
  })
  it('omits host when blank, includes when given', () => {
    expect(connectPayload({ user: 'u', password: 'p' }).host).toBeUndefined()
    expect(connectPayload({ user: 'u', password: 'p', host: ' h ' }).host).toBe('h')
  })
  it('passes a passcode through as duo_method', () => {
    expect(connectPayload({ user: 'u', password: 'p', duoMethod: '123456' }).duo_method).toBe('123456')
  })
  it('empty duo falls back to push', () => {
    expect(connectPayload({ user: 'u', password: 'p', duoMethod: '' }).duo_method).toBe('push')
  })
})

describe('expiryMessage', () => {
  it('is empty for a healthy/connecting session', () => {
    expect(expiryMessage({ state: 'connected', last_error: 'x' })).toBe('')
    expect(expiryMessage({ state: 'connecting' })).toBe('')
    expect(expiryMessage(null)).toBe('')
  })
  it('is empty when expired but no error recorded', () => {
    expect(expiryMessage({ state: 'expired' })).toBe('')
  })
  it('maps kind to a human prefix and appends the raw error', () => {
    expect(expiryMessage({ state: 'expired', error_kind: 'network', last_error: 'Broken pipe' }))
      .toBe('Connection lost — Broken pipe')
    expect(expiryMessage({ state: 'expired', error_kind: 'timeout', last_error: 'command timed out' }))
      .toBe('Session timed out — command timed out')
  })
  it('surfaces a failed-connect error on a disconnected session', () => {
    expect(expiryMessage({ state: 'disconnected', error_kind: 'auth', last_error: 'denied' }))
      .toBe('Authentication expired — denied')
  })
  it('falls back to a generic prefix for an unknown kind', () => {
    expect(expiryMessage({ state: 'expired', error_kind: 'weird', last_error: 'huh' }))
      .toBe('Session ended — huh')
  })
})

describe('initClusterConnection factory', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('is a no-op safe when mount is missing', () => {
    const api = initClusterConnection({})
    expect(api.getState()).toBe('disconnected')
  })

  it('renders a chip and reflects fetched status', async () => {
    const mount = document.createElement('div')
    document.body.appendChild(mount)
    const fetchImpl = vi.fn(async (url) => {
      if (url.endsWith('/status')) return { json: async () => ({ state: 'connected', who: 'jojo@alpine', host: 'alpine' }) }
      if (url.endsWith('/profiles')) return { json: async () => ({ profiles: [{ name: 'alpine', host: 'login.rc.colorado.edu' }] }) }
      return { ok: true, json: async () => ({}) }
    })
    const api = initClusterConnection({ mount, fetchImpl })
    const chip = mount.querySelector('#md-cluster-chip')
    expect(chip).toBeTruthy()
    await api.refresh()
    expect(api.getState()).toBe('connected')
    expect(chip.textContent).toContain('jojo@alpine')
  })
})
