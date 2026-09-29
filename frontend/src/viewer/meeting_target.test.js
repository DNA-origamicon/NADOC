import { it, expect } from 'vitest'
import { createMeetingTarget, createGuestQR, ROOM_MARKER } from './meeting_target.js'

const url = 'https://example.test/viewer.html?view=abc#room=abc&invite=guest&password=required'
it('prints a fixed physical marker independently of the active invitation', () => {
  const a = createMeetingTarget({ url }), b = createMeetingTarget({ url: url.replace('guest', 'next-guest') })
  const parse = text => new DOMParser().parseFromString(text, 'image/svg+xml')
  const marker = svg => parse(svg).querySelector('[data-room-marker]')
  expect(marker(a).outerHTML).toBe(marker(b).outerHTML)
  expect(marker(a).getAttribute('width')).toBe('187.5')
  expect(marker(a).getAttribute('viewBox')).toBe('0 0 10 10')
  expect(ROOM_MARKER).toMatchObject({ family: 'tag36h11', id: 0, sizeMeters: .15 })
  expect(parse(a).documentElement.getAttribute('width')).toBe('190mm')
  expect(a).toContain('100 mm')
  expect(a).not.toContain('guest-password')
})
it('encodes guest invitations only and rejects unsafe or presenter URLs', () => {
  for (const value of ['', 'javascript:alert(1)', 'data:text/html,test', 'https://user:secret@example.test/#invite=guest', url + '&role=presenter']) {
    expect(() => createGuestQR(value)).toThrow()
  }
  expect(createGuestQR(url)).toContain('viewBox=')
})
it('keeps untrusted titles out of SVG markup and explains the prototype scope', () => {
  const svg = createMeetingTarget({ url, title: '<script>alert(1)</script>' })
  expect(new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('script')).toBeNull()
  expect(svg).toContain('Print at 100%')
})
it('prints a large QR with a measured-size hint for automatic phone setup', async () => {
  const { createMobileTrackingTarget } = await import('./meeting_target.js')
  const svg = new DOMParser().parseFromString(createMobileTrackingTarget({ url: url.replace('&password=required', '&entry=qr') }), 'image/svg+xml')
  expect(svg.querySelector('[data-mobile-marker]').getAttribute('width')).toBe('150')
  expect(svg.documentElement.textContent).toContain('150 mm')
})
