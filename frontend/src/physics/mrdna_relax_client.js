/**
 * WebSocket client for the mrdna CG relaxation endpoint (/ws/mrdna-relax).
 *
 * One-shot: connect → receive progress → receive result → close.
 *
 * Usage:
 *   const client = initMrdnaRelaxClient({ onProgress, onResult, onError })
 *   client.run()
 *   client.cancel()
 */

const _WS_URL = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/mrdna-relax`
})()

/**
 * @param {{
 *   onProgress: (stage: string, pct: number) => void,
 *   onResult:   (msg: {positions, stats}) => void,
 *   onError:    (message: string) => void,
 * }} callbacks
 */
export function initMrdnaRelaxClient({ onProgress, onResult, onError }) {
  let _ws = null

  function run() {
    cancel()
    _ws = new WebSocket(_WS_URL)

    _ws.onmessage = ({ data }) => {
      let msg
      try { msg = JSON.parse(data) } catch { return }

      if (msg.type === 'mrdna_progress') {
        onProgress(msg.stage ?? '', msg.pct ?? 0)
      } else if (msg.type === 'mrdna_result') {
        onResult(msg)
      } else if (msg.type === 'mrdna_error') {
        onError(msg.message ?? 'mrdna error')
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
