import { describe, expect, it, vi } from 'vitest'
import {
  initRunpodSetup,
  validateApiKeyFormat,
  balanceStatus,
  volumeOptions,
  setupStepState,
} from './runpod_setup.js'

describe('validateApiKeyFormat', () => {
  it('mirrors the backend min_length of 8', () => {
    expect(validateApiKeyFormat('rp_abcdef')).toBe(true) // 9 chars
    expect(validateApiKeyFormat('short')).toBe(false)
    expect(validateApiKeyFormat('   rp_abcdef   ')).toBe(true) // trims
    expect(validateApiKeyFormat('')).toBe(false)
    expect(validateApiKeyFormat(null)).toBe(false)
  })
})

describe('balanceStatus', () => {
  it('warns loudly at $0 — RunPod destroys every pod at zero balance', () => {
    const s = balanceStatus({ available: true, balance: 0 })
    expect(s.level).toBe('warn')
    expect(s.text).toMatch(/\$0/)
  })

  it('warns when the balance is low enough a run could outlast it', () => {
    expect(balanceStatus({ available: true, balance: 5 }).level).toBe('warn')
  })

  it('is ok with a healthy balance', () => {
    const s = balanceStatus({ available: true, balance: 207 })
    expect(s.level).toBe('ok')
    expect(s.text).toContain('$207.00')
  })

  it('surfaces the reason when the balance is unreadable', () => {
    const s = balanceStatus({ available: false, reason: 'Cloudflare block' })
    expect(s.level).toBe('unknown')
    expect(s.text).toContain('Cloudflare block')
  })

  it('does not throw on a null payload', () => {
    expect(balanceStatus(null).level).toBe('unknown')
  })
})

describe('volumeOptions', () => {
  it('labels each volume with name, size and datacenter', () => {
    const opts = volumeOptions([
      { id: 'v1', name: 'namd', size_gb: 60, data_center_id: 'EU-RO-1' },
    ])
    expect(opts).toEqual([{ value: 'v1', label: 'namd — 60 GB (EU-RO-1)' }])
  })

  it('falls back to the id and a ? size when fields are missing', () => {
    const opts = volumeOptions([{ id: 'v2' }])
    expect(opts[0]).toEqual({ value: 'v2', label: 'v2 — ? GB' })
  })

  it('handles an empty list', () => {
    expect(volumeOptions(null)).toEqual([])
  })
})

describe('setupStepState', () => {
  it('is all-pending before anything happens', () => {
    const s = setupStepState({})
    expect(s).toEqual({
      credit: 'pending', apikey: 'pending', ssh: 'pending', volume: 'pending', verify: 'pending',
    })
  })

  it('marks credit blocked at $0 and done with money', () => {
    expect(setupStepState({ balance: { available: true, balance: 0 } }).credit).toBe('blocked')
    expect(setupStepState({ balance: { available: true, balance: 50 } }).credit).toBe('done')
  })

  it('marks ssh blocked when the local key is missing', () => {
    expect(setupStepState({ sshPresent: false }).ssh).toBe('blocked')
    expect(setupStepState({ sshPresent: true }).ssh).toBe('done')
  })

  it('verify is blocked on a red pre-flight, done on a green one', () => {
    expect(setupStepState({ preflight: { ok: false } }).verify).toBe('blocked')
    expect(setupStepState({ preflight: { ok: true } }).verify).toBe('done')
  })
})

// ── Factory ──────────────────────────────────────────────────────────────────

/** A fetch double that dispatches by path so one mock serves the whole wizard flow. */
function fakeFetch(routes) {
  return vi.fn(async (path, opts) => {
    const key = `${opts?.method === 'POST' ? 'POST ' : ''}${path}`
    const handler = routes[key] ?? routes[path]
    const body = handler ? handler(opts) : { status: 404, json: {} }
    return {
      ok: (body.status ?? 200) < 400,
      status: body.status ?? 200,
      json: async () => body.json ?? {},
    }
  })
}

const GREEN_PREFLIGHT = {
  ok: true,
  checks: [{ key: 'api_key', ok: true, label: 'RunPod API key', detail: 'connected' }],
  gpus: [],
}

