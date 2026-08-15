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

  it('clears Connecting from authoritative status even while connect response is delayed', async () => {
    vi.useFakeTimers()
    try {
      const mount = document.createElement('div')
      document.body.appendChild(mount)
      let connectStarted = false
      let releaseConnect
      const delayedConnect = new Promise(resolve => { releaseConnect = resolve })
      const fetchImpl = vi.fn(async (url, opts = {}) => {
        if (url.endsWith('/profiles')) return { ok: true, json: async () => ({ profiles: [] }) }
        if (url.endsWith('/connect') && opts.method === 'POST') {
          connectStarted = true
          return delayedConnect
        }
        if (url.endsWith('/status')) return {
          ok: true,
          json: async () => connectStarted
            ? ({ state: 'connected', who: 'jojo@alpine', host: 'alpine' })
            : ({ state: 'disconnected', who: null }),
        }
        return { ok: true, json: async () => ({}) }
      })
      const api = initClusterConnection({ mount, fetchImpl })
      await api.refresh()
      mount.querySelector('button[id^="md-cluster-chip"]').click()
      document.querySelector('#cl-user').value = 'jojo'
      document.querySelector('#cl-pass').value = 'secret'
      document.querySelector('#cl-go').click()
      await Promise.resolve()
      expect(api.getState()).toBe('connecting')

      await vi.advanceTimersByTimeAsync(500)
      expect(api.getState()).toBe('connected')
      expect(document.querySelector('#cl-go')).toBeNull() // modal closed
      expect(mount.textContent).toContain('jojo@alpine')

      releaseConnect({ ok: true, json: async () => ({ state: 'connected', who: 'jojo@alpine' }) })
      await Promise.resolve()
      api.dispose()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('two chips on screen (Clusters card + Job Wizard)', () => {
  it('contains login-field keydowns from both chips before global hotkeys see them', () => {
    document.body.innerHTML = '<div id="sidebar"></div><div id="wizard"></div>'
    const fetchImpl = async () => ({ json: async () => ({ state: 'disconnected' }) })
    const sidebar = initClusterConnection({ mount: document.getElementById('sidebar'), fetchImpl })
    const wizard = initClusterConnection({ mount: document.getElementById('wizard'), fetchImpl })
    const globalHotkey = vi.fn()
    document.addEventListener('keydown', globalHotkey)

    for (const chip of document.querySelectorAll('button[id^="md-cluster-chip"]')) {
      chip.click()
      const modal = document.body.lastElementChild
      for (const input of modal.querySelectorAll('input')) {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'u', bubbles: true }))
      }
      modal.querySelector('#cl-cancel').click()
    }

    expect(globalHotkey).not.toHaveBeenCalled()
    document.removeEventListener('keydown', globalHotkey)
    sidebar.dispose(); wizard.dispose()
  })

  it('mirrors a sign-in from one chip onto the other', async () => {
    // Only the chip that owns the session polls, so without adoption the second chip
    // would sit on a stale "Disconnected" forever.
    document.body.innerHTML = '<div id="a"></div><div id="b"></div>'
    const fetchImpl = async () => ({ json: async () => ({ state: 'disconnected', who: null }) })
    const a = initClusterConnection({ mount: document.getElementById('a'), fetchImpl })
    const b = initClusterConnection({ mount: document.getElementById('b'), fetchImpl })

    window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change', {
      detail: { state: 'connected', status: { state: 'connected', who: 'me@alpine' }, source: 'external' },
    }))
    expect(a.getState()).toBe('connected')
    expect(b.getState()).toBe('connected')
    a.dispose(); b.dispose()
  })

  it('gives each chip a unique DOM id', () => {
    // Duplicate ids silently break querySelector for whichever came second.
    document.body.innerHTML = '<div id="a"></div><div id="b"></div>'
    const fetchImpl = async () => ({ json: async () => ({ state: 'disconnected' }) })
    const a = initClusterConnection({ mount: document.getElementById('a'), fetchImpl })
    const b = initClusterConnection({ mount: document.getElementById('b'), fetchImpl })
    const ids = [...document.querySelectorAll('button')].map(n => n.id)
    expect(new Set(ids).size).toBe(ids.length)
    a.dispose(); b.dispose()
  })

  it('does not echo a sibling broadcast back out', () => {
    document.body.innerHTML = '<div id="a"></div><div id="b"></div>'
    const fetchImpl = async () => ({ json: async () => ({ state: 'disconnected' }) })
    const a = initClusterConnection({ mount: document.getElementById('a'), fetchImpl })
    const b = initClusterConnection({ mount: document.getElementById('b'), fetchImpl })
    let seen = 0
    const count = () => { seen += 1 }
    window.addEventListener('nadoc:cluster-state-change', count)
    window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change', {
      detail: { state: 'connected', status: { who: 'me' }, source: 'external' },
    }))
    // Exactly the one we dispatched — adoption must be silent or the chips ping-pong.
    expect(seen).toBe(1)
    window.removeEventListener('nadoc:cluster-state-change', count)
    a.dispose(); b.dispose()
  })

  it('stops adopting after dispose', () => {
    document.body.innerHTML = '<div id="a"></div>'
    const fetchImpl = async () => ({ json: async () => ({ state: 'disconnected' }) })
    const a = initClusterConnection({ mount: document.getElementById('a'), fetchImpl })
    a.dispose()
    window.dispatchEvent(new CustomEvent('nadoc:cluster-state-change', {
      detail: { state: 'connected', status: { who: 'me' }, source: 'external' },
    }))
    expect(a.getState()).toBe('disconnected')
  })
})
