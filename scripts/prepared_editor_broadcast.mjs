import { randomBytes, createHash } from 'node:crypto'

function sourceHash(scene) {
  try {
    const length = scene.readUInt32LE(8)
    if (length > 16 * 1024 * 1024 || length + 16 > scene.length) return null
    return JSON.parse(scene.subarray(16, 16 + length).toString()).sourceHash ?? null
  } catch { return null }
}

/** Local management authority; guests never receive this short-lived lease. */
export function createEditorBroadcast({ room, rooms, maxGuests, now }) {
  let lease = null, seenAt = 0
  function pause() { lease = null; room.presentation.pause() }
  function expire() { if (lease && now() - seenAt > 15000) pause() }
  function start(options = {}) {
    expire()
    if (room.trajectory) throw new Error('Use the trajectory controls in Share link for this prepared clip. Update this same link with a static view before broadcasting visualizations.')
    if (options.cameraOnly && (!/^[a-f0-9]{64}$/.test(options.sourceHash ?? '') || options.sourceHash !== sourceHash(room.scene))) throw new Error('The editor design differs from this shared view. Enable Share current visualizations to publish it first.')
    if (lease) throw new Error('Another editor is broadcasting to this presentation. Stop it first or wait 15 seconds after it disconnects.')
    const occupied = [...rooms.values()].reduce((n, r) => n + [...r.sessions.values()].filter(s => s.role !== 'presenter').length +
      Number(!!([...r.sessions.values()].some(s => s.role === 'presenter') || r.editorBroadcast?.active)), 0)
    if (![...room.sessions.values()].some(s => s.role === 'presenter') && occupied >= maxGuests) throw new Error('This presentation is full (four participants including the presenter).')
    for (const session of room.sessions.values()) if (session.role === 'presenter') { session.away = true; session.generation++ }
    room.presentation.leavePresenter()
    lease = randomBytes(32).toString('hex'); seenAt = now()
    return { lease, revision: room.revision }
  }
  function apply(action, token, body) {
    expire()
    if (!lease || token !== lease) throw new Error('Editor broadcast has stopped. Start broadcasting again.')
    seenAt = now()
    if (action === 'pause') { pause(); return { ok: true } }
    if (action === 'heartbeat') return { revision: room.revision }
    if (action === 'camera') return room.presentation.publish(JSON.parse(body))
    if (action !== 'scene') throw new Error('Unknown broadcast action')
    if (body.length > 512 * 1024 * 1024 || body.subarray(0, 8).toString() !== 'NADOCVW1') throw new Error('Invalid prepared viewer update')
    if ([...rooms.values()].reduce((n, r) => n + (r === room ? body.length : r.scene.length), 0) > 512 * 1024 * 1024) throw new Error('Shared views exceed the 512 MiB host capacity')
    room.scene = body; room.revision = createHash('sha256').update(body).digest('hex')
    room.presentation.replaceRevision(room.revision)
    return { revision: room.revision }
  }
  return { start, apply, expire, pause, get active() { expire(); return !!lease } }
}
