import { afterEach, expect, it } from 'vitest'
import { mountMeetingPassword } from './meeting_password.js'
afterEach(() => { document.body.innerHTML = '' })
it('leaves QR entry credential-free, supports protected links, and removes credentials before reuse', () => {
  document.body.innerHTML = '<form><input id="guest-name"><p id="join-error"></p></form>'
  const qr = mountMeetingPassword({ required: false })
  expect(document.querySelectorAll('input').length).toBe(1)
  expect(qr.field).toBeNull()
  qr.dispose()
  const protectedLink = mountMeetingPassword({ required: true })
  expect(protectedLink.field.type).toBe('password')
  expect(protectedLink.field.required).toBe(true)
  expect(protectedLink.field.labels[0].textContent).toBe('Meeting password')
  expect(protectedLink.field.closest('form')).not.toBeNull()
  protectedLink.field.value = 'private'
  protectedLink.dispose()
  expect(protectedLink.field.value).toBe('')
  mountMeetingPassword({ required: false })
  expect(document.querySelector('input[type=password]')).toBeNull()
})
