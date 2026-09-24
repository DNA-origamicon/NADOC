import './meeting_presence.css'
import { createMeetingPing } from './meeting_ping.js'

const glasses = '<svg width="20" height="16" viewBox="0 0 24 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 10 4 4h3M22 10l-2-6h-3M9 11c2-2 4-2 6 0"/><rect x="1" y="9" width="8" height="7" rx="3"/><rect x="15" y="9" width="8" height="7" rx="3"/></svg>'
/** Roster and persistent saved guest views; notification animation has its own clock. */
export function mountMeetingPresence({ parent, compact = false, selfId = '', onView = () => {}, ping, document: doc = document, now = Date.now } = {}) {
  const sound = ping ?? createMeetingPing({ document: doc })
  const roster = doc.createElement('div'); roster.className = `meeting-presence${compact ? ' meeting-presence--compact' : ''}`
  roster.setAttribute('role', 'list'); roster.setAttribute('aria-label', 'Guests and shared views'); roster.hidden = true
  parent.append(roster)
  let signature = '', initialized = false, cached = [], context = {}, localHealth = null
  const seen = new Map(), glowing = new Map(), timers = new Set()
  const api = {
    setHealth(value) { localHealth = value; api.update(cached, context) },
    update(participants = [], { serverTime = now() } = {}) {
      cached = participants; context = { serverTime }
      const guests = participants.filter(person => !compact || person.role !== 'presenter').map(person => ({ ...person,
        label: person.id === selfId ? 'Me' : person.role === 'presenter' ? 'Presenter' : String(person.name ?? ''),
        ...(person.id === selfId && localHealth ? { health: localHealth } : {}),
      })).sort((a, b) => Array.from(b.label).length - Array.from(a.label).length || a.label.localeCompare(b.label))
      const next = JSON.stringify(guests)
      if (signature === next) return
      signature = next
      for (const timer of timers) clearTimeout(timer)
      timers.clear()
      let notify = false
      for (const person of guests) {
        const view = person.sharedView
        if (person.id !== selfId && view && seen.get(person.id) !== view.serial) {
          const remaining = Math.max(0, 15000 - Math.max(0, serverTime - view.sharedAt))
          glowing.set(person.id, now() + remaining)
          if (initialized && remaining > 0) notify = true
          seen.set(person.id, view.serial)
        }
      }
      initialized = true
      if (notify) sound.play()
      roster.replaceChildren(...guests.map(person => {
        const item = doc.createElement('span'); item.className = 'meeting-presence-person'; item.setAttribute('role', 'listitem')
        const chip = doc.createElement('span'); chip.className = 'meeting-presence-chip'
        chip.title = `${person.name} · ${person.online === false ? 'Left · Saved view available' : 'Present'}`; chip.setAttribute('aria-label', chip.title)
        const name = String(person.name ?? '')
        chip.textContent = compact ? name.trim().split(/\s+/u).slice(0, 2).map(word => Array.from(word)[0] ?? '').join('').toLocaleUpperCase() : person.label
        if (/^#[a-f0-9]{6}$/i.test(person.color)) { chip.style.backgroundColor = person.color; chip.style.setProperty('--guest-color', person.color) }
        chip.dataset.participantId = person.id
        const remaining = (glowing.get(person.id) ?? 0) - now()
        if (remaining > 0) {
          chip.classList.add('meeting-presence-glow')
          const timer = setTimeout(() => { chip.classList.remove('meeting-presence-glow'); timers.delete(timer) }, remaining); timers.add(timer)
        }
        item.append(chip)
        if (person.sharedView && person.id !== selfId) {
          const button = doc.createElement('button'); button.type = 'button'; button.className = 'meeting-view-glasses'
          button.innerHTML = glasses; button.title = `View ${name}'s shared perspective`; button.setAttribute('aria-label', button.title)
          button.onclick = () => onView(person.sharedView, person)
          item.append(button)
        }
        for (const [kind, slow, title, path] of [
          ['network', person.health?.networkSlow, 'Slow connection or delayed transfers', '<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M9 16a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r="1"/>'],
          ['render', person.health?.renderSlow, 'Slow rendering in this viewer', '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>'],
        ]) if (slow) {
          const icon = doc.createElement('span'); icon.className = 'meeting-health-warning'; icon.dataset.health = kind
          icon.title = title; icon.setAttribute('role', 'img'); icon.setAttribute('aria-label', title)
          icon.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">${path}</svg>`
          item.append(icon)
        }
        return item
      }))
      roster.hidden = !guests.length
    },
    dispose() { for (const timer of timers) clearTimeout(timer); timers.clear(); if (!ping) sound.dispose(); roster.remove() },
  }
  return api
}
