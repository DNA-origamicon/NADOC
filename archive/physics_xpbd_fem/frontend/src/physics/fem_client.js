/**
 * WebSocket client for the FEM analysis endpoint (/ws/fem).
 *
 * The FEM solve is one-shot: connect → receive progress + result → close.
 * Mirrors the interface style of physics_client.js for consistency.
 *
 * Usage:
 *   const fem = initFemClient({ onProgress, onResult, onError })
 *   fem.run()      // starts a new solve (cancels any in-progress run)
 *   fem.cancel()   // abort and close the WebSocket
 */

const _WS_URL = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/fem`
})()

/**
 * @param {{
 *   onProgress: (stage: string, pct: number) => void,
 *   onResult:   (msg: {positions, rmsf, stats}) => void,
 *   onError:    (message: string) => void,
 * }} callbacks
 */
export function initFemClient({ onProgress, onResult, onError }) {
  let _ws = null

  function run() {
    // Cancel any existing connection before starting a new one.
    cancel()

    _ws = new WebSocket(_WS_URL)

    _ws.onmessage = ({ data }) => {
      let msg
      try { msg = JSON.parse(data) } catch { return }

      if (msg.type === 'fem_progress') {
        onProgress(msg.stage ?? '', msg.pct ?? 0)
      } else if (msg.type === 'fem_result') {
        onResult(msg)
      } else if (msg.type === 'fem_error') {
        onError(msg.message ?? 'FEM error')
      }
    }

    _ws.onerror = () => {
      onError('WebSocket connection error — is the backend running?')
    }

    _ws.onclose = () => {
      _ws = null
    }
  }

  function cancel() {
    if (_ws) {
      _ws.onmessage = null
      _ws.onerror   = null
      _ws.onclose   = null
      _ws.close()
      _ws = null
    }
  }

  return { run, cancel }
}
