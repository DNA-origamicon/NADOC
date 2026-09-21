import { it, expect, vi, afterEach } from 'vitest'
import { mountMeetingJoin } from './meeting_join.js'
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function setup(responses) {
  document.body.innerHTML = '<label class="open"></label><dialog id="join"><form id="join-form"><input id="guest-name" value="Alice"><p id="join-error"></p><button id="join-submit"></button></form></dialog><p id="status"></p><span id="guest"></span>'
  const dialog = document.querySelector('dialog'); dialog.showModal = vi.fn(); dialog.close = vi.fn()
  const fetch = vi.fn(); for (const response of responses) fetch.mockResolvedValueOnce(response)
  const viewer = { loadFile: vi.fn().mockResolvedValue(true) }, repeat = vi.fn(() => 1), cancel = vi.fn()
  const dispose = mountMeetingJoin({ viewer, fetch, location: { hash: '#invite=secret' }, setInterval: repeat, clearInterval: cancel })
  const submit = () => document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
  return { viewer, fetch, dialog, submit, dispose, repeat, cancel }
}
it('loads only after successful join, shows a safe name, and cancels monitoring on disposal', async () => {
  const v = setup([{ ok: true, json: async () => ({ name: '<b>Alice</b>' }) }, { ok: true, headers: new Headers({ 'Content-Length': '8' }), blob: async () => new Blob(['NADOCVW1']) }])
  v.submit()
  await vi.waitFor(() => expect(v.viewer.loadFile).toHaveBeenCalledOnce())
  expect(v.dialog.close).toHaveBeenCalledOnce()
  expect(document.querySelector('#guest').textContent).toContain('<b>Alice</b>')
  expect(document.querySelector('#guest b')).toBeNull()
  expect(JSON.parse(v.fetch.mock.calls[0][1].body)).toEqual({ token: 'secret', name: 'Alice' })
  v.dispose(); expect(v.cancel).toHaveBeenCalledWith(1)
  expect(v.fetch.mock.calls[0][1].signal.aborted).toBe(true)
})
it('keeps the prompt open and permits retry after a denied join', async () => {
  const v = setup([{ ok: false, json: async () => ({ error: 'Session full' }) }]); v.submit()
  await vi.waitFor(() => expect(document.querySelector('#join-error').textContent).toBe('Session full'))
  expect(v.viewer.loadFile).not.toHaveBeenCalled(); expect(v.dialog.close).not.toHaveBeenCalled()
  expect(document.querySelector('button').disabled).toBe(false); v.dispose()
})
it('keeps monitoring across transient outages and stops only on confirmed revocation', async () => {
  const v = setup([{ ok: true, json: async () => ({ name: 'Alice' }) }, { ok: true, headers: new Headers({ 'Content-Length': '8' }), blob: async () => new Blob(['NADOCVW1']) }])
  v.submit(); await vi.waitFor(() => expect(v.repeat).toHaveBeenCalledOnce())
  const poll = v.repeat.mock.calls[0][0]
  v.fetch.mockRejectedValueOnce(new Error('Network down')); await poll()
  expect(document.querySelector('#guest').textContent).toContain('reconnecting')
  expect(v.cancel).not.toHaveBeenCalled()
  v.fetch.mockResolvedValueOnce({ ok: true }); await poll()
  expect(document.querySelector('#guest').textContent).toBe('Alice · Private test')
  v.fetch.mockResolvedValueOnce({ ok: false, status: 410 }); await poll()
  expect(v.cancel).toHaveBeenCalledWith(1); expect(document.querySelector('#guest').textContent).toContain('Session ended')
  v.dispose()
})
it('does not dismiss the join prompt when package decoding fails', async () => {
  const v = setup([{ ok: true, json: async () => ({ name: 'Alice' }) }, { ok: true, headers: new Headers({ 'Content-Length': '8' }), blob: async () => new Blob(['NADOCVW1']) }])
  v.viewer.loadFile.mockResolvedValue(false); v.submit()
  await vi.waitFor(() => expect(document.querySelector('#join-error').textContent).toContain('Could not open'))
  expect(v.dialog.close).not.toHaveBeenCalled(); v.dispose()
})

it('reopens the join flow when a different part invite changes the fragment', async () => {
  const { mountMeetingInvites } = await import('./meeting_join.js')
  document.body.innerHTML = '<label class="open"></label><dialog id="join"><form id="join-form"><input id="guest-name" value="Alice"><p id="join-error"></p><button id="join-submit"></button></form></dialog><p id="status"></p><span id="guest"></span>'
  const dialog = document.querySelector('dialog'); dialog.showModal = vi.fn(); dialog.close = vi.fn()
  const host = new EventTarget(); host.location = { hash: '#room=' + 'a'.repeat(32) + '&invite=first' }
  const request = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Test denial' }) })
  const dispose = mountMeetingInvites({ viewer: {}, window: host, fetch: request })
  host.location.hash = '#room=' + 'b'.repeat(32) + '&invite=second'; host.dispatchEvent(new Event('hashchange'))
  document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())
  expect(request.mock.calls[0][0]).toBe('/meeting/' + 'b'.repeat(32) + '/join')
  expect(JSON.parse(request.mock.calls[0][1].body).token).toBe('second')
  expect(dialog.showModal).toHaveBeenCalledTimes(2)
  dispose(); host.dispatchEvent(new Event('hashchange')); expect(dialog.showModal).toHaveBeenCalledTimes(2)
})
it('asks for the meeting password and transmits it only in the join request body', async () => {
  document.body.innerHTML = '<label class="open"></label><dialog id="join"><form id="join-form"><input id="guest-name" value="Alice"><div id="meeting-password-row" hidden><input id="meeting-password"></div><p id="join-error"></p><button id="join-submit"></button></form></dialog><p id="status"></p><span id="guest"></span>'
  document.querySelector('dialog').showModal = vi.fn()
  const request = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Incorrect meeting password.' }) })
  const dispose = mountMeetingJoin({ viewer: {}, fetch: request, location: { hash: '#invite=token&password=required' } })
  expect(document.querySelector('#meeting-password-row').hidden).toBe(false)
  expect(document.querySelector('#meeting-password').required).toBe(true)
  document.querySelector('#meeting-password').value = 'test-password'
  document.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())
  expect(JSON.parse(request.mock.calls[0][1].body).password).toBe('test-password')
  expect(request.mock.calls[0][0]).not.toContain('test-password'); dispose()
})
