import { it, expect, vi, afterEach } from 'vitest'
import { initShareLink } from './share_link.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
it('publishes the current snapshot, copies its exact URL, and revokes that share', async () => {
  document.body.innerHTML = '<button id="menu-file-sharing"></button>'
  const share = { id: 'a'.repeat(32), title: '<b>Part A</b>', url: 'http://192.168.0.15:5182/viewer.html#room=a&invite=b', expiresAt: Date.now() + 60000 }
  const fetch = vi.fn(async path => ({ ok: true, json: async () => path.endsWith('/create') ? share : { shares: [] } }))
  const buffer = new ArrayBuffer(16), exportView = vi.fn().mockResolvedValue({ title: share.title, buffer }), clipboard = { writeText: vi.fn().mockResolvedValue() }
  const ui = initShareLink({ exportView, fetch, clipboard }); document.querySelector('dialog').showModal = vi.fn(); ui.show()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toContain('Host ready'))
  document.querySelector('[data-create]').click()
  await vi.waitFor(() => expect(document.querySelector('section input')?.value).toBe(share.url))
  expect(document.querySelector('section b')).toBeNull()
  expect(fetch.mock.calls.find(([p]) => p.endsWith('/create'))[1].body).toBe(buffer)
  document.querySelector('section button').click()
  await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenCalledWith(share.url))
  document.querySelector('section button:last-child').click()
  await vi.waitFor(() => expect(document.querySelector('section')).toBeNull())
  expect(fetch.mock.calls.at(-1)[0]).toBe(`/__nadoc_share/shares/${share.id}`)
  ui.dispose()
})
it('does not start hosting when the current view cannot be exported', async () => {
  const fetch = vi.fn(), ui = initShareLink({ exportView: async () => { throw new Error('Unsupported representation') }, fetch })
  document.querySelector('[data-create]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toBe('Unsupported representation'))
  expect(fetch).not.toHaveBeenCalled(); expect(document.querySelector('[data-create]').disabled).toBe(false)
  ui.dispose()
})
it('copies a complete internet invitation with a separate password', async () => {
  const share = { id: 'a'.repeat(32), title: 'Voltron', url: 'https://meeting.example/viewer.html#invite=token&password=required', presenterUrl: 'https://meeting.example/viewer.html#invite=presenter-secret&role=presenter', password: 'a-secure-generated-password', expiresAt: Date.now() + 60000 }
  const clipboard = { writeText: vi.fn().mockResolvedValue() }, fetch = vi.fn(async () => ({ ok: true, json: async () => ({ shares: [share] }) }))
  const ui = initShareLink({ exportView: vi.fn(), fetch, clipboard }); document.querySelector('dialog').showModal = vi.fn(); ui.show()
  await vi.waitFor(() => expect(document.querySelector('[data-password]')?.textContent).toContain(share.password))
  ;[...document.querySelectorAll('button')].find(button => button.textContent === 'Copy invitation').click()
  await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenCalledOnce())
  expect(clipboard.writeText.mock.calls[0][0]).toContain(share.url)
  expect(clipboard.writeText.mock.calls[0][0]).toContain(`Meeting password: ${share.password}`)
  expect(clipboard.writeText.mock.calls[0][0]).not.toContain('presenter-secret')
  expect([...document.querySelectorAll('a')].some(link => link.href === share.presenterUrl)).toBe(false)
  expect(document.getElementById('presentation-controls').hidden).toBe(false)
  expect(share.url).not.toContain(share.password); ui.dispose()
})
it('updates an existing invitation without offering a second link', async () => {
  const share = { id: 'a'.repeat(32), title: 'Part', url: 'https://example.invalid/one-link', expiresAt: Date.now() + 60000 }
  const request = vi.fn(async path => ({ ok: true, json: async () => path.endsWith('/content') ? share : { shares: [share], capabilities: ['share-content-v1'] } }))
  const ui = initShareLink({ exportView: async () => ({ title: 'Part', buffer: new ArrayBuffer(16) }), fetch: request })
  document.querySelector('dialog').showModal = vi.fn(); ui.show()
  await vi.waitFor(() => expect(document.querySelector('[data-create]').textContent).toBe('Update shared view'))
  document.querySelector('[data-create]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toContain('same link and sign-in'))
  expect(request.mock.calls.some(([p]) => p === `/__nadoc_share/shares/${share.id}/content`)).toBe(true)
  expect(request.mock.calls.some(([p]) => p.endsWith('/create'))).toBe(false)
  expect(document.querySelectorAll('[data-links] section')).toHaveLength(1)
  expect(document.querySelector('section input').value).toBe(share.url)
  expect([...document.querySelector('[data-target]').options].map(option => option.value)).toEqual([share.id])
  ui.dispose()
})

it('ends hosting from the persistent canvas controls and keeps them on a failed request', async () => {
  document.body.innerHTML = '<div id="canvas-area"></div>'
  let fails = true
  const fetch = vi.fn(async path => ({ ok: !path.endsWith('/stop') || !fails, json: async () => path.endsWith('/stop') ? { error: 'Host unavailable' } : { shares: [{ id: 'room', title: 'Part', expiresAt: Date.now() + 60000 }] } }))
  const ui = initShareLink({ exportView: vi.fn(), fetch }); document.querySelector('dialog').showModal = vi.fn(); ui.show()
  const bar = document.querySelector('#canvas-area #presentation-controls')
  await vi.waitFor(() => expect(bar.hidden).toBe(false))
  bar.querySelector('[data-end-presentation]').click()
  await vi.waitFor(() => expect(bar.textContent).toContain('Host unavailable'))
  expect(bar.hidden).toBe(false)
  fails = false; bar.querySelector('[data-end-presentation]').click()
  await vi.waitFor(() => expect(bar.hidden).toBe(true))
  expect(fetch.mock.calls.at(-1)).toEqual(['/__nadoc_share/stop', { method: 'POST', headers: { 'X-NADOC-Share': '1' } }])
  ui.dispose()
})

it('mirrors native view tools on the same invitation while camera sharing is off', async () => {
  vi.useFakeTimers()
  const share = { id: 'a'.repeat(32), title: 'Part', url: 'https://example.test/part', expiresAt: Date.now() + 60000 }
  const caps = ['share-content-v1', 'editor-broadcast-v1']
  let hosted = false
  const request = vi.fn(async path => ({ ok: true, json: async () => {
    if (path.endsWith('/create')) { hosted = true; return share }
    if (path.endsWith('/content')) return share
    return { capabilities: caps, shares: hosted ? [share] : [] }
  } }))
  const view = { viewTools: { sequences: false } }
  const prepared = { captureView: () => ({ scene: { uuid: 'native' }, view }), exportView: vi.fn(async () => ({ title: 'Part', buffer: new ArrayBuffer(16) })) }
  const state = { currentDesign: { id: 'part' } }
  const store = { getState: () => state, subscribe: () => () => {} }
  const ui = initShareLink({ exportView: prepared.exportView, broadcast: { prepared, store }, fetch: request })
  try {
    document.getElementById('share-link-dialog').showModal = vi.fn(); ui.show()
    await vi.advanceTimersByTimeAsync(0)
    document.querySelector('[data-create]').click(); await vi.advanceTimersByTimeAsync(0)
    expect(document.querySelector('.sharing-url').value).toBe(share.url)
    view.viewTools.sequences = true
    await vi.advanceTimersByTimeAsync(1100)
    expect(request.mock.calls.filter(([p]) => p.endsWith('/content'))).toHaveLength(1)
    expect(request.mock.calls.some(([p]) => p.endsWith('/camera') || p.endsWith('/broadcast/start'))).toBe(false)
    expect(document.querySelector('.presentation-perspective').getAttribute('aria-pressed')).toBe('false')
    view.viewTools.sequences = false
    await vi.advanceTimersByTimeAsync(1100)
    expect(request.mock.calls.filter(([p]) => p.endsWith('/content'))).toHaveLength(2)
    expect(document.querySelector('.sharing-url').value).toBe(share.url)
  } finally { ui.dispose(); vi.useRealTimers() }
})

it('creates a fresh invitation when upgrading the host invalidates the selected old link', async () => {
  const old = { id: 'a'.repeat(32), title: 'Part', url: 'https://example.invalid/old', expiresAt: Date.now() + 60000 }
  const fresh = { ...old, id: 'b'.repeat(32), url: 'https://example.invalid/new' }
  const request = vi.fn(async path => ({ ok: true, json: async () => path.endsWith('/create') ? fresh : { shares: path.endsWith('/start') ? [] : [old], capabilities: ['share-content-v1'], updateRequired: path.endsWith('/status') } }))
  const ui = initShareLink({ exportView: async () => ({ title: 'Part', buffer: new ArrayBuffer(16) }), fetch: request })
  document.querySelector('dialog').showModal = vi.fn(); ui.show()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toContain('update required'))
  document.querySelector('[data-create]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toContain('Invitation ready'))
  expect(request.mock.calls.some(([path]) => path.endsWith('/content'))).toBe(false)
  expect(document.querySelectorAll('[data-links] section')).toHaveLength(1)
  expect(document.querySelector('.sharing-url').value).toBe(fresh.url)
  ui.dispose()
})

it('shows the actual host access error instead of the offline invitation hint', async () => {
  const message = 'Share links must be created from NADOC on the hosting PC.'
  const ui = initShareLink({ exportView: vi.fn(), fetch: async () => ({ ok: false, json: async () => ({ error: message }) }) })
  document.querySelector('dialog').showModal = vi.fn(); ui.show()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toBe(message))
  ui.dispose()
})

it('does not publish or claim invitation readiness while public DNS is pending', async () => {
  const request = vi.fn(async () => ({ ok: true, json: async () => ({ publicAccess: { state: 'dns_pending', message: 'Waiting for public DNS', checks: [] }, shares: [] }) }))
  const ui = initShareLink({ exportView: async () => ({ title: 'Part', buffer: new ArrayBuffer(16) }), fetch: request })
  document.querySelector('[data-create]').click()
  await vi.waitFor(() => expect(document.querySelector('[data-status]').textContent).toBe('Waiting for public DNS'))
  expect(request.mock.calls.some(([path]) => path.endsWith('/create'))).toBe(false)
  ui.dispose()
})
