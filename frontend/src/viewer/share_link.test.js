import { it, expect, vi, afterEach } from 'vitest'
import { initShareLink } from './share_link.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
it('publishes the current snapshot, copies its exact URL, and revokes that share', async () => {
  document.body.innerHTML = '<button id="menu-help-share-link"></button>'
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
  expect([...document.querySelectorAll('a')].find(link => link.textContent === 'Open presenter').href).toBe(share.presenterUrl)
  expect(share.url).not.toContain(share.password); ui.dispose()
})
it('updates an existing invitation through the same publish button and keeps new invitations explicit', async () => {
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
  const target = document.querySelector('[data-target]'); target.value = ''; target.dispatchEvent(new Event('change'))
  expect(document.querySelector('[data-create]').textContent).toBe('Create link for current view')
  ui.dispose()
})
