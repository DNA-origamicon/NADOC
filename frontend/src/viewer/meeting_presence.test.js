import { it, expect, afterEach } from 'vitest'
import { mountMeetingPresence } from './meeting_presence.js'
afterEach(() => { document.body.innerHTML = '' })
it('shows self and other guests by safe display name and stable color, removes leavers, and cleans up', () => {
  const ui = mountMeetingPresence({ parent: document.body, selfId: 'self' })
  const alice = { id: 'a', name: '<img onerror=alert(1)>', color: '#a8d8ff' }
  ui.update([{ id: 'self', name: 'Me' }, alice])
  expect(document.querySelectorAll('.meeting-presence-chip')).toHaveLength(2)
  expect(document.querySelector('img')).toBeNull()
  expect(document.querySelector('.meeting-presence-chip').textContent).toBe(alice.name)
  const chip = document.querySelector('.meeting-presence-chip')
  ui.update([alice]); expect(document.querySelector('.meeting-presence-chip').textContent).toBe(chip.textContent)
  ui.update([]); expect(document.querySelector('.meeting-presence').hidden).toBe(true)
  ui.dispose(); expect(document.querySelector('.meeting-presence')).toBeNull()
})
it('uses initials for compact host icons with the complete name in a tooltip', () => {
  const ui = mountMeetingPresence({ parent: document.body, compact: true })
  ui.update([{ id: 'a', name: 'Ada Lovelace', color: '#ffc9a8' }])
  const chip = document.querySelector('.meeting-presence-chip')
  expect(chip.textContent).toBe('AL'); expect(chip.title).toBe('Ada Lovelace · Present')
})

it('pings only new shares, restarts a 15-second glow, retains glasses and opens the latest pose', async () => {
  const { vi } = await import('vitest'); vi.useFakeTimers()
  try {
    const ping = { play: vi.fn() }, onView = vi.fn(), ui = mountMeetingPresence({ parent: document.body, ping, onView })
    const person = { id: 'a', name: 'Ada', color: '#ffc9a8' }
    ui.update([person])
    const first = { serial: 1, sharedAt: Date.now(), camera: { position: [1, 2, 3] } }
    ui.update([{ ...person, sharedView: first }]); expect(ping.play).toHaveBeenCalledOnce()
    expect(document.querySelector('.meeting-presence-glow')).not.toBeNull()
    vi.advanceTimersByTime(10000)
    ui.update([{ ...person, sharedView: first }]); expect(ping.play).toHaveBeenCalledOnce()
    const second = { ...first, serial: 2, sharedAt: Date.now() }
    ui.update([{ ...person, sharedView: second }]); expect(ping.play).toHaveBeenCalledTimes(2)
    vi.advanceTimersByTime(14999); expect(document.querySelector('.meeting-presence-glow')).not.toBeNull()
    vi.advanceTimersByTime(1); expect(document.querySelector('.meeting-presence-glow')).toBeNull()
    document.querySelector('.meeting-view-glasses').click(); expect(onView.mock.calls[0][0]).toBe(second)
    ui.dispose(); expect(vi.getTimerCount()).toBe(0)
  } finally { vi.useRealTimers() }
})

it('orders longest labels first including Me and Presenter, with local health warnings and glasses to the right', () => {
  const ui = mountMeetingPresence({ parent: document.body, selfId: 'self' })
  ui.update([{ id: 'self', name: 'A long private name' }, { id: 'presenter', role: 'presenter', name: 'Presenter' }, { id: 'other', name: 'Grace Hopper', sharedView: { serial: 1, sharedAt: 0 } }])
  expect([...document.querySelectorAll('.meeting-presence-chip')].map(node => node.textContent)).toEqual(['Grace Hopper', 'Presenter', 'Me'])
  ui.setHealth({ networkSlow: true, renderSlow: true })
  const me = document.querySelector('[data-participant-id="self"]').parentElement
  expect(me.querySelectorAll('.meeting-health-warning')).toHaveLength(2)
  expect(me.querySelector('.meeting-view-glasses')).toBeNull()
  expect(document.querySelector('[data-participant-id="other"]').nextElementSibling.className).toBe('meeting-view-glasses')
  ui.setHealth({ networkSlow: false, renderSlow: false })
  expect(me.isConnected).toBe(false)
  expect(document.querySelector('.meeting-health-warning')).toBeNull(); ui.dispose()
})
