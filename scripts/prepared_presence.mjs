import { validateSharedCamera } from './prepared_camera.mjs'
import { randomBytes, randomInt } from 'node:crypto'

const COLORS = ['#a8d8ff', '#ffc9a8', '#c9b8ff', '#a8e6cf', '#ffb8d2', '#eadb92']
/** Public display identities never expose the cookie used to authenticate a guest. */
export function createRoomPresence({ presentation, now = Date.now }) {
  const connected = new Map(), saved = new Map()
  let serial = 0
  const publish = () => {
    const roster = new Map([...saved].map(([id, record]) => [id, { ...record, online: connected.has(id) }]))
    for (const { session } of connected.values()) if (session.role === 'guest') roster.set(session.participantId, {
      id: session.participantId, name: session.name, color: session.color, online: true, ...(session.health ? { health: { networkSlow: session.health.networkSlow, renderSlow: session.health.renderSlow } } : {}), ...(saved.get(session.participantId)?.sharedView ? { sharedView: saved.get(session.participantId).sharedView } : {}),
    })
    roster.set('presenter', { id: 'presenter', role: 'presenter', name: 'Presenter', color: '#a8d8ff', online: true })
    presentation.setParticipants([...roster.values()])
  }
  return {
    identify(session) {
      if (!session.participantId) {
        session.participantId = randomBytes(12).toString('hex')
        const used = new Set([...connected.values()].map(item => item.session.color))
        const available = COLORS.filter(color => !used.has(color))
        const palette = available.length ? available : COLORS
        session.color = palette[randomInt(palette.length)]
      }
      return session.participantId
    },
    health(session, value) {
      if (session.role !== 'guest' || !connected.has(session.participantId)) throw new Error('Join the presentation before reporting status')
      if (!value || Object.keys(value).some(key => !['networkSlow', 'renderSlow'].includes(key)) || typeof value.networkSlow !== 'boolean' || typeof value.renderSlow !== 'boolean') throw new Error('Only connection and rendering status flags are accepted')
      if (session.health && now() - session.health.updatedAt < 2000) throw new Error('Status update too frequent')
      session.health = { networkSlow: value.networkSlow, renderSlow: value.renderSlow, updatedAt: now() }; publish()
      return { ok: true }
    },
    expireHealth() {
      let changed = false
      for (const { session } of connected.values()) if (session.health && now() - session.health.updatedAt > 30000) { delete session.health; changed = true }
      if (changed) publish()
    },
    share(session, value) {
      const state = presentation.snapshot()
      if (state.ended) throw new Error('Presentation ended')
      if (session.role !== 'guest' || !connected.has(session.participantId)) throw new Error('Join the presentation before sharing a view')
      if (value?.revision !== state.revision) throw new Error('Wait for the latest visualization before sharing your view')
      const previous = saved.get(session.participantId)
      if (previous && now() - previous.sharedView.sharedAt < 1000) throw new Error('Please wait a moment before sharing again')
      const camera = validateSharedCamera(value.camera)
      // Keep one pose per guest for this presentation, including after disconnect.
      if (!previous && saved.size >= 128) throw new Error('Saved guest view capacity reached')
      saved.set(session.participantId, { id: session.participantId, name: session.name, color: session.color,
        sharedView: { camera, revision: value.revision, serial: ++serial, sharedAt: now() } })
      publish()
      return { ok: true }
    },
    connect(session, response) {
      this.identify(session)
      const entry = connected.get(session.participantId) ?? { session, streams: new Set() }
      entry.session = session; entry.streams.add(response); connected.set(session.participantId, entry)
      response.once('close', () => {
        entry.streams.delete(response)
        if (!entry.streams.size) connected.delete(session.participantId)
        publish()
      })
      publish()
    },
  }
}
