import { it, expect, vi, afterEach } from 'vitest'
import { initShareLink } from './share_link.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
const share = { id: 'a'.repeat(32), title: 'Part', url: 'https://example.test/viewer.html#invite=guest&password=required', password: 'guest-password', expiresAt: Date.now() + 60000 }
const el = selector => document.querySelector(selector)
function setup({ exportView = vi.fn(async () => ({ title: 'Part', buffer: new ArrayBuffer(16) })), fetch, clipboard = { writeText: vi.fn().mockResolvedValue() } } = {}) {
  const request = fetch ?? vi.fn(async path => ({ ok: true, json: async () => path.endsWith('/create') ? share : { running: false, shares: [] } }))
  const ui = initShareLink({ exportView, fetch: request, clipboard })
  el('dialog').showModal = vi.fn()
  return { ui, request, clipboard }
}
it('switches create/stop availability, copies a usable guest link, and resets after stopping', async () => {
  const { ui, request, clipboard } = setup()
  expect(el('[data-stop-host]').disabled).toBe(true)
  expect(el('[data-copy-link]')).toBeNull()
  ui.show()
  await vi.waitFor(() => expect(el('[data-create]').disabled).toBe(false))
  expect(el('[data-status]').textContent).toBe('')
  el('[data-create]').click()
  await vi.waitFor(() => expect(el('[data-stop-host]').disabled).toBe(false))
  expect(el('[data-create]').disabled).toBe(true)
  expect([...el('dialog').querySelectorAll('button')].map(b => b.getAttribute('aria-label') || b.textContent)).toEqual(['Close', 'Enable link', 'End presentation', 'Copy link', 'Copy password'])
  expect(el('select, textarea, [data-clip-options]')).toBeNull()
  el('[data-copy-link]').click()
  await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenCalledOnce())
  const copied = new URL(clipboard.writeText.mock.calls[0][0])
  expect(copied.href).toBe(share.url)
  expect(el('[data-link]').value).toBe(share.url)
  expect(el('[data-password]').value).toBe(share.password)
  expect(copied.search).not.toContain(share.password)
  expect(copied.hash).toContain('invite=guest')
  el('[data-copy-password]').click()
  await vi.waitFor(() => expect(clipboard.writeText).toHaveBeenLastCalledWith(share.password))
  expect(el('[data-status]').textContent).toBe('Password copied')
  el('[data-stop-host]').click()
  await vi.waitFor(() => expect(el('[data-create]').disabled).toBe(false))
  expect(el('[data-stop-host]').disabled).toBe(true)
  expect(el('[data-copy-link]')).toBeNull()
  expect(el('[data-copy-password]')).toBeNull()
  expect(request.mock.calls.at(-1)[0]).toBe('/__nadoc_share/stop')
  ui.dispose()
})
it('restores an existing link without offering replacement or another invitation', async () => {
  const { ui, request } = setup({ fetch: vi.fn(async () => ({ ok: true, json: async () => ({ shares: [share] }) })) })
  ui.show()
  await vi.waitFor(() => expect(el('[data-copy-link]')).not.toBeNull())
  expect(el('[data-create]').disabled).toBe(true)
  expect(el('[data-stop-host]').disabled).toBe(false)
  el('[data-create]').click()
  expect(request).toHaveBeenCalledOnce()
  ui.dispose()
})
it('keeps export failures in a collapsed error log and permits retry', async () => {
  const { ui, request } = setup({ exportView: async () => { throw new Error('<b>Unsupported representation</b>') } })
  el('[data-create]').click()
  await vi.waitFor(() => expect(el('[data-error]').hidden).toBe(false))
  expect(el('[data-error]').open).toBe(false)
  expect(el('[data-error-log]').textContent).toBe('<b>Unsupported representation</b>')
  expect(el('[data-error-log] b')).toBeNull()
  expect(el('[data-status]').textContent).toBe('')
  expect(request).not.toHaveBeenCalled()
  expect(el('[data-create]').disabled).toBe(false)
  expect(el('[data-stop-host]').disabled).toBe(true)
  ui.dispose()
})
it('keeps an active link when stopping fails and reports the error', async () => {
  const { ui } = setup({ fetch: async path => ({ ok: !path.endsWith('/stop'), json: async () => path.endsWith('/stop') ? { error: 'Host unavailable' } : { shares: [share] } }) })
  ui.show()
  await vi.waitFor(() => expect(el('[data-stop-host]').disabled).toBe(false))
  el('[data-stop-host]').click()
  await vi.waitFor(() => expect(el('[data-error-log]').textContent).toBe('Host unavailable'))
  expect(el('[data-create]').disabled).toBe(true)
  expect(el('[data-stop-host]').disabled).toBe(false)
  expect(el('[data-copy-link]')).not.toBeNull()
  ui.dispose()
})
it('reports clipboard failures without discarding the link', async () => {
  const { ui } = setup({ clipboard: { writeText: async () => { throw new Error('Permission denied') } } })
  el('[data-create]').click()
  await vi.waitFor(() => expect(el('[data-copy-link]')).not.toBeNull())
  el('[data-copy-link]').click()
  await vi.waitFor(() => expect(el('[data-error-log]').textContent).toContain('Permission denied'))
  expect(el('[data-error]').open).toBe(false)
  expect(el('[data-copy-link]')).not.toBeNull()
  ui.dispose()
})
it('waits for public access before enabling stop or showing copy', async () => {
  const { ui, request } = setup({ fetch: vi.fn(async () => ({ ok: true, json: async () => ({ publicAccess: { state: 'dns_pending', message: 'Waiting for public DNS' }, shares: [] }) })) })
  el('[data-create]').click()
  await vi.waitFor(() => expect(el('[data-status]').textContent).toBe('Waiting for public DNS'))
  expect(el('[data-create]').disabled).toBe(true)
  expect(el('[data-stop-host]').disabled).toBe(true)
  expect(el('[data-copy-link]')).toBeNull()
  expect(request.mock.calls.some(([path]) => path.endsWith('/create'))).toBe(false)
  ui.dispose()
})
it('releases Enable link after a stalled connection without publishing a late response', async () => {
  vi.useFakeTimers()
  let release
  const { ui, request } = setup({ fetch: vi.fn(() => new Promise(resolve => { release = resolve })) })
  try {
    el('[data-create]').click()
    await vi.advanceTimersByTimeAsync(0)
    expect(el('[data-status]').textContent).toBe('Connecting internet sharing…')
    await vi.advanceTimersByTimeAsync(15 * 60 * 1000)
    expect(el('[data-create]').disabled).toBe(false)
    expect(el('[data-error-log]').textContent).toContain('keep checking in the background')
    release({ ok: true, json: async () => ({ publicAccess: { state: 'ready' } }) })
    await vi.advanceTimersByTimeAsync(0)
    expect(request).toHaveBeenCalledTimes(1)
    expect(el('[data-copy-link]')).toBeNull()
  } finally { ui.dispose(); vi.useRealTimers() }
})
it('shows status failures without clearing an existing link', async () => {
  let fails = false
  const { ui } = setup({ fetch: async () => { if (fails) throw new Error('Network down'); return { ok: true, json: async () => ({ shares: [share] }) } } })
  ui.show(); await vi.waitFor(() => expect(el('[data-copy-link]')).not.toBeNull())
  fails = true; ui.show()
  await vi.waitFor(() => expect(el('[data-error-log]').textContent).toBe('Network down'))
  expect(el('[data-create]').disabled).toBe(true)
  expect(el('[data-stop-host]').disabled).toBe(false)
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
    expect(document.querySelector('[data-copy-link]')).not.toBeNull()
    view.viewTools.sequences = true
    await vi.advanceTimersByTimeAsync(1100)
    expect(request.mock.calls.filter(([p]) => p.endsWith('/content'))).toHaveLength(1)
    expect(request.mock.calls.some(([p]) => p.endsWith('/camera') || p.endsWith('/broadcast/start'))).toBe(false)
    expect(document.querySelector('.presentation-perspective').getAttribute('aria-pressed')).toBe('false')
    view.viewTools.sequences = false
    await vi.advanceTimersByTimeAsync(1100)
    expect(request.mock.calls.filter(([p]) => p.endsWith('/content'))).toHaveLength(2)
    expect(document.querySelector('[data-copy-link]')).not.toBeNull()
  } finally { ui.dispose(); vi.useRealTimers() }
})