describe('initRunpodSetup factory', () => {
  it('renders a launcher button into the mount', () => {
    const mount = document.createElement('div')
    initRunpodSetup({ mount, fetchImpl: vi.fn() })
    expect(mount.querySelector('#rp-setup-open')).toBeTruthy()
    expect(mount.textContent).toContain('Set up RunPod')
  })

  it('opening the wizard shows the five-step checklist', () => {
    const w = initRunpodSetup({ mount: document.createElement('div'), fetchImpl: vi.fn() })
    w.open()
    const body = document.querySelector('.modal__body')
    expect(body).toBeTruthy()
    expect(body.textContent).toContain('API key')
    expect(body.textContent).toContain('Network volume')
    w.dispose()
  })

  it('verifying a key connects, then loads balance / volumes / ssh key', async () => {
    const fetchImpl = fakeFetch({
      'POST /api/runpod/connect': () => ({ json: { connected: true, network_volume_id: null } }),
      '/api/runpod/balance': () => ({ json: { available: true, balance: 207 } }),
      '/api/runpod/volumes': () => ({ json: { volumes: [{ id: 'v1', name: 'namd', size_gb: 60 }] } }),
      '/api/runpod/ssh-public-key': () => ({ json: { present: true, public_key: 'ssh-ed25519 AAA' } }),
    })
    const w = initRunpodSetup({ mount: document.createElement('div'), fetchImpl })
    w.open()
    const body = document.querySelector('.modal__body')
    body.querySelector('#rp-setup-key').value = 'rp_abcdefgh'
    body.querySelector('#rp-setup-key').dispatchEvent(new Event('input'))
    body.querySelector('#rp-setup-verify').click()
    await vi.waitFor(() => expect(document.querySelector('.modal__body').textContent).toContain('$207.00'))

    const after = document.querySelector('.modal__body')
    expect(after.textContent).toContain('Connected')
    expect(after.querySelector('#rp-setup-pubkey').value).toContain('ssh-ed25519')
    expect(after.querySelector('#rp-setup-volume')).toBeTruthy()
    w.dispose()
  })

  it('a rejected key shows the error and does not connect', async () => {
    const fetchImpl = fakeFetch({
      'POST /api/runpod/connect': () => ({ status: 400, json: { detail: 'RunPod rejected the API key (401).' } }),
    })
    const w = initRunpodSetup({ mount: document.createElement('div'), fetchImpl })
    w.open()
    const body = document.querySelector('.modal__body')
    body.querySelector('#rp-setup-key').value = 'rp_bogus1234'
    body.querySelector('#rp-setup-key').dispatchEvent(new Event('input'))
    body.querySelector('#rp-setup-verify').click()
    await vi.waitFor(() =>
      expect(document.querySelector('.modal__body').textContent).toContain('rejected the API key'))
    expect(document.querySelector('.modal__body').textContent).not.toContain('Connected.')
    w.dispose()
  })

  it('a green pre-flight fires onConnected so the Run gate refreshes', async () => {
    const onConnected = vi.fn()
    const fetchImpl = fakeFetch({
      'POST /api/runpod/connect': () => ({ json: { connected: true } }),
      '/api/runpod/balance': () => ({ json: { available: true, balance: 207 } }),
      '/api/runpod/volumes': () => ({ json: { volumes: [{ id: 'v1', name: 'namd', size_gb: 60 }] } }),
      '/api/runpod/ssh-public-key': () => ({ json: { present: true, public_key: 'ssh-ed25519 AAA' } }),
      'POST /api/runpod/preflight': () => ({ json: GREEN_PREFLIGHT }),
    })
    const w = initRunpodSetup({ mount: document.createElement('div'), fetchImpl, onConnected })
    w.open()
    let body = document.querySelector('.modal__body')
    body.querySelector('#rp-setup-key').value = 'rp_abcdefgh'
    body.querySelector('#rp-setup-key').dispatchEvent(new Event('input'))
    body.querySelector('#rp-setup-verify').click()
    await vi.waitFor(() => expect(document.querySelector('.modal__body').querySelector('#rp-setup-volume')).toBeTruthy())

    body = document.querySelector('.modal__body')
    const sel = body.querySelector('#rp-setup-volume')
    sel.value = 'v1'
    sel.dispatchEvent(new Event('change'))
    await vi.waitFor(() => {
      const btn = document.querySelector('#rp-setup-preflight')
      expect(btn && !btn.disabled).toBe(true)
    })

    document.querySelector('#rp-setup-preflight').click()
    await vi.waitFor(() => expect(onConnected).toHaveBeenCalled())
    expect(document.querySelector('.modal__body').textContent).toContain("You're ready")
    w.dispose()
  })
})
