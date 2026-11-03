import { it, expect } from 'vitest'
import { createGuestInvitationPrint, createGuestQR } from './meeting_target.js'
const url = 'https://example.test/viewer.html?view=abc#room=abc&invite=guest&password=required'
it('prints a guest QR without spatial markers or tracking instructions', () => {
  const text = createGuestInvitationPrint({ url, title: '<script>alert(1)</script>' })
  const svg = new DOMParser().parseFromString(text, 'image/svg+xml')
  expect(svg.querySelector('[data-guest-invitation]').getAttribute('width')).toBe('150')
  expect(svg.querySelector('script, [data-room-marker], [data-mobile-marker]')).toBeNull()
  expect(text).not.toMatch(/qrmm|tracking|calibrat/i)
  expect(svg.documentElement.getAttribute('width')).toBe('190mm')
})
it('encodes guest invitations only and rejects unsafe or presenter URLs', () => {
  for (const value of ['', 'javascript:alert(1)', 'data:text/html,test', 'https://user:secret@example.test/#invite=guest', url + '&role=presenter']) {
    expect(() => createGuestQR(value)).toThrow()
    expect(() => createGuestInvitationPrint({ url: value })).toThrow()
  }
  expect(createGuestQR(url)).toContain('viewBox=')
})
