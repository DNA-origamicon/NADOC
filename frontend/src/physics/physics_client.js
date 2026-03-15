/**
 * Physics layer — WebSocket client for XPBD position streaming.
 *
 * Connects to /ws/physics on the backend and receives real-time relaxed
 * backbone positions.  Never writes to the topological or geometric layers.
 *
 * Protocol (mirrors backend/api/ws.py):
 *   Client → Server: {"action": "start_physics"}
 *   Server → Client: {"type": "positions", "step": int, "data": [{...}]}
 *   Client → Server: {"action": "stop_physics"}
 *   Client → Server: {"action": "reset_physics"}
 *
 * Usage:
 *   const client = initPhysicsClient({
 *     onPositions: (updates, step) => { ... },
 *     onStatus:    (msg) => { ... },
 *   })
 *   client.start()   // connect + send start_physics
 *   client.reset()   // send reset_physics (rebuilds SimState on server)
 *   client.stop()    // send stop_physics + close WebSocket
 *   client.isActive  // boolean
 */

const WS_URL = (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.hostname}:8000/ws/physics`
})()

/**
 * Initialise a physics WebSocket client.
 *
 * @param {{ onPositions: function, onStatus: function }} callbacks
 * @returns {{ start, stop, reset, get isActive }}
 */
export function initPhysicsClient({ onPositions, onStatus } = {}) {
  let _ws     = null
  let _active = false

  function _onMessage(event) {
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }

    if (msg.type === 'positions' && typeof onPositions === 'function') {
      onPositions(msg.data, msg.step)
    } else if (msg.type === 'status' && typeof onStatus === 'function') {
      onStatus(msg.message)
    } else if (msg.type === 'error' && typeof onStatus === 'function') {
      onStatus(`Error: ${msg.message}`)
    }
  }

  function _send(obj) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify(obj))
    }
  }

  function start({ useStraight = false } = {}) {
    // If an open connection exists, just (re)start physics on the server side.
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _active = true
      _send({ action: 'start_physics', use_straight: useStraight })
      return
    }

    // If still connecting or closing, close it first and fall through to create a new one.
    if (_ws && _ws.readyState !== WebSocket.CLOSED) {
      _ws.onclose = null  // suppress stale handler
      _ws.close()
      _ws = null
    }

    const ws = new WebSocket(WS_URL)
    _ws = ws

    ws.onopen = () => {
      if (_ws !== ws) return  // superseded by a later start() call
      _active = true
      _send({ action: 'start_physics', use_straight: useStraight })
    }

    ws.onmessage = _onMessage

    ws.onerror = (e) => {
      console.warn('[PhysicsClient] WebSocket error', e)
    }

    ws.onclose = () => {
      // Only update state if this is still the active connection.
      if (_ws === ws) {
        _active = false
        _ws = null
      }
    }
  }

  function stop() {
    _active = false
    const ws = _ws
    _ws = null
    if (ws) {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: 'stop_physics' }))
      ws.close()
    }
  }

  function reset() {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _send({ action: 'reset_physics' })
    } else if (!_ws) {
      // No connection — start fresh.
      start()
    }
    // If WS exists but not yet OPEN (CONNECTING), do nothing — onopen will send start_physics.
  }

  /**
   * Update simulation parameters live (wired to UI sliders).
   *
   * @param {{ noise_amplitude?, bond_stiffness?, bend_stiffness?, bp_stiffness? }} params
   */
  function updateParams(params) {
    _send({ action: 'update_params', ...params })
  }

  return {
    start,
    stop,
    reset,
    updateParams,
    get isActive() { return _active },
  }
}
