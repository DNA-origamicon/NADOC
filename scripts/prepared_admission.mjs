/** Host-wide admission authority. Only browser acknowledgements renew leases. */
export function createAdmission({ rooms, maxGuests, now, disconnect }) {
  const records = () => [...rooms.values()].flatMap(room => [...room.sessions.entries()].filter(([, s]) => s.role === 'guest').map(([id, s]) => ({ room, id, s })))
  const waiting = () => records().filter(({s}) => s.admission === 'waiting').sort((a,b) => a.s.queuedAt-b.s.queuedAt || a.s.order-b.s.order)
  let serial = 0
  const occupied = () => records().filter(({s}) => ['active','offered'].includes(s.admission)).length
  function release(s, reason) {
    s.admission = 'released'; s.reason = reason; s.releasedAt = now(); s.promptAt = null; s.offerUntil = null
    disconnect(s)
  }
  function activate(s) {
    s.admission = 'active'; s.admittedAt = now(); s.activityAt = now(); s.ackAt = now(); s.promptAt = null; s.reason = null; s.offerUntil = null
  }
  function sweep() {
    for (const {room,id,s} of records()) {
      if (s.admission === 'released') { if (now()-s.releasedAt > 600000) room.sessions.delete(id); continue }
      if (now()-s.ackAt > (s.admission === 'waiting' ? 90000 : 120000)) { release(s, 'disconnected'); continue }
      if (s.hiddenAt != null && now()-s.hiddenAt >= 120000) { release(s, 'background'); continue }
      if (s.admission === 'offered' && now() >= s.offerUntil) { release(s, 'offer-expired'); continue }
      if (s.admission === 'active' && s.promptAt != null && now()-s.promptAt >= 30000) release(s, 'inactive')
    }
    const queue = waiting()
    for (const {s} of records()) if (s.admission === 'active') {
      if (!queue.length) s.promptAt = null
      else if (s.hiddenAt == null && now()-s.activityAt >= 300000 && s.promptAt == null) s.promptAt = now()
    }
    for (const {s} of queue) {
      if (occupied() >= maxGuests) break
      if (s.hiddenAt != null || now()-s.ackAt > 30000) continue
      s.admission = 'offered'; s.offerUntil = now()+30000
    }
  }
  function enroll(s) {
    sweep()
    if (['active','waiting','offered'].includes(s.admission)) return
    if (records().filter(({s}) => s.admission === 'waiting').length >= 256) throw new Error('The waiting list is full. Please try again shortly.')
    Object.assign(s, { ackAt: now(), activityAt: now(), hiddenAt: null, queuedAt: now(), order: ++serial, reason: null, promptAt: null })
    if (occupied() < maxGuests && !waiting().length) activate(s)
    else s.admission = 'waiting'
  }
  function pulse(s, value) {
    sweep()
    if (s.admission === 'released') return status(s)
    s.ackAt = now()
    if (value.visible === false) { s.hiddenAt ??= now(); disconnect(s) }
    else if (value.visible === true) s.hiddenAt = null
    if (value.active === true && value.visible === true) { s.activityAt = now(); s.promptAt = null }
    if (value.action === 'leave') release(s, 'left')
    if (value.action === 'accept' && s.admission === 'offered' && s.hiddenAt == null) activate(s)
    sweep(); return status(s)
  }
  function status(s) {
    return { state: s.admission, reason: s.reason, position: s.admission === 'waiting' ? waiting().findIndex(v => v.s === s)+1 : null,
      offerUntil: s.offerUntil, promptUntil: s.promptAt == null ? null : s.promptAt+30000, serverTime: now(), capacity: maxGuests }
  }
  function summary(room) {
    const list = records().filter(v => v.room === room)
    return { displays: [...(room.sessions?.values() ?? [])].filter(s => s.role === 'display').length, capacity: maxGuests, occupied: occupied(), active: list.filter(v => v.s.admission === 'active').length,
      waiting: list.filter(v => ['waiting','offered'].includes(v.s.admission)).length,
      guests: list.filter(v => v.s.admission === 'active').sort((a,b) => a.s.admittedAt-b.s.admittedAt).map(({s}) => ({ id: s.participantId, name: s.name, admittedAt: s.admittedAt })) }
  }
  function rotate(room) {
    sweep()
    const queue = records().filter(v => v.room === room && ['waiting','offered'].includes(v.s.admission) && v.s.hiddenAt == null && now()-v.s.ackAt <= 30000).sort((a,b) => a.s.queuedAt-b.s.queuedAt || a.s.order-b.s.order)
    const active = records().filter(v => v.room === room && v.s.admission === 'active').sort((a,b) => a.s.admittedAt-b.s.admittedAt || a.s.order-b.s.order)
    const needed = queue.length ? Math.max(0, Math.min(queue.length,maxGuests) - (maxGuests-occupied()) - queue.filter(v => v.s.admission === 'offered').length) : 1
    const removed = active.slice(0,needed)
    for (const {s} of removed) release(s, 'rotated')
    let admitted = 0
    for (const {s} of queue) {
      if (s.admission !== 'offered' && occupied() >= maxGuests) break
      activate(s); admitted++
    }
    sweep(); return { removed: removed.length, admitted, ...summary(room) }
  }
  return { enroll, pulse, sweep, status, summary, rotate, release, active: s => s?.role === 'presenter' || (s?.admission === 'active' && s.hiddenAt == null) }
}