it('revokes guests when the part closes and does not shut down the public gateway', async () => {
  const { ui, request } = setup()
  el('[data-create]').click()
  await vi.waitFor(() => expect(el('[data-link]')).not.toBeNull())
  window.dispatchEvent(new Event('nadoc:document-reset'))
  await vi.waitFor(() => expect(request).toHaveBeenCalledWith(`/__nadoc_share/shares/${share.id}`, expect.objectContaining({ method: 'DELETE', keepalive: true })))
  expect(el('[data-link]')).toBeNull()
  expect(request.mock.calls.some(([url]) => url.endsWith('/stop'))).toBe(false)
  ui.dispose()
})

it('revokes a late publication when its part closes during upload', async () => {
  let release
  const request = vi.fn(async path => path.endsWith('/create') ? new Promise(resolve => { release = resolve }) : { ok: true, json: async () => ({ shares: [], publicAccess: { state: 'ready' } }) })
  const { ui } = setup({ fetch: request })
  el('[data-create]').click()
  await vi.waitFor(() => expect(release).toBeTypeOf('function'))
  window.dispatchEvent(new Event('nadoc:document-reset'))
  release({ ok: true, json: async () => share })
  await vi.waitFor(() => expect(request).toHaveBeenCalledWith(`/__nadoc_share/shares/${share.id}`, expect.objectContaining({ method: 'DELETE' })))
  expect(el('[data-link]')).toBeNull(); expect(el('[data-create]').disabled).toBe(false)
  ui.dispose()
})

it('closing a part during status refresh leaves Enable link usable and ignores the old status', async () => {
  let release
  const { ui } = setup({ fetch: () => new Promise(resolve => { release = resolve }) })
  ui.show()
  expect(el('[data-create]').disabled).toBe(true)
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(el('[data-create]').disabled).toBe(false)
  release({ ok: true, json: async () => ({ shares: [share] }) })
  await Promise.resolve(); await Promise.resolve()
  expect(el('[data-link]')).toBeNull(); expect(el('[data-create]').disabled).toBe(false)
  ui.dispose()
})
