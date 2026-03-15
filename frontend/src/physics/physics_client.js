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

  function start() {
    if (_ws && _ws.readyState !== WebSocket.CLOSED) {
      // Already connected — just (re)start physics on the server side.
      _send({ action: 'start_physics' })
      return
    }

    _ws = new WebSocket(WS_URL)

    _ws.onopen = () => {
      _active = true
      _send({ action: 'start_physics' })
    }

    _ws.onmessage = _onMessage

    _ws.onerror = (e) => {
      console.warn('[PhysicsClient] WebSocket error', e)
    }

    _ws.onclose = () => {
      _active = false
    }
  }

  function stop() {
    _active = false
    if (_ws) {
      _send({ action: 'stop_physics' })
      _ws.close()
      _ws = null
    }
  }

  function reset() {
    if (_active && _ws && _ws.readyState === WebSocket.OPEN) {
      _send({ action: 'reset_physics' })
    } else {
      // Not connected yet — start fresh.
      start()
    }
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
