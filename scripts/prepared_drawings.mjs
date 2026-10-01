import { validateSharedCamera } from './prepared_camera.mjs'
import { drawingPoints, DRAW_LIFETIME_MS } from '../frontend/src/viewer/meeting_drawing_protocol.js'

/** Ephemeral, authenticated screen marks. Never stored in a design or saved view. */
export function createRoomDrawings({ presentation, now = Date.now }) {
  let revision = presentation.snapshot().revision, marks = []
  const limits = new Map()
  function expire() {
    const current = presentation.snapshot().revision
    const next = current === revision ? marks.filter(mark => mark.expiresAt > now()) : []
    revision = current
    if (next.length !== marks.length) { marks = next; presentation.setDrawings(marks) }
  }
  return { expire, snapshot() { expire(); return { revision, drawings: marks, serverTime: now() } },
    publish(session, value) {
      expire()
      if (presentation.snapshot().ended || !session.streams?.size || session.role !== 'guest') throw new Error('Join the presentation before drawing')
      if (value?.revision !== revision) throw new Error('Wait for the current visualization before drawing')
      const author = session.participantId
      const previous = limits.get(author)
      const limit = previous && now() - previous.at < 1000 ? previous : { at: now(), count: 0 }
      if (++limit.count > 30) throw new Error('Too many drawing updates')
      limits.set(author, limit)
      if (value.clear === true) marks = marks.filter(mark => mark.author !== author)
      else {
        if (typeof value.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(value.id)) throw new Error('Invalid drawing identity')
        const camera = validateSharedCamera(value.camera), points = drawingPoints(value.points)
        if (marks.some(mark => mark.author === author && mark.id === value.id)) return { ok: true }
        marks = [...marks, { id: value.id, author, camera, points, color: session.color, revision,
          expiresAt: now() + DRAW_LIFETIME_MS }].slice(-256)
      }
      presentation.setDrawings(marks)
      return { ok: true }
    },
    leave(author) { marks = marks.filter(mark => mark.author !== author); limits.delete(author); presentation.setDrawings(marks) },
  }
}
